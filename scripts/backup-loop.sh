#!/usr/bin/env sh
# Periodic backup sidecar for the compose deployment.
#
# Runs inside the compose network, so it reaches PostgreSQL directly and reads
# the shared media volume. No docker socket and no host cron are required.

set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_USER="${POSTGRES_USER:-salesmind}"
POSTGRES_DB="${POSTGRES_DB:-salesmind}"

mkdir -p "$BACKUP_DIR"
echo "backup loop: every ${INTERVAL_SECONDS}s, retaining ${RETENTION_DAYS} days"

while :; do
    stamp="$(date +%Y%m%d-%H%M%S)"
    db_tmp="$BACKUP_DIR/.db-$stamp.dump.tmp"
    media_tmp="$BACKUP_DIR/.media-$stamp.tar.gz.tmp"

    if pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
        > "$db_tmp"; then
        mv "$db_tmp" "$BACKUP_DIR/db-$stamp.dump"
    else
        echo "backup $stamp: database dump failed" >&2
        rm -f "$db_tmp"
        sleep "$INTERVAL_SECONDS"
        continue
    fi

    if tar -czf "$media_tmp" -C /data/media .; then
        mv "$media_tmp" "$BACKUP_DIR/media-$stamp.tar.gz"
    else
        echo "backup $stamp: media archive failed" >&2
        rm -f "$media_tmp"
    fi

    find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$RETENTION_DAYS" -delete
    find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime +"$RETENTION_DAYS" -delete
    echo "backup $stamp complete"

    sleep "$INTERVAL_SECONDS"
done
