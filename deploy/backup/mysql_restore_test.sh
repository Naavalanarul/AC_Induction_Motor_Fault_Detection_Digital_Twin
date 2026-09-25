#!/usr/bin/env sh
# Restore a backup into a scratch database and verify it -- an untested backup is not a backup.
# Usage: MYSQL_ROOT_PASSWORD=... ./mysql_restore_test.sh backups/digital_twin_<stamp>.sql.gz [compose-service]
set -eu
FILE="$1"
SERVICE="${2:-mysql}"
SCRATCH="restore_check_$(date +%s)"
SRC="${MYSQL_DATABASE:-digital_twin}"
q() { docker compose exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$SERVICE" mysql -uroot -N -e "$1"; }
q "CREATE DATABASE $SCRATCH"
gunzip -c "$FILE" | docker compose exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$SERVICE" mysql -uroot "$SCRATCH"
status=0
for t in alembic_version motors sensors users faults_injected supervisory_actions alerts diagnoses sensor_readings; do
  n=$(q "SELECT COUNT(*) FROM $SCRATCH.$t")
  echo "$t: $n rows restored"
done
[ "$(q "SELECT COUNT(*) FROM $SCRATCH.motors")" -ge 1 ] || { echo "FAIL: no motors restored"; status=1; }
[ -n "$(q "SELECT version_num FROM $SCRATCH.alembic_version")" ] || { echo "FAIL: no alembic version"; status=1; }
q "DROP DATABASE $SCRATCH"
[ $status -eq 0 ] && echo "RESTORE CHECK PASSED ($FILE)"
exit $status
