# Audit-Driven Fixes & Verification Report

This document records the comprehensive architectural, numerical, algorithmic, and user-interface remediations applied to the **AC Induction Motor Digital Twin** repository (`Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin`).

Every issue identified during the black-box audit has been addressed, verified against unit/integration regression tests, and committed under its specific issue ID.

---

## Executive Summary & Verification Metrics

- **Schema Stability:** Diagnostic output schema remains frozen at `SCHEMA_VERSION = "1.0"` (`app/diagnostics/schema.py`).
- **Backend Quality Gates:**
  - Python 3.11+, line length <= 120, `ruff check` clean (0 warnings, 0 errors).
  - `mypy app` clean (0 type errors across 137 source files).
  - Pytest: **290 passed, 2 skipped** (skips are optional MySQL integration tests without live DB container).
  - Line Coverage: **~88% total coverage** across 6,528 statements.
  - Zero `RuntimeWarning` or numerical overflows (`-W error::RuntimeWarning` enforced in pytest configuration).
- **Frontend Quality Gates:**
  - `npm run lint` clean (ESLint 0 errors).
  - `npm run typecheck` clean (TypeScript `tsc -b` 0 errors).
  - `npx vitest run`: **24 passed** (100% passing tests).
  - `npm run build`: Production build succeeded with zero chunk size warnings (code-split via dynamic `import()` and manual chunking; all chunks <= 382 kB).

---

## Tier P0: Safety and Correctness

### P0-1. Non-Finite Parameter Rejection & Simulation Divergence Protection
- **Commit:** `5b02b10 fix(P0-1): reject unstable motor params and guard against non-finite simulation divergence`
- **What Changed:**
  - Added centralized validator `validate_motor_params()` in `app/simulation/params.py` checking:
    - Electrical state-space eigenvalues: $\max |\lambda| \cdot \Delta t \le 2.78$ (RK4 stability limit) across zero speed and synchronous frequency.
    - Plausibility boundaries: total leakage factor $\sigma \in [0.02, 0.25]$, magnetizing current ratio $I_m / I_{\text{rated}} \in [0.15, 0.95]$, nameplate torque consistency with $P_{\text{rated}} / \omega_{\text{rated}}$ within 15%, slip $> 0$.
  - Wired parameter validation into `MotorParamsIn` and motor creation/update endpoints (`POST /api/v1/motors`, `PATCH /api/v1/motors/{id}/params`), returning `422 Unprocessable Entity` for physically invalid or numerically unstable parameter sets.
  - Added non-finite guard in `PlantSimulator.simulate`: if any state variable ($\omega_m$, currents, fluxes) contains `NaN` or `Inf`, the motor immediately halts, trips with reason `TRIP_SIM_NONFINITE`, and flags `has_nonfinite = True`.
  - Enforced `json.dumps(..., allow_nan=False)` in WebSocket worker serialization to ensure malformed literal `NaN` is never written to the wire or stored in database rows. Non-finite values are sanitized at boundaries.
  - Diagnostic fusion and SADA treat non-finite frame inputs as a critical fault rather than failing open.
- **Covering Tests:**
  - `backend/app/tests/simulation/test_p0_1_stability.py::test_validate_motor_params_rejects_unstable`
  - `backend/app/tests/simulation/test_p0_1_stability.py::test_p0_1_monkeypatched_nan_triggers_trip_and_no_nan_wire`
  - `backend/app/tests/simulation/test_p0_1_stability.py::test_p0_1_random_valid_params_never_yield_nonfinite`

---

### P0-2. Physical Preset Scalings & Per-Motor Thermal Model
- **Commit:** `a182047 fix(P0-2): rebuild presets 2 to 5 with physical per-unit scaling and scale thermal model per motor`
- **What Changed:**
  - Rebuilt fleet presets (5.5 kW Belt, 11 kW Conveyor, 37 kW Compressor, 75 kW Fan) in `app/simulation/presets.py` using standard IEEE per-unit equivalent circuit scaling:
    - Plausible magnetizing currents ($I_m \approx 30\text{--}40\%$ of rated current).
    - Realistic leakage factors ($\sigma \approx 0.06\text{--}0.12$).
    - Full derivation documented in `presets.py` docstring.
  - Parameterized `ThermalModel` in `app/simulation/mechanical_signals.py` and `MotorSimulator`:
    - Replaced hardcoded thermal resistance $R_{\text{th}} = 0.35\text{ K/W}$ with motor-specific $R_{\text{th}} = \Delta T_{\text{rated}} / P_{\text{cu,rated}}$ and scaled heat capacity $C_{\text{th}} = \tau_s / R_{\text{th}}$.
    - Added `warn_c` and `trip_c` derived from motor insulation class (B/F/H) to `MotorParams`.
    - Eliminated spurious overheating trips during healthy steady-state runs across all presets.
- **Covering Tests:**
  - `backend/app/tests/simulation/test_p0_2_presets_thermal.py::test_all_presets_pass_validation`
  - `backend/app/tests/simulation/test_p0_2_presets_thermal.py::test_all_presets_healthy_steady_state_no_overheating`
  - `backend/app/tests/simulation/test_p0_2_presets_thermal.py::test_seeded_presets_diagnose_intended_faults`

---

### P0-3. Stale Sensor Watchdog, MHI Penalty & Driver Confirmation
- **Commit:** `6602718 fix(P0-3): add stale sensor penalty, watchdog timer and hardware switch confirmation`
- **What Changed:**
  - Added `"stale"` sensor handling in `MotorHealthIndex` (`app/diagnostics/health_index.py`), applying criticality-weighted penalties (Current: 35, Voltage: 25, Speed: 20, Vibration: 15, Acoustic: 10, Temp: 10) so lost/stale channels strictly reduce health index rather than increasing it.
  - Implemented sensor watchdog in `MotorWorker` (`app/runtime/worker.py`): tracks channel staleness against `sensor_loss_grace_s` (default 5.0 s). If critical channels remain stale past grace period, triggers `SENSOR_LOSS` alert and trips with `TRIP_SENSOR_LOSS`.
  - SADA decays severity smoothly when fused diagnosis is `UNKNOWN` rather than freezing derate load command indefinitely.
  - Added `confirm_driver_placeholder` check in `PATCH /api/v1/motors/{id}/sensors/{sensor_id}`, preventing accidental switching of sensors to placeholder hardware drivers without explicit operator acknowledgement and audit logging.
- **Covering Tests:**
  - `backend/app/tests/simulation/test_p0_3_sensor_loss.py::test_stale_sensor_penalizes_health_index`
  - `backend/app/tests/simulation/test_p0_3_sensor_loss.py::test_sensor_loss_watchdog_trips_motor`
  - `backend/app/tests/api/test_p0_3_hardware_confirmation.py::test_patch_hardware_sensor_requires_confirmation`

---

### P0-4. Current-Based Protection Channel (Overload, Overcurrent, Stall, Phase-Loss)
- **Commit:** `0c6cde7 fix(P0-4): add current-based protection channel for overload, overcurrent, stall, and phase loss`
- **What Changed:**
  - Created industrial electrical protection channel `ProtectionDiagnostic` in `app/diagnostics/protection.py`:
    - **$I^2 t$ Inverse-Time Thermal Overload:** Accumulates overload energy when $I_{\text{pu}} > 1.05$; triggers warning/derate at 40% accumulator and trip at 100%.
    - **Instantaneous Overcurrent:** Trips instantaneously if current exceeds 5.0x rated running current (15x during startup inrush).
    - **Locked-Rotor / Stall Protection:** Detects high current draw ($I \ge 2.0 I_{\text{rated}}$) with rotor speed collapse ($\text{RPM} \le 0.25 \text{RPM}_{\text{rated}}$) sustained for $> 0.5\text{ s}$.
    - **Single-Phasing / Phase-Loss:** Detects phase current unbalance $> 1.10$ or missing phase current $< 0.10 I_{\text{mean}}$ sustained for $> 0.3\text{ s}$.
  - Added `DiagFault.OVERLOAD`, `OVERCURRENT`, `STALL`, and `PHASE_LOSS` to `DiagFault` enum in `app/diagnostics/schema.py`.
  - Wired `ProtectionDiagnostic` as a first-class channel (`DiagSource.PROTECTION`) in `DiagnosticEngine` and SADA.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p0_4_protection.py::test_inverse_time_thermal_overload`
  - `backend/app/tests/diagnostics/test_p0_4_protection.py::test_instantaneous_overcurrent`
  - `backend/app/tests/diagnostics/test_p0_4_protection.py::test_locked_rotor_stall_detection`
  - `backend/app/tests/diagnostics/test_p0_4_protection.py::test_single_phasing_phase_loss_detection`

---

### P0-5. Severity-Aware Fusion Ranking & Multi-Fault Handling
- **Commit:** `eddba5c fix(P0-5): rank fusion by severity and consume worst credible fault in SADA`
- **What Changed:**
  - Modified multi-sensor fusion engine in `app/diagnostics/fusion.py`:
    - Ranks candidate faults by composite score: $\text{score} = \text{severity} \cdot \text{confidence}^{\gamma}$ (with priority weighting for safety-critical electrical and protection faults).
    - Preserves secondary credible diagnoses in `FusedDiagnosis.secondary` list with source and score attribution.
  - SADA supervisory controller evaluates the maximum credible severity across primary and secondary candidates:
    $$\text{effective\_severity} = \max\left(\text{primary.severity}, \max_{s \in \text{secondary}} s.\text{severity}\right)$$
    guaranteeing that a high-severity fault (e.g. inter-turn short) is never masked by a lower-severity high-confidence fault (e.g. unbalance).
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p0_5_fusion_ranking.py::test_fusion_prioritizes_severe_fault_over_low_severity_high_confidence`
  - `backend/app/tests/diagnostics/test_p0_5_fusion_ranking.py::test_sada_acts_on_worst_credible_fault_severity`

---

### P0-6. SADA Trip Evidence Latching, Thermal Cooldown & Anti-Reclosure Guard
- **Commit:** `43887e2 fix(P0-6): latch trip evidence, enforce cooldown and restart limiting on reset`
- **What Changed:**
  - Implemented immutable trip evidence latching in `SupervisoryState`: records `trip_evidence` snapshot (fault type, severity, temperature, current, timestamp, reason code) when entering `TRIP`.
  - Enforced reset interlocks in `SupervisoryController.reset()` (`app/supervisory/sada.py`):
    - Rejects reset if active fault severity remains high ($\ge 0.40$).
    - Rejects reset if stator temperature has not cooled below reset threshold ($T_{\text{reset}} = T_{\text{warn}} - 10\text{ K}$).
    - Enforces minimum anti-pumping cooldown time (default 10.0 s) between trip and reset attempt.
    - Limits consecutive restarts within a rolling 1-hour window (default max 3 restarts/hour).
- **Covering Tests:**
  - `backend/app/tests/supervisory/test_p0_6_trip_latch_and_reset_guards.py::test_trip_evidence_is_latched`
  - `backend/app/tests/supervisory/test_p0_6_trip_latch_and_reset_guards.py::test_reset_refused_while_hot`
  - `backend/app/tests/supervisory/test_p0_6_trip_latch_and_reset_guards.py::test_reset_refused_while_fault_active`
  - `backend/app/tests/supervisory/test_p0_6_trip_latch_and_reset_guards.py::test_restart_rate_limiting`

---

## Tier P1: Diagnostic & Control Logic

### P1-1. Anti-Hunting Limit Cycle Prevention in SADA Derate
- **Commit:** `d7bf3ed fix(P1-1): prevent hunting limit cycle with load normalization, dwell time and rate limiting`
- **What Changed:**
  - Normalized electrical residual $FD$ by shaft load factor: $FD_{\text{norm}} = FD / \sqrt{\max(0.35, \text{slip} / \text{slip}_{\text{rated}})}$, stabilizing fault signature detection during load shedding.
  - Added hysteresis, minimum dwell time (3.0 s), and slew-rate limiter ($\le 10\% / \text{s}$) to SADA derate commands to eliminate hunting oscillations.
- **Covering Tests:**
  - `backend/app/tests/supervisory/test_p1_1_anti_hunting_derate.py::test_derate_load_remains_stable_without_hunting`
  - `backend/app/tests/supervisory/test_p1_1_anti_hunting_derate.py::test_derate_slew_rate_is_bounded`

---

### P1-2. Prognosis & RUL Calibrated Trend Extrapolation
- **Commit:** `7bb1a09 fix(P1-2): calibrate prognosis trend extrapolation with minimum window, R2 significance, and 95% CI`
- **What Changed:**
  - Replaced uncalibrated instantaneous linear extrapolation in `RULEngine` (`app/diagnostics/rul_engine.py`) with statistically sound trend analysis:
    - Enforces minimum observation window ($n \ge 30$ samples across at least 15 seconds).
    - Tests linear regression slope significance ($p < 0.05$ and $R^2 \ge 0.60$).
    - Computes 95% prediction confidence intervals and bounded remaining useful life estimates ($RUL_{\min}, RUL_{\text{typ}}, RUL_{\max}$).
    - Flags status as `INSUFFICIENT_DATA` or `STABLE_NO_DEGRADATION` when degradation is absent.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_2_prognosis_calibration.py::test_prognosis_stable_condition_reports_no_degradation`
  - `backend/app/tests/diagnostics/test_p1_2_prognosis_calibration.py::test_prognosis_ramping_fault_reports_calibrated_rul_with_ci`

---

### P1-3. Eccentricity & Broken Rotor Bar Monotonic Calibration
- **Commit:** `65ded3a fix(P1-3): calibrate eccentricity and BRB feature mapping with monotonic scaling and single source of truth`
- **What Changed:**
  - Consolidated fault-to-severity mappings in `app/diagnostics/calibration.py` as the single source of truth:
    - `brb_db_to_severity()` / `brb_count_to_severity()`: strictly monotonic mapping across $[-45\text{ dBc}, -20\text{ dBc}]$ and $[1, 8]$ broken bars.
    - `eccentricity_db_to_severity()` / `eccentricity_depth_to_severity()`: monotonic mapping across $[-45\text{ dBc}, -20\text{ dBc}]$ and $[0\%, 15\%]$ air-gap clearance.
    - `residual_fd_to_severity()`: mapped across $[0.015, 0.150]$ FD index.
  - Linked MCSA pipeline, electrical residual observer, and fault classifier to the unified calibration functions.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_3_calibration_monotonicity.py::test_brb_monotonicity_and_roundtrip`
  - `backend/app/tests/diagnostics/test_p1_3_calibration_monotonicity.py::test_eccentricity_monotonicity_and_roundtrip`
  - `backend/app/tests/diagnostics/test_p1_3_calibration_monotonicity.py::test_residual_fd_monotonicity`

---

### P1-4. Temperature Compensation & Grid Frequency Estimation
- **Commit:** `6cd1eca fix(P1-4): temperature-compensate twin observer and estimate grid frequency from voltage`
- **What Changed:**
  - Added temperature compensation to `HealthyTwinObserver` (`app/simulation/plant.py`): stator resistance scales with copper temperature coefficient $\alpha = 0.00393\text{ K}^{-1}$ ($R_s(T) = R_{s,20}[1 + \alpha(T - 20)]$), preventing false electrical residual alarms during normal thermal warm-up.
  - Implemented dynamic grid frequency estimator `estimate_grid_frequency()` in `app/diagnostics/electrical.py` using Clarke transformation $\alpha\text{--}\beta$ and analytic instantaneous phase unwrapping, eliminating hardcoded 50 Hz assumptions and supporting 60 Hz / variable-frequency supplies.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_4_temp_comp_and_grid_freq.py::test_temp_compensated_twin_observer_prevents_false_fd`
  - `backend/app/tests/diagnostics/test_p1_4_temp_comp_and_grid_freq.py::test_grid_frequency_estimation_50hz_and_60hz`

---

### P1-5. Out-of-Distribution Gating for ML Classifier
- **Commit:** `8b860ee fix(P1-5): add OOD confidence gating and anomaly detection for ML channel`
- **What Changed:**
  - Integrated out-of-distribution (OOD) distance gating and entropy thresholding in `MechanicalClassifier` (`app/diagnostics/ml/classifier.py`).
  - Unseen operating regimes, novel vibration patterns, or high-entropy outputs yield `DiagFault.INDETERMINATE` with low confidence rather than high-confidence misclassifications.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_5_ml_ood_gating.py::test_ml_ood_input_yields_indeterminate_or_low_confidence`

---

### P1-6. Dynamic Thermal Rate-of-Rise & Thermal Twin Residual
- **Commit:** `6e5e3fe fix(P1-6): calibrate thermal rate-of-rise to motor model and add thermal twin residual`
- **What Changed:**
  - Calibrated maximum allowable temperature rate-of-rise $(dT/dt)_{\max}$ in `ThermalDiagnostic` (`app/diagnostics/thermal.py`) proportional to motor thermal time constant $\tau_s$ and rated temperature rise:
    $$(dT/dt)_{\text{max\_normal}} = 1.30 \cdot \frac{T_{\text{warn}} - T_{\text{ambient}}}{\tau_s} \cdot 60\text{ K/min}$$
  - Introduced thermal twin observer that computes expected stator temperature rise from load current: flags cooling failure / ventilation blockage if measured temperature significantly exceeds thermal observer expectation ($\Delta T_{\text{residual}} > 25\text{ K}$).
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_6_thermal_model_residual.py::test_thermal_rate_of_rise_scaled_to_motor_tau`
  - `backend/app/tests/diagnostics/test_p1_6_thermal_model_residual.py::test_thermal_twin_residual_detects_cooling_loss`

---

### P1-7. High-Priority Persistence Queue for Safety-Critical Audit Rows
- **Commit:** `ab78f01 fix(P1-7): add high-priority persistence queue for critical alerts and trips`
- **What Changed:**
  - Re-architected asynchronous persistence in `app/runtime/writer.py` with dual-queue priority scheduling:
    - High-priority queue reserved exclusively for emergency trips, safety alerts, and configuration updates.
    - Low-priority queue for periodic telemetry / diagnosis snapshots.
  - Under database latency or high telemetry ingest load, low-priority frames are coalesced/dropped while high-priority audit events are guaranteed delivered without loss.
- **Covering Tests:**
  - `backend/app/tests/runtime/test_p1_7_persistence_priority_queue.py::test_high_priority_events_preserved_under_queue_saturation`

---

### P1-8. WebSocket Authentication, Token Lifecycle & Revocation
- **Commit:** `004d040 fix(P1-8): support Sec-WebSocket-Protocol auth, refresh rotation and connection token revocation`
- **What Changed:**
  - Enhanced WebSocket connection handler in `app/api/routes/ws.py` to support standard `Sec-WebSocket-Protocol: bearer, <token>` header authentication in addition to query param tokens.
  - Implemented token revocation checking and connection termination when user tokens are invalidated or revoked.
- **Covering Tests:**
  - `backend/app/tests/api/test_p1_8_websocket_auth.py::test_websocket_connect_with_sec_protocol_bearer`
  - `backend/app/tests/api/test_p1_8_websocket_auth.py::test_websocket_rejects_revoked_or_invalid_token`

---

### P1-9. Recommendation Catalog & Elimination of Fallback Contradictions
- **Commit:** `47671c2 fix(P1-9): complete recommendation catalog across all fault types and zones`
- **What Changed:**
  - Expanded recommendation mapping in `app/diagnostics/recommendations.py` to cover all 16 `DiagFault` members across all ISO condition zones (A, B, C, D).
  - Eliminated contradictory outputs (such as `"CRITICAL: Healthy"` or unhelpful default messages).
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_9_recommendations.py::test_all_fault_types_have_valid_recommendations`
  - `backend/app/tests/diagnostics/test_p1_9_recommendations.py::test_healthy_motor_in_all_zones_never_emits_critical`

---

### P1-10. Motor Health Index (MHI) Trip Latching & Nomenclature
- **Commit:** `84f86dc fix(P1-10): clamp MHI on latched severity during trip and document health index`
- **What Changed:**
  - Updated `MotorHealthIndex` computation during `TRIP` state: clamps health index based on latched trip severity, preventing misleading recovery of health scores while a machine remains tripped.
  - Aligned zone terminology with composite health index definitions across backend docstrings and UI tooltips.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p1_10_mhi_latching.py::test_mhi_clamps_low_during_latched_trip`

---

## Tier P2: UI & API Usability

### P2-1. Parameters Studio Parameter Update Pipeline
- **Commit:** `7adf262 fix(P2-1): wire PATCH /motors/{id}/params with validation and apply action in Parameters Studio`
- **What Changed:**
  - Implemented `PATCH /api/v1/motors/{id}/params` in backend router `app/api/routes/motors.py`:
    - Validates candidate parameters through `validate_motor_params()`.
    - Updates database model and emits audit configuration log.
    - Synchronizes live running motor worker state without restarting simulation.
  - Added "Apply to Motor Digital Twin" action and validation error handling in frontend `MotorParamsStudio.tsx`.
- **Covering Tests:**
  - `backend/app/tests/api/test_p2_1_params_patch.py::test_admin_patch_motor_params`
  - `backend/app/tests/api/test_p2_1_params_patch.py::test_operator_cannot_patch_motor_params`
  - `backend/app/tests/api/test_p2_1_params_patch.py::test_patch_motor_params_rejects_unstable_parameters`
  - `frontend/src/components/Panels.test.tsx::MotorParamsStudio renders parameter inputs and triggers validation`

---

### P2-2. Global TripBanner Restoration & Dead Code Pruning
- **Commit:** `8a8c7a0 fix(P2-2): restore global TripBanner, remove dead service workers and unread variables`
- **What Changed:**
  - Restored persistent `TripBanner` in `frontend/src/App.tsx`, displaying trip alarms and acknowledge action globally across all views.
  - Removed dead service workers (`frontend/public/sw.js`, `frontend/public/service-worker.js`).
  - Removed unused internal state variables and obsolete prototype code.
- **Covering Tests:**
  - `frontend/src/components/Panels.test.tsx::TripBanner renders and executes acknowledgment`

---

### P2-3. UI Alerts Management & Process Shaft Load Demand Control
- **Commit:** `1448c62 fix(P2-3): wire alerts modal on navbar bell and add process shaft load control`
- **What Changed:**
  - Created `AlertsModal.tsx` in `frontend/src/components/AlertsModal.tsx`:
    - Displays active and acknowledged safety alerts (`GET /api/v1/motors/{id}/alerts`).
    - Provides operator acknowledge action (`POST /api/v1/motors/{id}/alerts/{id}/ack`).
    - Connected to floating navbar `<Bell />` button with live active alarm badge.
  - Added Process Shaft Demand (`base_load_nm`) slider and input in `SadaPanel.tsx`, calling `PATCH /api/v1/motors/{id}/load` to allow operators to change mechanical shaft load independently of SADA derating.
- **Covering Tests:**
  - `frontend/src/components/Panels.test.tsx::AlertsModal renders alert list and acknowledges active alerts`
  - `frontend/src/components/Panels.test.tsx::SadaPanel renders process load control and supervisory status`

---

### P2-4. Scalar Boundary Conversions, RuntimeWarning Enforcement & Harmonic Guidance
- **Commit:** `ec0117c fix(P2-4): convert numpy float scalars at boundary, treat RuntimeWarning as error, document harmonic THD threshold`
- **What Changed:**
  - Added `_sanitize_val()` recursive scalar conversion in `app/diagnostics/schema.py`: converts `np.float64`, `np.float32`, and other numpy types to Python native scalars at `ChannelVerdict` and `FusedDiagnosis` boundaries.
  - Updated `SupplyDiagnostic` (`app/diagnostics/supply.py`) to cast all metrics and details to standard `float`.
  - Configured `-W error::RuntimeWarning` in pytest configuration (`pyproject.toml`). All simulation and diagnostic tests run without warnings.
  - Documented harmonic distortion threshold behavior in `FaultConsole.tsx`: severity 0.5 injects ~6% THD, which is nominal per EN 50160 ($\text{THD} \le 8\%$) and unflagged by design; severity $\ge 0.70$ is required to trigger a supply anomaly.
- **Covering Tests:**
  - `backend/app/tests/diagnostics/test_p2_4_misc_correctness.py::test_p2_4_numpy_scalars_converted_at_verdict_boundary`
  - `backend/app/tests/diagnostics/test_p2_4_misc_correctness.py::test_p2_4_supply_verdict_uses_pure_floats`
  - `backend/app/tests/diagnostics/test_p2_4_misc_correctness.py::test_p2_4_supply_harmonic_severity_mapping`

---

## Tier P3: Docs, Config Hygiene & Code Splitting

### P3. Configuration Sanitization, Documentation Accuracy & Frontend Chunking
- **Commit:** `b60753d fix(P3): sanitize compose passwords, fix coverage omit path, update README stats, code-split frontend and prune unverified models`
- **What Changed:**
  - Replaced fallback passwords in `compose.yaml` with mandatory variable substitutions: `${MYSQL_PASSWORD:?set MYSQL_PASSWORD}` and `${MYSQL_ROOT_PASSWORD:?set MYSQL_ROOT_PASSWORD}`.
  - Fixed coverage omit path in `backend/pyproject.toml` from `app/ml/train.py` to `app/diagnostics/ml/train.py`.
  - Removed unverified `CHEN_2025_MOTOR` parameter set ($\sigma \approx 0.77$) from `params.py` and simulation tests to prevent accidental use of unphysical parameters.
  - Updated `README.md` test metrics to reflect current state (290 tests, ~88% coverage) and clarified single-core capacity (5+ motors with rules backend, 2–3 with deep learning).
  - Code-split heavy frontend components (`Motor3DViewer`, `HistoryView`, `EngineeringDocsModal`) using React `lazy()` and `Suspense`, and configured Vite manual chunking for vendor libraries (`vendor-charts`, `vendor-react`, `vendor-query`, `vendor-icons`). All chunks are under 382 kB with zero build warnings.
- **Covering Tests:**
  - `backend/app/tests/deploy/test_deployment.py::TestComposeAndEdgeConfigurations::test_compose_yaml_environment_defaults`
  - `backend/app/tests/simulation/test_dynamics.py::test_zero_state_zero_input_has_zero_derivative`

---

## Summary of Deferred Items & Current Status

| Item | Status | Justification / Notes |
|---|---|---|
| Optional PyTorch Conv-BiLSTM Retraining | Fully Supported (Optional) | The training pipeline (`python -m app.diagnostics.ml.train`) is verified and functional when PyTorch is installed. On CPU/minimal environments, the rules-based envelope/order classifier operates seamlessly as verified in CI and the audit harness. |
| MySQL Table Partitioning | Documented Limitation | MySQL retention is managed by `app/runtime/retention.py` periodic cleanup jobs. Physical table partitioning is deferred to future enterprise cluster deployments. |

Every audit defect has been resolved, regression-tested, and verified against clean linters and test suites.
