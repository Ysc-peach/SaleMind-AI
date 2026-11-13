#!/usr/bin/env sh
# Back up the database and uploaded media for the compose deployment.
#
# Usage:
#   POSTGRES_PASSWORD=... sh scripts/backup.sh
#   BACKUP_DIR=/srv/backups RETENTION_DAYS=30 sh scripts/backup.sh

set -eu

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
POSTGRES_USER="${POSTGRES_USER:-salesmind}"
POSTGRES_DB="${POSTGRES_DB:-salesmind}"

mkdir -p "$BACKUP_DIR"

echo "dumping database to $BACKUP_DIR/db-$STAMP.dump"
docker compose exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
    > "$BACKUP_DIR/db-$STAMP.dump"

echo "archiving media to $BACKUP_DIR/media-$STAMP.tar.gz"
docker compose run --rm --no-deps -T web \
    tar -czf - -C /app/media . \
    > "$BACKUP_DIR/media-$STAMP.tar.gz"

find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime +"$RETENTION_DAYS" -delete

echo "backup complete; restore with:"
echo "  docker compose exec -T db pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists < $BACKUP_DIR/db-$STAMP.dump"
