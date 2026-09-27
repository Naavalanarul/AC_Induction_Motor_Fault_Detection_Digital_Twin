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

### Fixed
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
