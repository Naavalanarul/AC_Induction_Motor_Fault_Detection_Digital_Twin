# Operations runbook

## Environments

| Env | How | Config |
|---|---|---|
| local | `docker compose up --build` (or uvicorn + vite) | `.env` from `.env.example`, seeded demo motor |
| staging | `compose.yaml` + `compose.prod.yaml` on a VM, deployed by CI on `v*` tags | `.env.staging` on the VM |
| production | same topology; promoted from staging after manual approval (GitHub `production` environment) | `.env.production` on the VM |

All environment-specific values come from environment variables. `app/config.py` is the single
settings object. When `APP_ENV` is `staging` or `production`, startup refuses to proceed if
`JWT_SECRET` is not set explicitly or if CORS is `*`. Never commit a filled-in `.env*` file.
Inject secrets through the VM's environment or Docker secrets.

Feature flags come from `FEATURE_FLAGS=a,b`, exposed as `settings.feature_flags`.

## Deploying

CI builds images tagged with the commit SHA and pushes them on `main`. A `v*` tag deploys:

1. **staging** runs `deploy/deploy.sh staging` on the staging VM: pull images, run
   `alembic upgrade head` as its own step, recreate the services, wait for health checks.
2. **production** runs the same script after a reviewer approves the `production` environment.
   Production takes a fresh MySQL backup before migrating.

Migrations are never run automatically inside the app in production. `AUTO_CREATE_SCHEMA` is
for local development only.

> Caveat: `deploy/deploy.sh` has not been run against a real VM from this repository. Rehearse on
> staging first. Plain Compose recreates all backend replicas together, so expect a few seconds of
> API and WebSocket interruption. True zero-downtime rolling updates need Swarm/Kubernetes or a
> blue/green switch of the nginx upstream.

### TLS

`deploy/nginx/edge.conf` terminates TLS with Let's Encrypt certificates from
`/etc/letsencrypt/live/<domain>/`. Replace `dt.example.com` with your domain. Issue and renew
certificates with certbot on the host, using webroot `/var/www/certbot`.

## Backups and restore

```bash
set -a; . ./.env.production; set +a
deploy/backup/mysql_backup.sh mysql ./backups                   # daily via cron; copy off-site
deploy/backup/mysql_restore_test.sh ./backups/<file>.sql.gz     # restore into a scratch DB and verify
```

Both scripts were exercised against the Compose MySQL 8.4 container on 2026-09-25. The restore
check recovered all 9 tables (motors, sensors, users, faults, SADA actions, alerts, diagnoses,
sensor readings, alembic version) and passed. Run the restore check on a schedule too: an
untested backup is not a backup. A managed MySQL service with automated backups and
point-in-time recovery is preferred for production.

**Full restore:**

1. Stop the backend with `docker compose stop backend`.
2. Load the dump with `gunzip -c <file> | docker compose exec -T mysql mysql -uroot -p <db>`.
3. Run `alembic upgrade head`.
4. Start the backend.

## Observability

- **Logs.** JSON on stdout. Every line carries `request_id` (from `X-Request-ID`, else
  generated) and `motor_id` for worker logs. Ship them with your log driver (Loki, ELK). The
  production overlay rotates json-file logs.
- **Metrics.** `GET /metrics` on each backend replica. It is intentionally not routed through
  nginx; Prometheus scrapes it on the Docker network. The key series:
  - `dt_sim_ticks_total` and `dt_sim_lag_seconds`: simulation liveness and real-time lag
  - `dt_diagnosis_seconds`
  - `dt_ws_connections`
  - `dt_db_write_seconds`, `dt_db_write_errors_total`, `dt_db_pool_checked_out`
  - `dt_fault_injections_total`, `dt_sada_trips_total`, `dt_worker_restarts_total`
  - `dt_ml_backend_available`
  - `dt_http_request_seconds`
- **Dashboards.** Grafana at 127.0.0.1:3000 (tunnel over SSH). "Motor Digital Twin — service
  health" is provisioned from `deploy/grafana/`.
- **Alerts.** `deploy/prometheus/alerts.yml`:
  - backend down
  - simulation loop stalled
  - simulation lagging
  - DB pool nearly exhausted
  - DB write errors
  - 5xx rate above 5 %
  - worker restart loop
  - ML fallback active
  - motor tripped

  Configure a real receiver in `deploy/alertmanager/alertmanager.yml`.
- **Health.** `/healthz` is liveness. `/readyz` is readiness: it checks that the DB is reachable
  and every owned motor worker ticked within the last 5 s, and returns 503 otherwise. The Docker
  health check uses `/healthz`.

## Resilience behaviour

- Each motor runs in its own supervised asyncio task. A crash is logged and counted, and the
  worker is rebuilt from durable DB state (active faults, sensor modes) with exponential backoff.
  Other motors are unaffected.
- Diagnostic channels are isolated. If the ML model fails to load or errors, the vibration channel
  falls back to rules. The electrical, thermal and supply channels, and SADA, keep working.
- Fault injections and operator overrides are written to MySQL before they are applied.
  High-rate telemetry goes through a batched writer. If the DB is down, those rows are dropped and
  counted in `dt_db_write_errors_total`, but the simulation keeps running.
- On SIGTERM, the backend stops accepting WebSocket connections, stops the workers, flushes queued
  DB writes and closes the broker. Compose gives it `stop_grace_period: 30s`.
- A hardware sensor that stops responding trips its circuit breaker. The channel reports `stale`
  and its diagnostic becomes `unavailable` instead of blocking fusion.

## Scaling

One backend process handles about 2–3 motors (see `loadtest/RESULTS.md`). To scale, raise
`deploy.replicas` for `backend` and set `REDIS_URL`. A per-motor Redis lock gives each motor
exactly one owning replica; the other replicas stand by and take over within about 15 s if the
owner dies. REST commands and live frames travel over Redis pub/sub, so any replica can serve any
client.

## Data retention

The `retention_loop` task (hourly by default) deletes `sensor_readings` and `diagnoses` older than
`RETENTION_DAYS`. Fault injections, SADA actions and alerts are kept as the audit trail. MySQL
`PARTITION BY RANGE` is **not** set up. If tables grow large, add partitioning in a migration;
every unique key must then include the partition column.
