# AC Induction Motor Digital Twin — Full Implementation Plan (Python + React + MySQL)

Simulation-first, all sensor modalities modeled, hardware pluggable later via a sensor abstraction layer so nothing has to be rewritten when real hardware shows up.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  SIMULATION CORE (Python)                                            │
│  State-space induction motor (RK4) + fault injectors                 │
└───────────────┬────────────────────────────────────────────────────┘
                │ ground-truth motor state (currents, speed, torque, temp)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SENSOR ABSTRACTION LAYER                                            │
│  Sensor interface → SimulatedSensor (now) | HardwareSensor (later)   │
│  6 channels: current, vibration(x/y/z), acoustic, temp, speed, volt   │
└───────────────┬────────────────────────────────────────────────────┘
                │ raw per-sensor streams
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DIAGNOSTIC ENGINE                                                    │
│  • Electrical: DT current-residual method (MCSA, no ML needed)       │
│  • Vibration/Acoustic: wavelet+FFT features → Conv-BiLSTM classifier  │
│  • Thermal: threshold + rate-of-rise                                 │
│  • Fusion: weighted verdict across channels                          │
└───────────────┬────────────────────────────────────────────────────┘
                │ fused diagnosis + severity score
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SUPERVISORY LAYER (SADA)                                             │
│  confidence gating → severity smoothing → torque derate / trip       │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FASTAPI BACKEND — REST + WebSocket                                   │
│  MySQL (SQLAlchemy) for persistence                                   │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  REACT FRONTEND — per-sensor panels + fused dashboard + SADA controls │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend framework | **FastAPI** (Python 3.11+) | async-native, WebSocket support, Pydantic validation, auto OpenAPI docs |
| Simulation loop | `asyncio` background task, fixed-rate tick | decoupled from HTTP request cycle, mirrors a real acquisition loop |
| Numerics | NumPy, SciPy (`scipy.signal` for Welch PSD, filtering) | RK4 solver, spectral analysis |
| Wavelets | PyWavelets (`pywt`) | CWT scalogram + DWT energy decomposition |
| ML | PyTorch (or TensorFlow/Keras — pick one) | Conv-BiLSTM for vibration/acoustic classification |
| ORM / migrations | SQLAlchemy 2.x + Alembic | schema versioning |
| Database | MySQL 8 | as specified |
| Streaming to frontend | WebSocket (FastAPI native) + optional Redis pub/sub if you scale to multiple backend workers | live sensor + diagnosis feed |
| Task scheduling | APScheduler (or Celery+Redis if it grows) | periodic model retraining, log rotation |
| Frontend | React + Vite + TypeScript | fast dev loop, typed sensor payloads |
| Charts | Recharts or Plotly.js (Plotly if you want scalograms/heatmaps easily) | waveform, spectrum, scalogram, gauges |
| Frontend state/streaming | native WebSocket client + React Query for REST | live + cached data |
| Styling | Tailwind CSS | fast to build a clean per-sensor dashboard |
| Containerization | Docker Compose (backend, mysql, frontend, optional redis) | one command to run everything |
| Testing | pytest (backend), Vitest/React Testing Library (frontend) | |

---

## 3. Sensor Abstraction Layer (built hardware-ready from day one)

Every sensor implements a common interface so a simulated sensor and a real one are interchangeable without touching the diagnostic engine:

```python
class Sensor(ABC):
    @abstractmethod
    async def read(self) -> SensorFrame: ...
    def calibrate(self, raw) -> float: ...   # raw counts → physical units

class SimulatedCurrentSensor(Sensor): ...      # pulls from motor twin state
class SimulatedVibrationSensor(Sensor): ...    # synthetic BPFO/BPFI/BSF/FTF signal
class SimulatedAcousticSensor(Sensor): ...
class SimulatedTempSensor(Sensor): ...
class SimulatedSpeedSensor(Sensor): ...
class SimulatedVoltageSensor(Sensor): ...

# later, drop-in:
class ADS1115CurrentSensor(Sensor): ...        # reads real ADC over I2C/serial
class MQTTVibrationSensor(Sensor): ...         # subscribes to an ESP32 publishing over MQTT
```

A `SensorRegistry` config (JSON/YAML or DB row) decides at startup which implementation backs each channel — `mode: "simulated" | "hardware"` per sensor. Switching to hardware later is a config change, not a rewrite.

### Full sensor set (all six, simulated now)

| Sensor | Signal generated | Faults it targets |
|---|---|---|
| Current transducer (3-phase) | stator current via RK4 twin | broken rotor bar, inter-turn short, eccentricity (MCSA) |
| Tri-axial accelerometer | vibration with BPFO/BPFI/BSF/FTF injected per fault | bearing IR/OR/ball, unbalance, misalignment |
| Acoustic/microphone | broadband + impulsive bursts correlated with vibration | bearing defects, mechanical looseness |
| Thermocouple/IR temp | slow thermal model (RC lag) driven by load + fault heat | overload, insulation degradation, poor lubrication |
| Encoder/tachometer | shaft speed/slip | normalizes all other signals to RPM — required by nearly every other feature |
| Voltage sensor (3-phase) | supply voltage, optionally with injected imbalance/sag | distinguishes supply-side anomalies from real motor faults |

---

## 4. Simulation Core

- Induction motor state-space model in the α-β frame (per the Chen et al. digital-twin paper): stator currents + rotor flux states, RK4 integration, event-driven step size at PWM switching instants.
- **Fault injector module**, one function per fault, each parameterized by severity:
  - `inject_broken_rotor_bar(count, position)`
  - `inject_interturn_short(phase, severity_eta)`
  - `inject_eccentricity(type, severity)`
  - `inject_bearing_fault(type: IR|OR|Ball, severity)` → drives the vibration/acoustic generators, not the electrical model
  - `inject_unbalance(magnitude)`, `inject_misalignment(magnitude)`
  - `inject_voltage_anomaly(type: sag|imbalance|harmonic)`
- Motor + fault state lives in one `MotorTwinState` object updated every tick; all sensor simulators read from it, so cross-sensor consistency is automatic (e.g., a bearing fault shows up in vibration *and* acoustic *and* faint current sidebands together, not independently).

---

## 5. Diagnostic Engine

**Electrical (no ML — physics residual method):**
- Maintain a parallel *healthy-state* digital twin (frozen params) running alongside the faulted simulation.
- α-β current residual → FD (detection) and FL (localization) indices, exactly as in Phase 2 of the earlier plan.

**Vibration/Acoustic (ML):**
- Framing: 0.5s window / 0.2s hop.
- Features: RMS, kurtosis, skewness, crest factor, peak-to-peak, variance, Welch-PSD band energies, spectral entropy/centroid/spread/flatness (~20 features).
- Conv-BiLSTM (32→64 conv filters, 64-unit BiLSTM, softmax over healthy/IR/OR/ball/unbalance/misalignment).
- **Leak-safe evaluation is mandatory**: group by simulation run (not by frame), train-only normalization, multi-seed reporting.

**Thermal:** simple threshold + rate-of-rise check (no ML needed).

**Fusion:** weighted-voting verdict combining all channel outputs into one `{fault_type, confidence, severity}` schema — freeze this schema before building the API around it.

---

## 6. Database Schema (MySQL)

```
motors            (id, name, rated_power, rated_speed, rated_torque, params_json, created_at)
sensors           (id, motor_id, type ENUM('current','vibration','acoustic','temp','speed','voltage'),
                    mode ENUM('simulated','hardware'), config_json)
sensor_readings   (id, sensor_id, ts, window_start, window_end, feature_vector_json, raw_ref BLOB/NULL)
                    -- store extracted features always; store raw waveform only on anomaly/on-demand
                    -- (raw high-rate waveforms are too heavy for MySQL row storage otherwise)
diagnoses         (id, motor_id, ts, fault_type, confidence, severity_score, per_sensor_scores_json,
                    source ENUM('electrical_residual','ml_classifier','thermal','fused'))
faults_injected   (id, motor_id, fault_type, severity, start_ts, end_ts)   -- ground truth for sim runs
supervisory_actions (id, motor_id, ts, state, load_cmd, reason_code, trip BOOLEAN)
alerts            (id, motor_id, ts, severity, message, acknowledged BOOLEAN)
users             (id, username, role, ...)                                -- if you want auth
```

Indexes on `(motor_id, ts)` everywhere you'll query time ranges. Use Alembic migrations from the start so schema changes don't require manual `ALTER TABLE`s later (your DC plan flagged this exact pain point).

---

## 7. Backend API

**REST (FastAPI):**
```
POST   /motors                          register a motor (simulated config)
GET    /motors/{id}                     motor details + current state
POST   /motors/{id}/faults               inject a fault into the running simulation
DELETE /motors/{id}/faults/{fault_id}    clear an injected fault
GET    /motors/{id}/sensors              list sensors + mode (simulated/hardware)
PATCH  /motors/{id}/sensors/{id}         switch a sensor's mode (sim → hardware later)
GET    /motors/{id}/diagnoses            history, paginated, filterable by time range/fault_type
GET    /motors/{id}/history              fault + supervisory action timeline
POST   /motors/{id}/supervisory/override manual operator override (ack/reset)
```

**WebSocket:**
```
/ws/motors/{id}/stream    → pushes: per-sensor live readings, fused diagnosis, supervisory state
                              at ~5-10 Hz for UI (raw sim runs much faster internally)
```

---

## 8. Frontend (React)

- **Dashboard layout:** one panel per sensor (waveform + spectrum, vibration also gets a scalogram), plus one fused "overall diagnosis" panel and a SADA supervisory status panel (load %, reason code, trip state).
- **Fault injection console:** buttons/sliders to inject each fault type + severity into the simulation, for demoing/testing without hardware.
- **Sensor mode toggle:** per-sensor UI to switch simulated↔hardware once real sensors exist (calls the `PATCH /sensors/{id}` endpoint).
- **History view:** timeline of diagnoses + supervisory actions, filterable.
- Keep charts consistent (grayscale or a fixed palette) from day one rather than retrofitting a theme later.

---

## 9. Build Order (phased, each phase ends in something runnable)

- [tick] **Phase 0** — repo scaffold: FastAPI app, MySQL via Docker Compose, Alembic init, React app skeleton
- [ ] **Phase 1** — simulation core: RK4 induction motor twin, healthy-state validated (twin current ≈ simulated "real" motor current)
- [ ] **Phase 2** — sensor abstraction layer + all 6 simulated sensors wired to `MotorTwinState`
- [ ] **Phase 3** — fault injectors for all fault types, verified each produces the expected signature (MCSA sideband, BPFO/BPFI peak, thermal ramp, etc.)
- [ ] **Phase 4** — electrical diagnostic (current residual FD/FL) — no ML, fastest win
- [ ] **Phase 5** — vibration/acoustic feature pipeline + Conv-BiLSTM, leak-safe evaluation
- [ ] **Phase 6** — fusion layer, frozen output schema
- [ ] **Phase 7** — MySQL persistence + REST API
- [ ] **Phase 8** — WebSocket live streaming
- [ ] **Phase 9** — SADA supervisory layer (severity smoothing, confidence gating, graded derate, emergency trip)
- [ ] **Phase 10** — React dashboard: per-sensor panels → fused panel → SADA panel → fault injection console
- [ ] **Phase 11** — Docker Compose packaging, docs, test suite (pytest + Vitest), CI
- [ ] **Phase 12 (future)** — swap in real `HardwareSensor` implementations one channel at a time; nothing above this layer changes


# AC Motor Digital Twin — Production-Grade Architecture Addendum

Everything from the previous plan stands (sensors, simulation core, diagnostic engine, SADA). This layers on what turns it from a working prototype into something you'd actually run and trust.

---

## 1. Non-Functional Requirements

| Concern | Target |
|---|---|
| Availability | Backend survives a diagnostic-engine crash without taking down the API or simulation loop |
| Auth | Every endpoint and WebSocket connection authenticated; role-based access (viewer / operator / admin) |
| Data integrity | No silent data loss — every fault injection, diagnosis, and supervisory action is durably logged before it's acted on |
| Observability | Every request traceable end-to-end; metrics exportable; alerts fire on their own before a human notices |
| Scalability | Multiple motors, multiple concurrent WebSocket viewers, without a rewrite |
| Reproducibility | Same config + same fault sequence → same diagnostic output (deterministic seeding) |
| Security | No secrets in code/repo; TLS everywhere in prod; input validated at every boundary |

---

## 2. Revised Architecture (with cross-cutting concerns)

```
                         ┌───────────────────────────────┐
                         │   Nginx / Reverse Proxy (TLS)   │
                         └──────────────┬──────────────────┘
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
            React (static build)   FastAPI (REST)     FastAPI (WebSocket)
                                        │                    │
                    ┌───────────────────┴────────────────────┘
                    ▼
          ┌─────────────────────┐        ┌─────────────────┐
          │  Auth / RBAC layer   │        │  Redis pub/sub   │──▶ fan-out live
          └─────────┬────────────┘        │  (scaling WS)    │   sensor/diagnosis
                    ▼                     └─────────┬─────────┘   events across
          Simulation + Diagnostic + SADA             │            backend workers
          (background asyncio workers, one           │
           per motor instance, supervised)           ▼
                    │                        ┌─────────────────┐
                    ▼                        │  Structured logs  │──▶ log aggregator
          ┌─────────────────────┐            │  (JSON, per req)  │   (ELK/Loki)
          │  SQLAlchemy + pool   │            └─────────────────┘
          └─────────┬────────────┘                    │
                    ▼                                  ▼
              MySQL (primary)                 Prometheus metrics
              + read replica (optional)        + Grafana dashboards
              + scheduled backups
```

---

## 3. Security & Auth

- **Authentication:** JWT-based (access + refresh tokens), issued by a `/auth/login` endpoint; passwords hashed with `bcrypt`/`argon2`. If this ever needs SSO, keep the auth layer abstracted behind a single dependency so swapping to OAuth2/OIDC later doesn't touch business logic.
- **Authorization (RBAC):** three roles minimum — `viewer` (read-only dashboards), `operator` (can inject faults, override supervisory actions), `admin` (manage motors/sensors/users). Enforce via FastAPI dependencies on every route, not just in the frontend.
- **WebSocket auth:** token passed at connection handshake (query param or subprotocol), validated before the socket is accepted into any Redis channel.
- **Input validation:** every request/response modeled with Pydantic schemas — reject malformed fault-injection payloads (e.g., severity out of [0,1]) at the API boundary, never in the simulation core.
- **Secrets management:** no secrets in `.env` committed to the repo. Use `.env.example` for structure, real secrets injected via environment variables at deploy time (Docker secrets, or a vault if you have one available).
- **CORS:** explicit allow-list of origins (frontend URL only), not `*`, once you're past local dev.
- **Rate limiting:** on `/auth/login` and fault-injection endpoints at minimum (e.g., `slowapi`) — prevents someone from hammering the simulation with fault injections.
- **Dependency hygiene:** `pip-audit` / `npm audit` in CI, pinned versions (`requirements.txt` with hashes or `poetry.lock`, `package-lock.json`).

---

## 4. Scalability & Performance

**Simulation workers:** run each motor's simulation+diagnostic loop as its own supervised asyncio task (or separate process via `multiprocessing`/Celery worker if CPU-bound ML inference starts blocking the event loop). One motor's crash must not take down others — wrap each loop in a supervisor that restarts it and logs the failure.

**WebSocket fan-out:** don't have each backend worker hold its own list of connected clients if you run more than one backend replica — use **Redis pub/sub** as the broker; any worker can publish a diagnosis event, any worker's WebSocket connections receive it. This is what makes horizontal scaling of the backend possible later.

**MySQL at scale — this is the part that will bite you first:**
- Raw waveform data is high-rate; do **not** write every raw sample to MySQL. Persist:
  - extracted feature vectors per window (small, structured) — always
  - raw waveform snapshots only on anomaly/on-demand (store as a blob or in object storage with a DB pointer, not inline)
- Partition `sensor_readings` and `diagnoses` tables by time (MySQL native `PARTITION BY RANGE` on a date column) so old-data queries and retention cleanup stay fast.
- Add a **retention policy job** (APScheduler cron) that rolls up or archives readings older than N days rather than growing the table indefinitely.
- Use connection pooling (`SQLAlchemy` pool_size tuned to worker count) and read replicas if dashboard read load grows separately from write load.

**Caching:** cache "current motor state" and "latest diagnosis per motor" in Redis so dashboard polling doesn't hit MySQL for every refresh — WebSocket pushes cover live updates, REST reads can serve from cache with a short TTL as fallback.

---

## 5. Reliability & Error Handling

- **Health checks:** `/healthz` (liveness) and `/readyz` (readiness — DB reachable, simulation workers running) for every deployment target (Docker healthcheck, k8s probes if you go there).
- **Graceful degradation:** if the ML diagnostic model fails to load or errors on inference, the electrical-residual (non-ML) diagnostic path must keep working — never let one diagnostic channel's failure block the others or the SADA supervisory loop.
- **Circuit breaker pattern** reserved for hardware sensors later — if a real sensor stops responding, fall back to "stale/unknown" status rather than blocking the fusion layer indefinitely.
- **Idempotency:** fault-injection and supervisory-override endpoints should be safe to retry (client-generated request IDs, dedup on the server).
- **Graceful shutdown:** on SIGTERM, stop accepting new WebSocket connections, flush pending DB writes, cleanly stop simulation loops — don't just kill the process (this matters for zero-downtime deploys).

---

## 6. Observability

- **Structured logging:** JSON logs with request ID, motor ID, and timestamp on every log line (`structlog` or Python's `logging` with a JSON formatter). Ship to an aggregator (ELK, Loki+Grafana, or even just persistent volume + `docker logs` for a smaller deployment).
- **Metrics:** expose a `/metrics` endpoint (Prometheus format) tracking: simulation tick rate, diagnosis latency, WebSocket connection count, DB query latency, fault-injection rate, SADA trip count. Grafana dashboard on top.
- **Alerting:** wire Prometheus Alertmanager (or even a simple threshold check) to page on: simulation loop stalled, DB connection pool exhausted, error rate spike — this is the "who watches the watcher" layer for the DT itself.
- **Tracing (optional but worth it):** OpenTelemetry spans across REST request → diagnostic engine → DB write, so a slow request is debuggable end-to-end.

---

## 7. CI/CD Pipeline

```
on push/PR:
  1. lint (ruff/flake8 for Python, eslint for React)
  2. type check (mypy, tsc)
  3. unit tests (pytest, Vitest) — must pass, coverage threshold enforced
  4. integration tests (spin up MySQL via testcontainers, run API tests against it)
  5. security scan (pip-audit, npm audit, optionally Trivy on the built image)
  6. build Docker images, tag with commit SHA
  7. (on main branch merge) push images to registry
  8. (on release tag) deploy — staging first, manual promote to prod
```

Keep `alembic upgrade head` as an explicit, separate deploy step (never auto-run migrations silently in app startup for prod) — you want a human/CI gate on schema changes touching a live DB.

---

## 8. Testing Strategy

| Layer | What to test |
|---|---|
| Simulation core | RK4 twin matches expected healthy-state waveform within tolerance; each fault injector produces its known spectral signature (unit tests with assertions on FFT peaks, not just "it runs") |
| Diagnostic engine | Electrical residual FD/FL indices cross known thresholds on injected faults; ML classifier evaluated with the leak-safe grouped protocol from the earlier plan, checked in CI against a frozen validation set so accuracy regressions are caught |
| API | Contract tests per endpoint (status codes, schema validation, auth enforcement) |
| WebSocket | Connection auth rejection, message schema, reconnect behavior |
| Frontend | Component tests (React Testing Library) for dashboard panels + fault-injection console; at least a few end-to-end tests (Playwright/Cypress) covering "inject fault → see it appear in dashboard → see SADA derate" |
| Load | k6 or Locust: N concurrent WebSocket viewers, M motors simulating concurrently — establishes real capacity numbers rather than guessing |

---

## 9. Configuration & Environments

- Three environments minimum: **local** (docker-compose, seeded test data), **staging** (mirrors prod topology, safe to break), **production**.
- All environment-specific values (DB host, Redis host, JWT secret, CORS origins) come from environment variables — a single `config.py` (Pydantic `BaseSettings`) reads them, nothing hardcoded.
- Feature flags for anything experimental (e.g., a new fault type or a new ML model version) so you can roll out to staging without a prod deploy.

---

## 10. Deployment Topology

- **Simplest production-viable setup:** Docker Compose on a single VM — Nginx (TLS via Let's Encrypt) → FastAPI (2-3 replicas behind Nginx) + Redis + MySQL (managed MySQL service strongly preferred over self-hosted for backups/HA) + React static build served by Nginx.
- **If you outgrow one VM:** move to Kubernetes — but don't start there; it adds real operational overhead you don't need until you have multiple motors/high concurrent load.
- **Backups:** automated daily MySQL backups (managed DB service handles this, or `mysqldump` + offsite storage cron if self-hosted), with a documented, *tested* restore procedure — an untested backup is not a backup.
- **Zero-downtime deploys:** rolling restart of backend replicas behind Nginx, health-checked before traffic cutover.

---

## 11. API Versioning & Documentation

- Prefix routes `/api/v1/...` from day one — free insurance against breaking the frontend when the schema evolves.
- FastAPI's auto-generated OpenAPI docs (`/docs`) kept accurate by relying on Pydantic models as the single source of truth (no hand-written docs that drift).
- A `CHANGELOG.md` and versioned Docker image tags so you always know exactly what's deployed where.

---

## 12. Updated Build Order

Everything from the earlier 12-phase plan stays, with these production-hardening phases inserted/appended:

- [tick] Phase 0 — repo scaffold **including** CI pipeline skeleton, Docker Compose for local dev, Alembic, `.env.example`
- [ ] Phases 1–11 — as before (simulation → sensors → faults → diagnostics → fusion → persistence → streaming → SADA → frontend)
- [ ] **Phase 12 — Auth & RBAC**: JWT login, role-gated endpoints and WebSocket
- [ ] **Phase 13 — Observability**: structured logging, `/metrics`, health/readiness endpoints, basic Grafana dashboard
- [ ] **Phase 14 — Resilience**: supervised simulation workers, graceful shutdown, retention/partitioning job for MySQL
- [ ] **Phase 15 — Testing & CI hardening**: coverage thresholds, integration tests against real MySQL, load test baseline
- [ ] **Phase 16 — Staging deploy**: full topology (Nginx/TLS/Redis/MySQL) mirrored, smoke-tested
- [ ] **Phase 17 — Production cutover**: backups verified via test restore, alerting wired, versioned release
- [ ] **Phase 18 (future)** — swap in real hardware sensors per channel, behind the abstraction layer, staged through the same CI/staging/prod pipeline as any other change
