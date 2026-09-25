# Load-test baseline

Measured on 2026-09-25 with `loadtest/ws_load.py`, 30 s per run.

- **Environment:** the Docker Compose stack with MySQL, Redis, one backend process and nginx, on a
  4-vCPU cloud sandbox. The backend image was built with `INSTALL_ML=false`, so the vibration
  channel used the rule-based classifier. The Conv-BiLSTM adds a little inference time per hop.
- **Load generator:** ran on the same host, so it competed with the backend for CPU. Treat these
  numbers as an order-of-magnitude baseline, not a benchmark.

The UI stream target is 10 frames/s per viewer. "Sim lag" is `dt_sim_lag_seconds`, which shows
how far a motor's simulation falls behind real time.

| Motors | Viewers | Frames/s per viewer (mean) | Inter-frame gap p95 | Sim lag | Backend CPU |
|---|---|---|---|---|---|
| 1 | 0 | – | – | 0 s | 19 % |
| 1 | 50 | 9.96 | 197 ms | 0 s | 58 % |
| 1 | 200 | 4.99 | 409 ms | 1.8 s | 98 % |
| 2 | 100 | 7.40 | 239 ms | 1.2–1.6 s | 107 % |
| 3 | 0 | – | – | ≤ 0.5 s | 82 % |

All runs had 0 connection errors.

## Findings

- One Python process is GIL-bound at roughly one core. Each motor costs about 25 ms of CPU per
  100 ms chunk: ~13 ms simulation, ~9 ms diagnostics, plus spectra. So **2–3 motors per process**.
- Before these runs, every frame was JSON-encoded once per viewer and always carried the spectra
  and scalogram (~54 KB). At 100 viewers that alone used about one core, and delivery dropped to
  1.9 frames/s. Two fixes: frames are now encoded once and fanned out, and spectra/scalogram are
  sent only when they change. That raised delivery to 5.6 frames/s under the same overloaded
  4-motor setup.
- **Scaling path:** run more backend replicas behind nginx with `REDIS_URL` set. Each motor is owned
  by exactly one replica through a Redis lock, so motors spread across processes. WebSocket
  viewers spread across replicas through Redis pub/sub. This is covered by
  `test_redis_broker_pubsub_and_ownership`, but a multi-replica load test has **not** been run yet.
  Moving diagnostics into a process pool is the next step if a single motor ever needs more than
  one core.
