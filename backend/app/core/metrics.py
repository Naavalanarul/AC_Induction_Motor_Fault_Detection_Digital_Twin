"""core/metrics.py — Prometheus metrics exposed at /metrics."""

from prometheus_client import Counter, Gauge, Histogram

SIM_TICKS = Counter("dt_sim_ticks_total", "Simulation chunks processed", ["motor_id"])
SIM_TICK_SECONDS = Histogram("dt_sim_tick_seconds", "Wall time per simulation chunk (sim+sensors)",
                             buckets=(0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5))
DIAG_SECONDS = Histogram("dt_diagnosis_seconds", "Diagnostic engine latency per chunk",
                         buckets=(0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5))
SIM_LAG_SECONDS = Gauge("dt_sim_lag_seconds", "How far the simulation lags real time", ["motor_id"])
WS_CONNECTIONS = Gauge("dt_ws_connections", "Open WebSocket connections")
DB_WRITE_SECONDS = Histogram("dt_db_write_seconds", "Batched DB write latency")
DB_WRITE_ERRORS = Counter("dt_db_write_errors_total", "Failed DB write batches")
DB_DROPPED_TOTAL = Counter("dt_db_dropped_total", "Telemetry rows dropped due to queue pressure", ["priority"])
DB_BATCH_FAILED_TOTAL = Counter("dt_db_batch_failed_total", "Failed DB write batches by category", ["kind"])
DB_DEAD_LETTER_TOTAL = Counter("dt_db_dead_letter_total", "Records written to dead-letter audit file")
FAULT_INJECTIONS = Counter("dt_fault_injections_total", "Fault injections", ["fault_type"])
SADA_TRIPS = Counter("dt_sada_trips_total", "SADA trips", ["motor_id"])
WORKER_RESTARTS = Counter("dt_worker_restarts_total", "Supervised worker restarts", ["motor_id"])
HTTP_REQUESTS = Histogram("dt_http_request_seconds", "HTTP request latency", ["method", "route", "status"])
DB_POOL_CHECKED_OUT = Gauge("dt_db_pool_checked_out", "DB connections currently checked out of the pool")
DB_POOL_CAPACITY = Gauge("dt_db_pool_capacity", "pool_size + max_overflow")
ML_BACKEND = Gauge("dt_ml_backend_available", "1 if the Conv-BiLSTM backend is loaded, 0 if on rule fallback")
MOTOR_HEALTH_INDEX = Gauge("dt_motor_health_index", "Motor Health Index in [0, 100]", ["motor_id", "motor_name"])
