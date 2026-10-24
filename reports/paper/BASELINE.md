# Baseline Test and Coverage Report

Measured on: 2026-10-24
Platform: macOS (Darwin)

## Backend (pytest)

- **Command:** `cd backend && pytest -q --cov=app`
- **Python version:** Python 3.11.16
- **pytest version:** pytest 9.1.1
- **Passed:** 382
- **Skipped:** 1 (`app/tests/api/test_db_integration.py` requires live MySQL)
- **Failed:** 0
- **Warnings:** 1 (StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated)
- **Total Statements:** 9,077
- **Missed Statements:** 1,208
- **Total Line Coverage:** 87%

### Breakdown by Key Subsystem
- `app/api`: 85% - 100%
- `app/core_physics`: 78% - 97%
- `app/diagnostics`: 59% - 100% (engine 100%, fusion 100%, health_index 100%, mcsa 96%, prognosis 96%, protection 99%, rul_engine 93%, thermal 98%, electrical 98%, fault_classifier 59%)
- `app/runtime`: 62% - 94% (worker 94%, writer 89%, manager 83%)
- `app/sensors`: 86% - 100%
- `app/simulation`: 60% - 100% (plant 90%, dynamics 100%, motor_twin 100%, twin_state 100%, state_space_solver 100%, faults 97%, pwm 95%)
- `app/static_analysis`: 79% - 99%
- `app/supervisory`: 94% (SADA supervisor)
- `app/validation`: 48% - 98% (splits 98%, metrics 90%, loaders 76% - 92%, protocols 48% due to untested real-data paths)

## Frontend (vitest)

- **Command:** `cd frontend && npm test -- --run`
- **Vitest version:** v5.0.1
- **Test Files Passed:** 6 / 6
- **Tests Passed:** 49 / 49
- **Skipped:** 0
- **Failed:** 0
- **Duration:** ~1.32s
- **Suites:**
  - `src/dsa/PriorityQueue.test.ts` (4 tests)
  - `src/api/client.test.ts` (3 tests)
  - `src/components/TripFlows.test.tsx` (11 tests)
  - `src/components/Panels.test.tsx` (17 tests)
  - `src/components/LoginForm.test.tsx` (7 tests)
  - `src/components/StaticDiagnosisPanel.test.tsx` (7 tests)
