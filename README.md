# AC Induction Motor Fault-Detection Digital Twin

A simulation-first digital twin of a 1.5 kW induction motor. It streams six simulated sensor
channels, diagnoses faults with a physics residual method plus a Conv-BiLSTM, fuses the verdicts,
and drives a supervisory layer that derates or trips the motor. A React dashboard shows it live.
Every sensor sits behind an abstraction layer, so real hardware can replace a simulated channel
through configuration. No other code has to change.

See [`implementation.md`](implementation.md) for the original plan and per-phase status.

![Dashboard with an injected outer-race bearing fault: Conv-BiLSTM detects it, SADA derates the load](docs/dashboard.png)

```
simulator (RK4 plant + fault injectors) ─▶ 6 sensors (sim | hardware) ─▶ diagnostic engine
   electrical DT residual · Conv-BiLSTM vibration/acoustic · thermal · supply ─▶ fusion
   ─▶ SADA (gating, smoothing, derate, trip) ─▶ FastAPI REST + WebSocket ─▶ React dashboard
                                         └▶ MySQL (Alembic) · Redis pub/sub · Prometheus
```

## Quick start (Docker)

```bash
cp .env.example .env          # set passwords and JWT_SECRET
docker compose up --build     # mysql, redis, one-shot migration, backend, frontend
```

Open http://localhost:8080 and sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. A demo motor is
created on first start. The API docs are at http://localhost:8080/api/v1/docs.

Set `INSTALL_ML=false` as a build arg to skip PyTorch. The vibration channel then uses the
rule-based fallback, and everything else works the same.

## Local development

```bash
# backend (Python 3.11+)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt          # hash-pinned
pip install torch --index-url https://download.pytorch.org/whl/cpu   # optional (ML channel)
DATABASE_URL=sqlite:///./dev.db AUTO_CREATE_SCHEMA=true ADMIN_USERNAME=admin ADMIN_PASSWORD=admin-pass-123 \
  uvicorn app.main:create_app --factory --reload --port 8000

# frontend
cd frontend && npm ci && npm run dev         # http://localhost:5173 (proxies /api to :8000)
```

## What is in the box

| Area | Where | Notes |
|---|---|---|
| Motor model | `backend/app/simulation/` | Live simulation uses `plant.py` and `twin_state.py` with fixed-step RK4 integration at 5 kHz. Reference and validation models (`loop.py`, `motor_twin.py`, `pwm.py`, `dynamics.py`, `integrators.py`) provide offline verification and test bench comparison. |
| Fault injectors | `simulation/faults.py`, `state_space_solver.py` | Mathematical fault models: Stator Inter-turn Short Circuit (ITSC: $\mu = N_{sc}/N_s$ with circulating current matrix $\mathbf{v}_s = \mathbf{R}_s \mathbf{i}_s + d\boldsymbol{\psi}_s/dt$), Broken Rotor Bars (BRB: $R_r(\theta_r)$ rotor asymmetry yielding $\ge 15\text{ dB}$ sidebands), Dynamic Eccentricity ($L_m(\theta_m)$ angular permeance model), bearing defects, unbalance, misalignment. Motors start healthy; set `SEED_DEFAULT_FAULTS=true` to pre-seed demo faults on startup. |
| MCSA & Thermal | `diagnostics/mcsa.py`, `simulation/thermal_lptn.py` | High-resolution MCSA pipeline ($F_s \ge 5000\text{ Hz}$) with flat-top/Hann windowing, Welch PSD, and automated peak detection for $f_{BRB} = f_s(1 \pm 2ks)$ and $f_{ecc} = f_s \pm f_r$. 4-Node Lumped Parameter Thermal Network ($T_w, T_t, T_r, T_b$) coupled with classical Arrhenius thermal insulation degradation model ($\text{Life} = A \cdot \exp(E_a / (k_B T_w))$). |
| Sensors | `backend/app/sensors/` | Current, voltage, speed, temperature, tri-axial vibration, acoustic. `SensorRegistry` switches each channel between simulated and hardware. The hardware classes are placeholders behind a circuit breaker and report `stale`. |
| Electrical diagnosis | `diagnostics/electrical.py` | A frozen healthy twin is driven by the measured voltage and speed. It computes the FD/FL indices and classifies the fault from the residual spectrum. No ML. |
| Vibration/acoustic ML | `diagnostics/features.py`, `diagnostics/ml/` | 28 features × 4 channels per 0.5 s window with a 0.2 s hop. The model is Conv(32)→Conv(64)→BiLSTM(64). Training is leak-safe: grouped by run, normalization fitted on training data only, 3 seeds. A rule-based fallback takes over if torch or the model is unavailable. |
| Thermal / supply | `diagnostics/thermal.py`, `supply.py` | Thermal uses a threshold plus rate-of-rise check. Supply uses VUF, THD and sag, so supply problems are not mistaken for motor faults. |
| Fusion | `diagnostics/fusion.py`, `schema.py` | Weighted voting. The output schema is frozen at v1.0. |
| Supervisory SADA | `supervisory/sada.py` | Confidence gate, EMA smoothing, anti-hunting dwell times, graded derate from 100 % to 50 %, latched trip, emergency and thermal trips, and operator ack, reset and manual load. |
| API | `backend/app/api/` | `/api/v1/...` REST, and a WebSocket at `/api/v1/ws/motors/{id}/stream`. JWT auth with viewer/operator/admin roles on every route. Idempotency keys, rate limits, Pydantic validation. Transient simulation solve and MCSA endpoints. |
| Runtime | `backend/app/runtime/` | One supervised worker per motor with restart backoff. Batched DB writer with high-priority audit queue. In-memory or Redis broker, with a per-motor ownership lock for multiple replicas. Retention job. |
| Observability | `core/logging.py`, `core/metrics.py`, `deploy/` | JSON logs carry the request id and motor id. `/metrics`, `/healthz` and `/readyz` are exposed. Prometheus alert rules and a Grafana dashboard are provisioned. |
| Frontend | `frontend/` | Fleet operations grid, motor provisioning modal (7 presets + custom dq physics), DSA priority queue, live telemetry deck with Telemetry Mode Badge (`Real Hardware Stream` vs. `Dynamic State-Space Emulation`), 4-node LPTN thermal matrix & Arrhenius RUL meter, parameters studio, database inspector, and 8-chapter interactive Engineering & Physics Documentation Book (`EngineeringDocsModal.tsx`) featuring book spine styling, turn-page navigation, dedicated chapter on Data Structures & Algorithmic Foundations (DSA: Binary Max-Heap priority queues, O(1) circular ring buffers, SADA hysteresis FSM, hash registries), dedicated main dashboard footer (`https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin · 2026 · Naavalanarul · MIT License`), and in-depth explanations of scientific libraries, state-space ODEs, mathematical fault models, first-principles sensor synthesis, multi-modal diagnostics, system architecture, and research papers with DOI links. |
| Ops | `compose.yaml`, `compose.prod.yaml`, `deploy/`, `.github/workflows/ci.yml` | Local and production stacks, TLS edge, backups with a tested restore check, CI/CD. See [docs/operations.md](docs/operations.md). |

## API summary

```
POST /api/v1/auth/login | /auth/refresh      GET /api/v1/auth/me      GET|POST /api/v1/users (admin)
GET  /api/v1/system/db-status                POST /api/v1/system/db-test (test/apply MySQL password)
GET  /api/v1/motors                          POST /api/v1/motors (admin)
GET  /api/v1/motors/{id}                     details + current state
PATCH /api/v1/motors/{id}/params             update motor equivalent circuit & thermal params (admin)
POST /api/v1/motors/{id}/simulation/transient-solve (on-demand RK45 state-space dynamic solve)
GET  /api/v1/motors/{id}/mcsa                high-res MCSA spectral peaks and Welch PSD
PATCH /api/v1/motors/{id}/load               process load demand (operator)
POST /api/v1/motors/{id}/faults              inject (operator; Idempotency-Key supported)
GET  /api/v1/motors/{id}/faults              DELETE /api/v1/motors/{id}/faults/{fault_id}
GET  /api/v1/motors/{id}/sensors             PATCH /api/v1/motors/{id}/sensors/{sensor_id} (admin)
GET  /api/v1/motors/{id}/diagnoses?start&end&fault_type&limit&offset
GET  /api/v1/motors/{id}/history             GET /api/v1/motors/{id}/alerts, POST .../alerts/{id}/ack
POST /api/v1/motors/{id}/supervisory/override   {action: ack|reset|set_load|release_load, load?}
WS   /api/v1/ws/motors/{id}/stream?token=... (or Sec-WebSocket-Protocol: bearer, <token>)
GET  /healthz  /readyz  /metrics
```

## Tests

```bash
cd backend && pytest -q --cov=app              # 290 tests, ~88 % line coverage (SQLite)
TEST_DATABASE_URL=mysql+pymysql://dt:pw@127.0.0.1:3306/dt_test pytest app/tests/api   # same contract tests on MySQL
TEST_REDIS_URL=redis://127.0.0.1:6379/0 pytest app/tests/runtime
cd frontend && npm test                        # Vitest + Testing Library
npx playwright test                            # E2E: inject fault -> diagnosis -> SADA derate (backend on :8000)
python backend/loadtest/ws_load.py --password ... --motors 2 --viewers 100   # load test, see backend/loadtest/RESULTS.md
```

Retrain the classifier with `python -m app.diagnostics.ml.train --runs-per-class 40 --seeds 0 1 2`.
Run it from `backend/`. It writes `artifacts/conv_bilstm.pt` and `metrics.json`.

## Limitations (read before trusting results)

- **Everything is validated on simulated data only.** The Conv-BiLSTM scored 100 % test accuracy
  (3 seeds, 48 held-out runs each). That result only shows the simulator's fault signatures are
  easy to separate. It says nothing about accuracy on real motors. Retrain and re-validate on
  measured data before relying on it.
- The fault models are simplified lumped models, documented in `simulation/faults.py`. Examples:
  - Pure static eccentricity can't be observed in an α-β model, so it is modelled as mixed eccentricity.
  - Inter-turn heating uses an explicit hot-spot factor.
- The residual thresholds (`FD_THRESHOLD` and others) were tuned against this simulator's noise
  floor. They must be re-tuned for real sensors.
- The live twin uses `DEFAULT_MOTOR`: a widely used 1.5 kW parameter set (Rs=1.405, Rr=1.395, Ls=Lr=0.178039,
  Lm=0.1722, J=0.0131) from the field-oriented/DTC control literature. Unverified parameter sets (e.g.
  CHEN_2025_MOTOR with σ ≈ 0.77) have been pruned from the codebase to ensure physical and numerical plausibility.
- The thermal time constant is shortened to 180 s so demos show thermal behaviour. Real TEFC
  motors take tens of minutes.
- One backend process sustains 5+ simulated motors in real time on a single CPU core with the rules backend
  (or 2–3 with neural networks enabled), and about 50–100 viewers at the full 10 Hz. Scale out with replicas.
  See `backend/loadtest/RESULTS.md`.
- The hardware sensor classes are placeholders. MySQL table partitioning is not implemented; the
  retention job deletes old rows instead. The rate limiter is per process.
