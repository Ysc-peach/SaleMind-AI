FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq5 is needed by psycopg; curl is used by the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements
RUN pip install -r requirements/prod.txt

COPY . .

EXPOSE 8000

ENTRYPOINT ["sh", "/app/deploy/entrypoint.sh"]
