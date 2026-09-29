# Changelog

All notable changes to this project. Versions follow semantic versioning; Docker images are
tagged with the git SHA and with the release tag.

## [Unreleased]

### Added
- Concrete `HardwareSensor` drivers implemented for all 6 sensor channels: `ADS1115CurrentSensor` (16-bit I2C ADC), `MQTTVibrationSensor` (tri-axial accelerometer over MQTT), `VoltageADCSensor`, `EncoderSpeedSensor`, `ThermocoupleTempSensor`, and `I2SAcousticSensor` with circuit-breaker fail-safe handling (Phase 12 / 18).
- Staging and production deployment verification test suite (`test_deployment.py`) covering staging security constraints, Docker Compose stacks (`compose.yaml`, `compose.prod.yaml`), Nginx edge reverse-proxy configuration, `deploy.sh` script execution, database backup/restore procedures (`mysql_backup.sh`, `mysql_restore_test.sh`), and Prometheus/Alertmanager alerting rules (Phase 16 & 17).
- Phase 19: Standard 5-motor industrial fleet preset catalog (`backend/app/simulation/presets.py`: 1.5 kW line 3 pump, 5.5 kW aging belt drive, 11 kW line 7 conveyor, 37 kW compressor train, 75 kW kiln draft fan) with idempotent seeding (`backend/app/scripts/seed_presets.py`) and admin route `POST /api/v1/admin/seed-presets`.
- Phase 20: Motor Health Index (MHI, [0, 100]) and ISO 10816 condition zones (A: Good, B: Acceptable, C: Alert, D: Danger) with deterministic fault error codes `<SOURCE>-<FAULT>-<ZONE>` (`backend/app/diagnostics/health_index.py`). Alembic migration `20260927_0002_health_index_and_error_code` adding `health_index` (Float) and `error_code` (String(24)) to `diagnoses` table and WebSocket streaming frames.
- Phase 21: Degradation prognosis with least-squares polynomial extrapolation (`backend/app/diagnostics/prognosis.py`) predicting time-to-derate and time-to-trip over a rolling 120-sample severity history, accessible via `GET /api/v1/motors/{id}/prognosis`. Prescriptive maintenance recommendations catalog (`backend/app/diagnostics/recommendations.py`) with fault-specific actionable checklists, accessible via `GET /api/v1/motors/{id}/recommendation`.
- Phase 22: Fleet dashboard landing view (`FleetDashboard.tsx`) featuring 4 summary KPI tiles (fleet size, avg MHI, motors tripped/derated, active alerts), fleet preset seed trigger, and responsive motor card grid (`MotorCard.tsx`) with SVG health gauges (`HealthGauge.tsx`). Global persistent `TripBanner.tsx` with operator trip acknowledgment and override actions. Detailed motor Health & Maintenance view (`HealthMaintenanceTab.tsx`) with RUL estimates, prescriptive checklists, and diagnostic event history. Comprehensive Vitest unit tests and Playwright E2E integration specs (`dashboard.spec.ts`).
- Phase 23: Production observability hookup including Prometheus gauge metric `dt_motor_health_index` labeled by `motor_id` and `motor_name`, Prometheus Alertmanager rule `MotorHealthIndexCritical` in `deploy/prometheus/alerts.yml`, and Grafana dashboard panel in `deploy/grafana/dashboards/digital-twin.json`.
- Phase 24: Enterprise UI Ergonomics, Motor Provisioning, and Resilient Local Deployment:
  - Motor provisioning dialog (`AddMotorModal.tsx`) with 7 industrial machine presets and custom dq parameter studio with live physical feasibility verification ($\sigma > 0$, $T_r$).
  - Sign-out confirmation modal (`SignOutConfirmModal.tsx`) requiring explicit operator confirmation before terminating session and disconnecting live streams.
  - Streamlined Fleet Priority Queue (`FleetPriorityQueue.tsx`) by removing redundant heap operation buttons and displaying a clean Heap Telemetry header.
  - Official high-contrast TWIN-CORE browser tab favicon (`favicon.svg`) replacing the default Vite logo across light and dark browser themes.
  - Safe fallback defaults for `compose.yaml` and deployment verification tests (`test_deployment.py`) enabling `docker compose config` validation without a mandatory pre-existing `.env` file.
- Phase 25: Operator Profile & Live Database Configuration Deck:
  - Interactive navbar operator profile chip opening a dedicated system connectivity dialog (`ProfileDatabaseModal.tsx`).
  - Real-time database connection status indicator ("DATABASE CONNECTED / DISCONNECTED") showing dialect, active database, host/port, latency, and all persistence schema tables.
  - Dedicated MySQL credential management with password visibility toggle, non-destructive link testing (`POST /api/v1/system/db-test`), and runtime connection hot-reload.
  - Harmonized modal dialog card styling to match the application page background color (`var(--page)` / `#050505`) across Add Motor, Sign Out, and Database Profile dialogs.
- Phase 26: Core Physics Engine Reconstruction:
  - Non-linear 5-state electromechanical ODE solver using `scipy.integrate.solve_ivp(method="RK45")` in stationary ($\alpha$-$\beta$) and synchronous ($d$-$q$) frames, integrating $[i_{ds}, i_{qs}, \psi_{dr}, \psi_{qr}, \omega_m]^T$ (`state_space_solver.py`).
  - Mathematical fault injection: Stator Inter-turn Short Circuit (ITSC: $\mu = N_{sc}/N_s$ with circulating current matrix $\mathbf{v}_s = \mathbf{R}_s \mathbf{i}_s + d\boldsymbol{\psi}_s/dt$), Broken Rotor Bars (BRB: $R_r(\theta_r)$ rotor asymmetry matrix producing $(1 \pm 2ks)f_s$ sidebands), and Dynamic Eccentricity ($L_m(\theta_m) = L_{m0}(1 + \delta_{ecc}\cos\theta_m)$ angular permeance model).
- Phase 27: MCSA Analytical Pipeline & 4-Node Lumped Parameter Thermal Network:
  - High-resolution stator current acquisition ($F_s \ge 5000\text{ Hz}$), flat-top / Hann windowing, Welch PSD, and automated peak detection with `scipy.signal.find_peaks` targeting $f_{BRB} = f_s(1 \pm 2ks)$ ($k \in \{1,2,3\}$) and dynamic eccentricity sidebands $f_s \pm f_r$ (`mcsa.py`).
  - 4-Node Lumped Parameter Thermal Network (`thermal_lptn.py`): tracks Stator Winding ($T_w$), Teeth Core ($T_t$), Rotor Cage ($T_r$), and Bearings ($T_b$).
  - Classical Arrhenius insulation thermal life model $\text{Life} = A \cdot \exp(E_a / (k_B T_w))$ calculating instantaneous thermal acceleration factor and Remaining Useful Life (RUL hours).
- Phase 28: UI/UX Refactoring & Telemetry Ingestion Modes:
  - Decoupled solver execution from UI rendering thread via asynchronous simulation endpoints `POST /api/v1/motors/{id}/simulation/transient-solve` and `GET /api/v1/motors/{id}/mcsa`.
  - Prominent Telemetry Ingestion Mode badge (`Mode: Real Hardware Stream` vs. `Mode: Dynamic State-Space Emulation`) in the motor overview header and live deck.
  - 4-Node LPTN thermal matrix visualization with temperature bars and Arrhenius RUL meter in `HealthMaintenanceTab.tsx`.
  - Automated MCSA peak markers overlay targeting $f_s(1 \pm 2ks)$ and dynamic eccentricity sidebands in `SensorPanels.tsx`.
- Phase 29: Physics Engine Verification & Automated Testing:
  - Comprehensive physics test suite (`test_physics_engine.py`) verifying steady-state speed convergence under no-load ($1499.2\text{ RPM}$) and rated load ($1474.0\text{ RPM}$), BRB sideband harmonic power increase $\ge 15\text{ dB}$ ($+76.5\text{ dB}$ delta), ITSC localized heat, dynamic eccentricity permeance, 4-node LPTN thermodynamic stability, and Arrhenius degradation kinetics.
- Phase 30: CI Stability, Algorithmic Foundations (DSA) in Documentation, and Default Fault Ingestion:
  - CI Pipeline Hardening: Resolved all Ruff linter and Mypy static typing issues across backend codebase (79 files, 0 errors) and fixed TypeScript spectra typing definitions in frontend (`types.ts`). Both backend (`pytest -q --cov=app --cov-fail-under=85` at 87.07% coverage) and frontend (`npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build`, `npx playwright test`) now pass with 100% success.
  - Startup Default Fault Injection: Motors automatically start in faulted states by default upon simulation boot (`main.py` bootstrap & `presets.py`), enabling immediate out-of-the-box demonstration of multi-modal anomaly detection, MCSA sidebands, vibration envelope spikes, and SADA supervisory derates.
  - Chapter 7 DSA Foundations in Engineering Documentation Book (`EngineeringDocsModal.tsx`): Detailed mathematical and implementation analysis of Binary Max/Min Heap Priority Queues (`PriorityQueue.ts` / `FleetPriorityQueue.tsx`) for O(log N) fleet asset triage, Circular Sliding Ring Buffers (`deque(maxlen=K)`) for O(1) zero-allocation telemetry windowing, Finite State Machine (FSM) with asymmetric hysteresis debouncing and α=0.25 EMA filter (`sada.py`), and O(1) hash map registries.
  - Main Dashboard Global Footer: Formatted exact footer string `https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin · 2026 · Naavalanarul · MIT License` across application layout.
  - Updated live faulted operational dashboard screenshot in `docs/dashboard.png` with updated README references.
  - Playwright E2E smoke tests verifying zero syntax or runtime console tracebacks when toggling UI views, inspecting the mode badge, and monitoring thermal dynamics.
- Phase 30: Engineering & Physics Documentation Modal:
  - Rich 5-tab interactive documentation modal (`EngineeringDocsModal.tsx`) accessible from both the navbar Docs button and the Operator Profile dialog, covering:
    - Tab 1: Continuous electromechanical state-space model (RK45 Dormand-Prince, Clarke/Park coordinate systems, governing stator/rotor ODEs, Newton torque balance).
    - Tab 2: Mathematical fault injection (ITSC shorted-turn ratio μ with circulating current matrix, BRB rotor resistance asymmetry R_r(θ_r) producing (1 ± 2ks)f_s sidebands, dynamic eccentricity air-gap permeance L_m(θ_m), bearing defect kinematics BPFO/BPFI/BSF/FTF).
    - Tab 3: MCSA Welch PSD pipeline (windowed spectral analysis, automated peak detection) and 4-Node LPTN thermal network (T_w, T_t, T_r, T_b) with classical Arrhenius insulation degradation and RUL estimation.
    - Tab 4: High-level software pipeline architecture (RK45 plant → sensor abstraction → multimodal diagnostics → decision fusion → SADA FSM → WebSocket → React), dual telemetry ingestion modes.
    - Tab 5: Canonical research papers and IEEE/ISO standards with direct DOI links (Thomson & Fenger 2001, Nandi et al. 2005, Chen et al. 2014, Tallam et al. 2007, McFadden & Smith 1984, IEEE Std 841, ISO 10816-3).
  - Navbar "Docs" button with accent-colored pill styling next to operator profile chip.
  - Physics Engine & Architecture Documentation card integrated into `ProfileDatabaseModal.tsx` body and footer with one-click modal transition.
  - Playwright E2E test (`docs-modal.spec.ts`) verifying all 5 documentation tabs, navbar access, and profile-to-docs navigation flow.
- Phase 31: Core Physics & Diagnostics Backend Consolidation & Comprehensive Subsystem RUL:
  - Re-organized file directories by migrating root-level packages into `backend/`:
    - `backend/app/core_physics/`: `dynamic_solver.py`, `fault_models.py`, `motor_parameters.py`, `thermal_lptn.py`.
    - `backend/app/signal_processing/`: `mcsa_pipeline.py`, `vibration_analysis.py`, `feature_extraction.py`.
    - `backend/app/diagnostics/`: `fault_classifier.py` and `rul_engine.py`.
    - `backend/app/tests/simulation/`: `test_physics_solver.py` and `test_fault_injection.py`.
    - `backend/loadtest/`: `ws_load.py` and `RESULTS.md`.
  - Connected `RULEngine` into `worker.py` streaming frames and added REST endpoint `GET /api/v1/motors/{id}/rul` (`RULResultOut`).
  - Connected multi-subsystem RUL to React frontend in `HealthMaintenanceTab.tsx` displaying Arrhenius insulation life, ISO 281 bearing fatigue life, overall motor service life, and limiting factor.
  - Verified 184 backend pytest tests, 22 vitest unit tests, and 5 Playwright E2E tests.
- Phase 32: Interactive 7-Chapter Engineering & Physics Documentation Book (`EngineeringDocsModal.tsx`):
  - Revamped documentation modal into an interactive digital "book" reading experience with book spine accent styling, chapter progress indicator ("Chapter X of 7" / "Page X of 7"), interactive `Previous Chapter` and `Next Chapter` buttons, and keyboard navigation (`ArrowLeft` / `ArrowRight` / `PageUp` / `PageDown`).
  - Added dedicated Book Footer featuring the direct GitHub repository link (`https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin`) and year of creation (`Created: 2026 · Author: Naavalanarul`).
  - Structured content into 7 exhaustive, physics-grounded chapters:
    - Chapter 1 (`1. State-Space Physics`): System capabilities, complete scientific software stack (`scipy.integrate.solve_ivp` RK45, `scipy.signal`, `PyWavelets`, `PyTorch` Conv-BiLSTM, `FastAPI`, `Redis`, `React`), 5-state continuous electromechanical state-space differential equations in Clarke ($\alpha$-$\beta$) and Park ($d$-$q$) reference frames, torque generation, shaft dynamics, and physical parameter definitions.
    - Chapter 2 (`2. Mathematical Faults`): Mathematical fault injection models: Stator Inter-turn Short Circuit (ITSC: circulating current loop, shorted turn ratio $\mu = N_{sc}/N_s$, localized Joulean heating), Broken Rotor Bars (BRB: anisotropic rotor resistance tensor $R_r(\theta_r)$, $(1 \pm 2ks)f_s$ sidebands, $2s f_s$ torque oscillations), Dynamic Air-Gap Eccentricity (permeance modulation $L_m(\theta_m)$, $f_s \pm f_r$ current sidebands), and Rolling Element Bearing Defect Kinematics (BPFO, BPFI, BSF, FTF equations).
    - Chapter 3 (`3. Sensor Simulation`): Detailed explanation of how sensor values are synthesized from first-principles physics: Inverse Clarke transformation for 3-phase currents ($I_A, I_B, I_C$) with 16-bit ADC Gaussian noise $\mathcal{N}(0, \sigma^2)$, balanced grid voltages vs PWM inverter switching patterns with harmonics, optical speed encoder simulation with quantization noise and torsional flutter, tri-axial accelerometer vibration physics (1x unbalance, 2x misalignment, and bearing defect Dirac-comb impact convolution with exponentially damped structural resonances $A e^{-\zeta \omega_n t}\sin(\omega_d t)$), acoustic sound pressure waves coupling housing vibration, magnetostriction 100 Hz hum, and cooling fan aerodynamic turbulence, and temperature sensing with thermal inertia lag.
    - Chapter 4 (`4. Fault Detection`): Comprehensive multi-modal diagnostic engine explanation: Digital Twin Current Residual Method (analytical redundancy isolating internal faults from supply voltage swings), MCSA Welch PSD sideband tracking, Continuous Wavelet Transform (CWT) Morlet scalograms for non-stationary impact transients, 1D Conv-BiLSTM deep neural classifier with automatic rule-based envelope order analysis fallback, weighted decision fusion calculating Motor Health Index (MHI), and SADA supervisory FSM (NORMAL $\to$ WATCH $\to$ DERATE $\to$ TRIP).
    - Chapter 5 (`5. MCSA & Thermal`): High-frequency spectral analysis pipeline (Welch PSD, Flat-top and Hann windowing), 4-Node Lumped Parameter Thermal Network (LPTN) differential heat balance across Stator Winding ($T_w$), Teeth Core ($T_t$), Rotor Cage ($T_r$), and Bearings ($T_b$), Classical Arrhenius thermal insulation degradation model ($10^\circ\text{C}$ half-life rule), and ISO 281 bearing fatigue life ($L_{10h}$).
    - Chapter 6 (`6. System Architecture`): High-level software pipeline architecture ASCII diagram, dual telemetry ingestion modes (Dynamic State-Space Emulation vs Real Hardware Stream), and real-time event-driven streaming runtime.
    - Chapter 7 (`7. Research Papers & Standards`): Canonical research papers with verified clickable external links (Thomson & Fenger 2001, Nandi et al. 2005, Chen et al. 2014, Tallam et al. 2007) and industry standards (IEEE Std 841, ISO 10816-3).
  - Playwright E2E integration test suite (`docs-modal.spec.ts`) updated and verified across all 7 chapters, pagination controls, keyboard turning, GitHub link, and 2026 creation year.

### Fixed
- Fixed parameter cards scrolling bug in `AddMotorModal` by enforcing `flex-shrink: 0` on form cards and `min-height: 0` on the scrollable container, preventing flexbox from squeezing inputs down to 91px.
- Pinned modal header and footer outside the scrollable body so Cancel and Provision actions are always visible and accessible.
- Fixed modal stacking context by mounting modals via React Portals (`createPortal(..., document.body)`) at `z-index: 9999` and applying deep background blurring and dimming to the floating navigation bar.
- Added automatic Service Worker and Cache Storage eviction scripts (`index.html`, `sw.js`, `service-worker.js`) to evict stale caches from prior localhost projects (e.g. Expensify).
- Prevent persisted diagnoses from contradicting SADA supervisory state by overriding false "healthy" diagnoses during latched motor trips when sensors are starved (Phase 19).
- Added `INDETERMINATE` verdict to `DiagFault` schema (`backend/app/diagnostics/schema.py`) as a non-breaking additive enum member.
- Threaded SADA-latched fault type and severity into `Diagnosis` telemetry when motor is tripped and diagnostic channels are unavailable.
- Updated React dashboard (`HistoryView.tsx`) to distinctly format and style `INDETERMINATE` diagnoses ("monitoring paused — motor stopped") and support filtering.

## [1.0.0] - 2026-09-25

### Added
- Averaged-inverter RK4 motor plant validated against the event-driven PWM twin; healthy-twin observer.
- Fault injectors (rotor bar, inter-turn short, eccentricity, bearing IR/OR/ball, unbalance,
  misalignment, voltage sag/imbalance/harmonics) with spectral-signature tests.
- Sensor abstraction layer with six simulated sensors, hardware placeholders and circuit breaker.
- Diagnostics: DT current residual (FD/FL), feature pipeline + Conv-BiLSTM (leak-safe training,
  rule-based fallback), thermal, supply; weighted fusion with frozen output schema v1.0.
- SADA supervisory layer (confidence gating, EMA smoothing, graded derate, latched/emergency/thermal trip).
- FastAPI `/api/v1` REST + WebSocket streaming, JWT auth with RBAC, idempotency keys, rate limits.
- MySQL schema with Alembic migration; batched telemetry writer; retention job.
- Supervised per-motor workers, Redis broker with per-motor ownership for multi-replica runs.
- Structured JSON logging, Prometheus metrics, health/readiness endpoints, alert rules, Grafana dashboard.
- React dashboard: live per-sensor panels, fused diagnosis, SADA controls, fault console, history.
- Docker images, Compose stacks (local + production overlay with TLS edge), backup/restore scripts,
  CI/CD workflow, load-test script and baseline.

### Fixed (relative to the initial scaffold)
- Broken imports in the simulation package (`simulation.inverter`, `lambda_` constant).
- Pre-existing RK4 convergence test band too tight for the coarsest step.
