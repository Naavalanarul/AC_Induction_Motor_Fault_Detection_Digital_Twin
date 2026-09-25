# Changelog

All notable changes to this project. Versions follow semantic versioning; Docker images are
tagged with the git SHA and with the release tag.

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
