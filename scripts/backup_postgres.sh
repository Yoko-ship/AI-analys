#!/bin/sh
# Nightly PostgreSQL backup for the uzstock-db container (accounts, sessions,
# analytics). Run by uzstock-postgres-backup.service on the VPS host.
#
# Writes a custom-format dump, proves it is restorable by listing its contents
# with pg_restore, and keeps the newest $KEEP verified dumps. A dump that fails
# verification is deleted and the unit fails, so a bad night is visible in
# `systemctl list-units --failed` instead of leaving a silent broken file.
set -eu

DOCKER=${DOCKER:-/snap/bin/docker}
CONTAINER=${CONTAINER:-uzstock-db}
DEST=${DEST:-/root/uzstock/backups/postgres}
KEEP=${KEEP:-14}

umask 077
mkdir -p "$DEST"
chmod 700 "$DEST"

user=$("$DOCKER" exec "$CONTAINER" printenv POSTGRES_USER)
db=$("$DOCKER" exec "$CONTAINER" printenv POSTGRES_DB)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="$DEST/$db-$stamp.dump"
tmp="$file.partial"

trap 'rm -f "$tmp"' EXIT
"$DOCKER" exec "$CONTAINER" pg_dump -U "$user" -d "$db" --format=custom --compress=6 > "$tmp"

# Restorability check: pg_restore must read the whole archive's table of contents.
entries=$("$DOCKER" exec -i "$CONTAINER" pg_restore --list < "$tmp" | grep -vc '^;')
if [ "$entries" -lt 1 ]; then
    echo "backup verification failed: empty archive" >&2
    exit 1
fi
mv "$tmp" "$file"
trap - EXIT

# Rotation: keep the newest $KEEP verified dumps.
ls -1t "$DEST"/"$db"-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

echo "postgres backup ok: $file ($(du -h "$file" | cut -f1), $entries archive entries)"
