#!/usr/bin/env sh
# Back up the database and uploaded media for the compose deployment.
#
# Usage:
#   POSTGRES_PASSWORD=... sh scripts/backup.sh
#   COMPOSE_ENV_FILE=.env.production.local sh scripts/backup.sh
#   BACKUP_DIR=/srv/backups RETENTION_DAYS=30 sh scripts/backup.sh

set -eu

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-.env.production.local}"
STAMP="$(date +%Y%m%d-%H%M%S)"
POSTGRES_USER="${POSTGRES_USER:-salesmind}"
POSTGRES_DB="${POSTGRES_DB:-salesmind}"

compose() {
    if [ -f "$COMPOSE_ENV_FILE" ]; then
        docker compose --env-file "$COMPOSE_ENV_FILE" "$@"
    else
        docker compose "$@"
    fi
}

mkdir -p "$BACKUP_DIR"

echo "dumping database to $BACKUP_DIR/db-$STAMP.dump"
compose exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
    > "$BACKUP_DIR/db-$STAMP.dump"

echo "archiving media to $BACKUP_DIR/media-$STAMP.tar.gz"
# The web image has an ENTRYPOINT that launches gunicorn and ignores extra
# arguments, so the tar command must override it with --entrypoint.
compose run --rm --no-deps --entrypoint sh -T web \
    -c 'tar -czf - -C /app/media .' \
    > "$BACKUP_DIR/media-$STAMP.tar.gz"

find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime +"$RETENTION_DAYS" -delete

echo "backup complete; restore with:"
echo "  compose exec -T db pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists < $BACKUP_DIR/db-$STAMP.dump"
