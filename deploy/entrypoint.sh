#!/usr/bin/env sh
# Container entrypoint: apply migrations, collect static, then serve.

set -eu

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# LangGraph keeps its own tables; setup() is idempotent (CREATE IF NOT EXISTS).
python -c "
from apps.sales.services.solution_workflow_checkpoint import setup_solution_workflow_checkpoint_schema
setup_solution_workflow_checkpoint_schema()
"

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-180}" \
    --access-logfile - \
    --error-logfile -
