#!/bin/sh
# Nightly encrypted copy of production data to storage off this server.
#
# Every other backup (scripts/backup_postgres.sh, financial_ingestion's backup)
# lives on the VPS itself, so losing or compromising the VPS lost them too, and
# admin_control.sqlite3 had no backup at all. This copies, after those run:
#   postgres/   the verified pg_dump files
#   sqlite/<stamp>/  a consistent snapshot of every SQLite database in the data
#                volume (scripts/sqlite_snapshots.py), kept for $KEEP_DAYS days
#   data/       everything else in the data volume (documents, financial
#                backups and artifacts), live database files excluded
#
# rclone runs from a pinned image, so nothing is installed on the host. Its
# remotes come from $ENV_FILE, written by the deploy from GitHub secrets:
# "offsite" is the S3-compatible bucket, "secure" an rclone crypt remote over
# it, so files are encrypted before they leave this machine. Restore: see
# DEPLOY.md, "Off-site backups".
set -eu

DOCKER=${DOCKER:-/snap/bin/docker}
ENV_FILE=${ENV_FILE:-/root/uzstock/offsite-backup.env}
RCLONE_IMAGE=${RCLONE_IMAGE:-rclone/rclone:1.68.2}
APP_IMAGE=${APP_IMAGE:-uzstock-web:latest}
DATA_VOLUME=${DATA_VOLUME:-uzstock_data}
PG_DIR=${PG_DIR:-/root/uzstock/backups/postgres}
SCRIPTS=${SCRIPTS:-/root/uzstock/app/scripts}
KEEP_DAYS=${KEEP_DAYS:-45}

if [ ! -s "$ENV_FILE" ]; then
  echo "Off-site backup is not configured: $ENV_FILE is missing." >&2
  exit 1
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
staging=offsite-staging

# Snapshots are written into the data volume so the upload below reads them
# from the same mount; they are removed again whatever happens.
cleanup() {
  "$DOCKER" run --rm --network none --user root --entrypoint rm -v "$DATA_VOLUME:/app/data" "$APP_IMAGE" \
    -rf "/app/data/$staging" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$DOCKER" run --rm -i --network none --user root --entrypoint python -v "$DATA_VOLUME:/app/data" "$APP_IMAGE" \
  - /app/data "/app/data/$staging/sqlite" < "$SCRIPTS/sqlite_snapshots.py"

# RCLONE_DOCKER_ARGS: extra docker arguments, used by CI to mount a local test target.
rclone() {
  # shellcheck disable=SC2086
  "$DOCKER" run --rm --env-file "$ENV_FILE" ${RCLONE_DOCKER_ARGS:-} \
    -v "$PG_DIR:/backup/postgres:ro" -v "$DATA_VOLUME:/backup/data:ro" \
    "$RCLONE_IMAGE" "$@"
}

if [ -d "$PG_DIR" ]; then
  rclone copy /backup/postgres secure:postgres --include "*.dump"
fi
rclone copy "/backup/data/$staging/sqlite" "secure:sqlite/$stamp"
rclone copy /backup/data secure:data \
  --exclude "/$staging/**" --exclude "*.db" --exclude "*.db-*" --exclude "*.sqlite" --exclude "*.sqlite-*" \
  --exclude "*.sqlite3" --exclude "*.sqlite3-*"
rclone delete secure:sqlite --min-age "${KEEP_DAYS}d"
rclone delete secure:postgres --min-age "${KEEP_DAYS}d"
rclone rmdirs secure:sqlite --leave-root

echo "Off-site backup $stamp complete."
