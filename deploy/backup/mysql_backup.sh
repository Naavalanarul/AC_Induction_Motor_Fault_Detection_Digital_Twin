#!/usr/bin/env sh
# Consistent logical backup of the digital-twin database (InnoDB, no table locks).
# Usage: MYSQL_PASSWORD=... ./mysql_backup.sh [compose-service] [out-dir]
# Schedule daily (cron/systemd timer) and copy the result off-site.
set -eu
SERVICE="${1:-mysql}"
OUT_DIR="${2:-./backups}"
DB="${MYSQL_DATABASE:-digital_twin}"
USER="${MYSQL_USER:-dt}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
FILE="$OUT_DIR/${DB}_${STAMP}.sql.gz"
docker compose exec -T -e MYSQL_PWD="$MYSQL_PASSWORD" "$SERVICE" \
  mysqldump --single-transaction --quick --routines --triggers --no-tablespaces -u"$USER" "$DB" | gzip -9 > "$FILE"
gzip -t "$FILE"
echo "$FILE"
