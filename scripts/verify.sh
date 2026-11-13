#!/usr/bin/env bash
# One reproducible verification entrypoint for local machines and CI runners.
#
# Usage:
#   DATABASE_URL=postgres://... bash scripts/verify.sh
#   DATABASE_URL=postgres://... bash scripts/verify.sh backend
#   bash scripts/verify.sh frontend
#
# The backend suite needs PostgreSQL with the pgvector extension. Tests create
# their database from TEST_DATABASE_TEMPLATE (default: salesmind_test_template),
# so that template must exist and contain the extension.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python}"
PART="${1:-all}"

verify_backend() {
    : "${DATABASE_URL:?DATABASE_URL is required for the backend suite}"
    export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.test}"
    export TEST_DATABASE_TEMPLATE="${TEST_DATABASE_TEMPLATE:-salesmind_test_template}"

    "$PYTHON" -m pip install -r requirements/dev.txt
    "$PYTHON" manage.py check
    "$PYTHON" manage.py makemigrations --check --dry-run
    "$PYTHON" -m pytest -q
}

verify_frontend() {
    cd frontend
    npm ci
    npm test
    npm run build
}

case "$PART" in
    all)
        verify_backend
        verify_frontend
        ;;
    backend)
        verify_backend
        ;;
    frontend)
        verify_frontend
        ;;
    *)
        echo "unknown part: $PART (expected all, backend or frontend)" >&2
        exit 2
        ;;
esac
