# Code Paths Classification: Live, Reference, and Legacy

This document classifies every top-level package and module within `backend/app` into **Live Path**, **Reference**, or **Legacy**, establishing architectural clarity and ensuring paper experiments rely strictly on verified operational code paths.

---

## 1. Top-Level Package Classifications

| Directory | Classification | Role & Description |
|---|---|---|
| `app/api/` | **Live Path** | FastAPI HTTP and WebSocket routers, request/response Pydantic schemas, dependency injection, and authentication. |
| `app/core/` | **Live Path** | Application configuration, security utilities (JWT, password hashing), structured logging, Prometheus metrics, and rate limiting. |
| `app/core_physics/` | **Reference** | Standalone high-fidelity physics models (state-space motor solver, 4-node LPTN thermal model, geometric bearing fault models). Certain data structures (e.g., `BearingDefect`, `FaultState`, `EccentricityType`) are imported by `diagnostics/rul_engine.py` and `diagnostics/calibration.py`. |
| `app/db/` | **Live Path** | SQLAlchemy ORM models, declarative base, database session lifecycle management (SQLite and MySQL). |
| `app/diagnostics/` | **Live Path** (with Legacy subset) | Core online diagnostics orchestration (`engine.py`), domain diagnostics (`electrical.py`, `mcsa.py`, `features.py`, `fusion.py`, `health_index.py`, `prognosis.py`, `protection.py`, `rul_engine.py`, `supply.py`, `thermal.py`), and neural network classifier (`ml/`). Note: `fault_classifier.py` is **Legacy**. |
| `app/runtime/` | **Live Path** | Real-time execution loop (`worker.py`), multi-motor manager (`manager.py`), streaming telemetry broker (`broker.py`), asynchronous database writer (`writer.py`), and historical retention (`retention.py`). |
| `app/scripts/` | **Live Path / Utility** | Database seeding and demonstration presets initialization (`seed_presets.py`). |
| `app/sensors/` | **Live Path** | Sensor registry, abstract base sensor contracts, simulated noisy sensors, and hardware I/O driver stubs. |
| `app/signal_processing/` | **Legacy / Reference** | Standalone signal processing pipelines (`mcsa_pipeline.py`, `vibration_analysis.py`, `feature_extraction.py`). Tested in isolation but superseded in the live runtime path by `diagnostics/mcsa.py` and `diagnostics/features.py`. |
| `app/simulation/` | **Live Path** | The primary digital twin simulator running in the worker: numerical integrators (RK4), plant model (`plant.py`), healthy observer twin (`motor_twin.py`, `twin_state.py`), dynamic state-space solver, fault injection engine (`faults.py`), thermal model, inverter PWM, and fleet presets. |
| `app/static_analysis/` | **Live Path** | Offline/static parameter characterisation engine for motor nameplate and steady-state electrical/mechanical analysis. |
| `app/supervisory/` | **Live Path** | State-Aware Derating & Alert supervisor (`sada.py`), providing hysteresis, dwell timers, EMA smoothing, and confidence-gated supervisory derate/trip control. |
| `app/tests/` | **Test Suite** | Comprehensive unit, integration, and end-to-end regression tests across all subsystems. |
| `app/validation/` | **Reference / Experimentation** | Offline research validation framework: data loaders (`liman_c`, `estogu`, etc.), split generation (`splits.py`), evaluation protocols (`protocols.py`), reporting, and domain-adaptation metrics. |

---

## 2. Duplicate-Code Analysis & Verification

### Verification Grep Results
Grep across `backend/app` for `signal_processing`, `fault_classifier`, and `core_physics` revealed:
- `app/signal_processing/`:
  - Imported **only** by `app/tests/simulation/test_physics_solver.py`, `app/tests/simulation/test_fault_injection.py`, `app/tests/diagnostics/test_p1_3_eccentricity_brb_calibration.py`, and `app/diagnostics/fault_classifier.py`.
  - **Never imported** by `app/runtime/`, `app/api/`, or `app/diagnostics/engine.py`.
- `app/diagnostics/fault_classifier.py`:
  - Imported **only** by test files (`test_physics_solver.py`, `test_p1_3_eccentricity_brb_calibration.py`).
  - Contains an earlier standalone rule-based heuristic classifier.
- `app/core_physics/`:
  - Imported by `app/diagnostics/rul_engine.py` (`BearingDefect`, `FaultState`, `FourNodeThermalLPTN`) and `app/diagnostics/calibration.py` (`EccentricityType`).
  - Also imported by tests and the legacy `signal_processing/` modules.
- `app/diagnostics/mcsa.py`:
  - The **true live path** MCSA pipeline. Imported by `app/diagnostics/engine.py` and invoked on every live processing chunk inside `app/runtime/worker.py`.

### Architectural Determination
1. **Live Diagnostic Path:**
   - Real-time chunks are ingested by `app/runtime/worker.py`.
   - Dispatched to `app/diagnostics/engine.py:DiagnosticEngine.process_chunk()`.
   - Frequency-domain spectral peaks are computed using `app/diagnostics/mcsa.py:MCSADiagnostic`.
   - Feature vectors are extracted via `app/diagnostics/features.py:SignalFeatureExtractor`.
   - Vibration/acoustic signals are classified by `app/diagnostics/ml/classifier.py:VibrationClassifier` (Conv-BiLSTM with rule-based fallback).
   - Electrical residuals are evaluated by `app/diagnostics/electrical.py:ElectricalResidualDiagnostic` comparing against `app/simulation/plant.py:HealthyTwinObserver`.
   - Protection faults are handled by `app/diagnostics/protection.py:ProtectionDiagnostic`.
   - Fused through `app/diagnostics/fusion.py:DiagnosticFusion`.
   - Fed into `app/supervisory/sada.py:SadaSupervisor`.
   - Overall health score evaluated by `app/diagnostics/health_index.py:MotorHealthIndex`.

2. **Reference Path:**
   - `app/core_physics/`: Validated physics solver and structural definitions preserved for theoretical comparison, parameter derivation, and RUL calculation.
   - `app/validation/`: Research experimentation suite used to generate paper evidence.

3. **Legacy Path:**
   - `app/signal_processing/` (`mcsa_pipeline.py`, `vibration_analysis.py`, `feature_extraction.py`).
   - `app/diagnostics/fault_classifier.py`.
   - *Policy:* These files are preserved to maintain full backward compatibility with historical tests, but paper experiments and live extensions must never import or depend on them.

---

## 3. Ground Rules for Paper Experiments

All paper experiments (P1 through P8) must strictly adhere to the following import discipline:
- Use **Live Path** components for plant simulation, twin observers, diagnostics, fusion, SADA supervisory control, and MHI computation.
- Use **Reference** components (`app/validation/`) for dataset ingestion, grouped cross-validation, and metrics collection.
- Under no circumstances shall paper experiments import from `app/signal_processing/` or `app/diagnostics/fault_classifier.py`.
