# Backend — Motor Digital Twin & Diagnostic Engine

The backend service for the AC Induction Motor Fault Detection Digital Twin. Built with Python
3.11+, FastAPI, SQLAlchemy, Alembic, Redis, and PyTorch (optional CPU inference).

## Architecture & Package Layout

```
backend/app/
├── simulation/        # 5 kHz RK4 motor plant, state equations, fault injection models
├── sensors/           # Abstract transducer interfaces (simulated vs. hardware streams)
├── diagnostics/       # Multi-modal fault detection pipeline
│   ├── electrical.py  # Frozen healthy twin residual check (FD/FL spectral indices)
│   ├── ml/            # Conv(32)→Conv(64)→BiLSTM(64) vibration & acoustic classifier
│   ├── features.py    # 28 time/frequency features per 0.5s window
│   ├── thermal.py     # Winding temperature threshold and rate-of-rise check
│   ├── supply.py      # Voltage Unbalance Factor (VUF), THD, and supply sag
│   ├── mcsa.py        # High-res Welch PSD and peak detector (BRB sidebands, eccentricity)
│   ├── fusion.py      # Weighted voting fusion engine (frozen schema v1.0)
│   └── health_index.py# Motor Health Index (MHI, 0–100 scale) and condition zone
├── static_analysis/   # Offline scalar measurement diagnosis
│   ├── schemas.py     # Pydantic v2 models with rigorous physical range validation
│   ├── steady_state.py# Per-phase equivalent circuit solver (I, P, Q, cos φ from slip)
│   ├── channels.py    # Static adapters (supply, protection, thermal, electrical, rules)
│   └── engine.py      # Static engine, fusion, MHI, and advisory recommendation
├── supervisory/       # Supervisory Anomaly Detection & Action (SADA FSM)
├── runtime/           # Supervised per-motor simulation workers, brokers, and DB writer
├── api/               # FastAPI REST routes and WebSocket streaming
│   └── routes/        # auth, motors, faults, sensors, static, system
├── db/                # SQLAlchemy models (User, Motor, Diagnosis, StaticAnalysis, etc.)
└── core/              # Structured JSON logging, Prometheus metrics, and security
```

## Quick Start (Local Development)

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install hash-pinned dependencies
pip install -r requirements-dev.txt

# 3. Optional: install PyTorch CPU wheels for ML vibration channel
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 4. Start local development server (SQLite default)
DATABASE_URL=sqlite:///./dev.db \
AUTO_CREATE_SCHEMA=true \
ADMIN_USERNAME=admin \
ADMIN_PASSWORD=admin-pass-123 \
JWT_SECRET=dev-secret-key-at-least-32-chars-long-12345 \
uvicorn app.main:create_app --factory --reload --port 8000
```

Interactive OpenAPI documentation is available at `http://localhost:8000/api/v1/docs`.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./dev.db` | SQLAlchemy connection string (SQLite or MySQL) |
| `AUTO_CREATE_SCHEMA` | `false` | Auto-create tables on startup (set `true` for local SQLite) |
| `JWT_SECRET` | Required in prod | Symmetric secret for signing HS256 auth tokens |
| `ADMIN_USERNAME` | `admin` | Default administrator username seeded on first start |
| `ADMIN_PASSWORD` | `admin-pass-123` | Default administrator password |
| `REDIS_URL` | None (in-memory) | Redis connection URL for multi-replica pub/sub & locks |
| `USE_ML` | `true` | If `false`, vibration channel uses rule-based fallback |
| `REALTIME_FACTOR` | `1.0` | Simulation speed multiplier (e.g. `4.0` for faster tests) |
| `LOG_JSON` | `false` | Enable structured JSON logging with correlation IDs |

## Static-Value Diagnosis Engine

The `app.static_analysis` package provides offline diagnostic capabilities for field evaluations
where continuous waveform streams are unavailable.

1. **Equivalent Circuit Physics:**
   Given line-line/line-neutral voltage $V$, supply frequency $f$, and rotor speed $n_r$, the
   solver computes per-phase slip $s = (n_s - n_r)/n_s$, equivalent impedance
   $Z = R_s + j X_s + (j X_m \parallel (R_r/s + j X_r))$, theoretical stator current $I_{expected}$,
   power factor $\cos \phi$, and active power $P$.
2. **Channel Adapters:**
   - **Supply:** Calculates Voltage Unbalance Factor (NEMA / negative sequence) and sag.
   - **Protection:** Evaluates instantaneous overcurrent, overload ($I/I_{rated}$), stall, and phase loss.
   - **Thermal:** Evaluates winding temperature against NEMA/IEC insulation class warn and trip thresholds.
   - **Electrical Residual:** Compares measured current against theoretical equivalent circuit prediction and detects current unbalance.
   - **Mechanical Vibration:** Rule-based evaluation of RMS vibration and 1X/2X/bearing frequencies.
   - **MCSA Spectral Lines:** Assesses sideband harmonics at $f_s(1 \pm 2ks)$ and $f_s \pm f_r$.
3. **Transparency Guard:**
   Channels that lack required measurements report **`not assessable`** with an explicit reason.
   They are never treated as healthy, preventing false-negative diagnoses.
4. **Advisory Guarantee:**
   Because single static snapshots lack continuous history, all outputs are marked as
   `advisory only, no control action taken`. The static engine never drives SADA derates or trips.

## API Endpoints

```
Authentication:
  POST   /api/v1/auth/login                  # Generate access token
  POST   /api/v1/auth/refresh                # Refresh access token
  GET    /api/v1/auth/me                     # Current user profile
  GET    /api/v1/users                       # List users (admin only)
  POST   /api/v1/users                       # Create user (admin only)

Live Digital Twin:
  GET    /api/v1/motors                      # List registered motors
  POST   /api/v1/motors                      # Provision motor (admin only)
  GET    /api/v1/motors/{id}                 # Motor details and state
  PATCH  /api/v1/motors/{id}/params          # Update equivalent circuit parameters
  POST   /api/v1/motors/{id}/simulation/transient-solve # Solve RK45 dynamic trajectory
  GET    /api/v1/motors/{id}/mcsa            # High-resolution MCSA spectrum & peaks
  PATCH  /api/v1/motors/{id}/load            # Adjust load torque (operator)
  POST   /api/v1/motors/{id}/faults          # Inject fault (operator)
  DELETE /api/v1/motors/{id}/faults/{id}     # Clear injected fault
  GET    /api/v1/motors/{id}/diagnoses       # Query diagnosis history
  GET    /api/v1/motors/{id}/alerts          # Motor alerts log
  POST   /api/v1/motors/{id}/alerts/{id}/ack # Acknowledge alert
  POST   /api/v1/motors/{id}/supervisory/override # SADA action (ack, reset, set_load)
  WS     /api/v1/ws/motors/{id}/stream       # Real-time WebSocket telemetry

Static Analysis:
  POST   /api/v1/static/diagnose             # Execute static snapshot diagnosis (operator)
  GET    /api/v1/static/analyses             # Paginated static diagnosis history (viewer)
  GET    /api/v1/static/analyses/{id}        # Retrieve specific static report (viewer)
  GET    /api/v1/static/trend?motor_id=      # Sparse snapshot degradation trend & RUL

System & Observability:
  GET    /healthz                            # Liveness probe
  GET    /readyz                             # Readiness probe
  GET    /metrics                            # Prometheus metrics
  GET    /api/v1/system/db-status            # Database connection health
  POST   /api/v1/system/db-test              # Test/apply MySQL credentials
```

## Testing & Quality Assurance

```bash
# Full test suite with coverage (>85% requirement)
pytest -q --cov=app --cov-report=term-missing

# Contract tests against real MySQL container
TEST_DATABASE_URL=mysql+pymysql://dt:dtpw@127.0.0.1:3306/digital_twin_test pytest app/tests/api

# Real Redis broker pub/sub & ownership lock tests
TEST_REDIS_URL=redis://127.0.0.1:6379/0 pytest app/tests/runtime

# Static analysis physics agreement and validation tests
pytest app/tests/static_analysis/ -v

# Linting and static type checking
ruff check app migrations
mypy app --exclude app/tests
```
