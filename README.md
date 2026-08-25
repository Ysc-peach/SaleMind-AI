# SalesMind AI

SalesMind AI is a modular Django monolith. The first phase establishes the
PostgreSQL-backed project foundation and will add identity, roles, Django
Admin management, and JWT authentication in the following tasks.

## Requirements

- Python 3.12.14
- PostgreSQL 17 or a compatible supported PostgreSQL release

SQLite is not supported. Keep local credentials in the ignored `.env` file or
in process environment variables; do not commit them.

## Local setup

Create a PostgreSQL database and role, for example from `psql` as a database
administrator:

```sql
CREATE USER salesmind WITH PASSWORD 'choose-a-local-password';
CREATE DATABASE salesmind OWNER salesmind;
```

Create the virtual environment and install the pinned dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
```

Copy the environment template and replace every placeholder, including the
database password:

```powershell
Copy-Item .env.example .env
```

`DATABASE_URL` must use the local PostgreSQL role and database. URL-encode any
reserved characters in the password. `DJANGO_SECRET_KEY` and `JWT_SIGNING_KEY`
must be different long random values.

Once the custom user foundation is present, apply migrations and create the
technical Django Admin account:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

The current Task 1 foundation intentionally points `AUTH_USER_MODEL` at the
`accounts.User` interface that is introduced in Task 2. Therefore the
migration, superuser, and full Django system-check commands become runnable
after Task 2 is applied.

## Tests and checks

Tests use pytest-django and the configured PostgreSQL database:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

During Task 1, use `pip check`, Python compilation, and static configuration
inspection. The full `manage.py check` is intentionally deferred until the
custom `accounts.User` model exists.

## Environment variables

The required local variables are documented in `.env.example`:

- `DJANGO_SETTINGS_MODULE` selects `config.settings.local` by default.
- `DJANGO_SECRET_KEY` signs Django data and is separate from the JWT key.
- `JWT_SIGNING_KEY` signs JWTs and must be different from the Django key.
- `DATABASE_URL` is the PostgreSQL connection URL.
- `DJANGO_ALLOWED_HOSTS` is a comma-separated host list.
- `DJANGO_CSRF_TRUSTED_ORIGINS` is a comma-separated origin list.

`config.settings.local` reads `.env` without overriding values already supplied
by the process environment. `config.settings.production` fails closed when
required hosts or trusted origins are absent and enables HTTPS redirect, secure
cookies, HSTS, and the proxy SSL header.

## Phase-one API surface

The authentication endpoints will be added in Task 3:

- `POST /api/auth/login/` with `username` and `password`, returning `access`
  and `refresh` tokens.
- `POST /api/auth/refresh/` with `refresh`, returning a new `access` token.
- `GET /api/auth/me/` with `Authorization: Bearer <access>`, returning the
  current user's identity and business role.

Django Admin is available at `/admin/` after the custom user and Admin setup.
Business role is independent of Django's `is_staff` and `is_superuser` flags.

## Out of scope for this phase

Customer and Opportunity models, AI/RAG/LLM integrations, pgvector,
LangGraph, Redis, Celery, Kafka, Docker, microservices, JWT blacklist and
rotation, logout, runtime-configurable roles, and speculative service or
selector layers are not part of the first-phase backend foundation.
