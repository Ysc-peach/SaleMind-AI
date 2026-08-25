# SalesMind AI

SalesMind AI is a modular Django monolith with a PostgreSQL-backed identity
foundation, Django Admin user management, business roles, and JWT
authentication.

## Requirements

- Python 3.12.14
- PostgreSQL 17, or a compatible supported PostgreSQL release

SQLite is not supported. Keep local credentials in the ignored `.env` file or
in process environment variables; never commit real passwords or signing keys.

## Project layout

- `config/settings/base.py` contains shared Django, PostgreSQL, DRF, and JWT
  settings.
- `config/settings/local.py` loads the ignored `.env` for local development.
- `config/settings/production.py` enables fail-closed production security
  settings.
- `config/settings/test.py` requires a PostgreSQL `DATABASE_URL` and supplies
  deterministic test-only signing keys when the process does not provide them.
- `apps/accounts/` contains the custom user model, business roles, and Django
  Admin registration.
- `apps/accounts/api/` contains the authentication URL routes, serializer, and
  current-user API view.

## Local setup

Create a PostgreSQL database and login role. For example, from `psql` as a
database administrator:

```sql
CREATE USER salesmind WITH PASSWORD 'choose-a-local-password' CREATEDB;
CREATE DATABASE salesmind OWNER salesmind;
```

`CREATEDB` is required for this local development role because Django's test
runner creates a temporary PostgreSQL test database. A production application
role should follow least privilege and must not receive `CREATEDB`.

Create the virtual environment and install the pinned dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
```

Copy the template, then replace every placeholder with local values:

```powershell
Copy-Item .env.example .env
```

`.env` selects `config.settings.local` and must provide:

- `DJANGO_SECRET_KEY`: a long random Django signing value.
- `JWT_SIGNING_KEY`: a different long random JWT signing value.
- `DATABASE_URL`: a PostgreSQL URL such as
  `postgresql://salesmind:replace-with-local-db-password@127.0.0.1:5432/salesmind`.
- `DJANGO_ALLOWED_HOSTS`: a comma-separated host list.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: a comma-separated origin list.

URL-encode reserved characters in the database password. Process environment
variables take precedence over values in `.env` for local settings.

Apply migrations, create the technical Django Admin account, and start the
development server:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

The Django Admin site is available at `http://127.0.0.1:8000/admin/`.

## Users, business roles, and technical privileges

Every user has one business role: `admin`, `sales`, or `presales`. The role is
application data; it is not a Django permission flag. In particular, assigning
the business `admin` role does not grant access to Django Admin.

`is_staff` allows a user to sign in to the Django Admin site when its model
permissions allow it. `is_superuser` grants all Django permissions and also
requires `is_staff=True`; `createsuperuser` creates this technical privileged
account. These flags remain independent from the user's business role.

## Authentication API

All API endpoints are under `/api/auth/` and use JSON.

### Login

`POST /api/auth/login/`

```json
{
  "username": "alice",
  "password": "StrongPassword123!"
}
```

Successful response (`200 OK`):

```json
{
  "access": "<access-token>",
  "refresh": "<refresh-token>"
}
```

### Refresh an access token

`POST /api/auth/refresh/`

```json
{
  "refresh": "<refresh-token>"
}
```

Successful response (`200 OK`):

```json
{
  "access": "<new-access-token>"
}
```

### Current user

`GET /api/auth/me/` with `Authorization: Bearer <access-token>`.

Successful response (`200 OK`):

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "first_name": "Alice",
  "last_name": "Seller",
  "role": "sales"
}
```

Access tokens last 15 minutes and refresh tokens last 7 days. Refresh-token
rotation, token blacklisting, and a logout endpoint are not enabled. The API
performs live user lookups, so deactivating a user rejects existing access and
refresh tokens.

## Tests and checks

The test settings do not load `.env`; pass the PostgreSQL connection in the
process environment. The test-only JWT default is used when `JWT_SIGNING_KEY`
is not set.

```powershell
$env:DATABASE_URL = "postgresql://salesmind:replace-with-local-db-password@127.0.0.1:5432/salesmind"
.\.venv\Scripts\python.exe -m pytest -q
```

With the local `.env` configured, verify migrations and Django configuration:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
```

For a production-settings verification, provide every required value explicitly
with safe non-production values, then run Django's deployment checks:

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.production"
$env:DJANGO_SECRET_KEY = "verification-only-django-secret-key-with-at-least-32-characters"
$env:JWT_SIGNING_KEY = "verification-only-jwt-signing-key-with-at-least-32-characters"
$env:DATABASE_URL = "postgresql://salesmind:replace-with-local-db-password@127.0.0.1:5432/salesmind"
$env:DJANGO_ALLOWED_HOSTS = "verification.example.test"
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://verification.example.test"
.\.venv\Scripts\python.exe manage.py check --deploy
```

Also verify the installed interpreter and dependency consistency:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip freeze
```

Production deployment must terminate HTTPS correctly and pass the original
HTTPS scheme through the configured proxy header; the verification values above
are not deployment credentials.

## Out of scope

This phase excludes customer and opportunity models, AI/RAG/LLM integrations,
pgvector, LangGraph, Redis, Celery, Kafka, Docker, microservices, runtime-
configurable roles, JWT rotation, JWT blacklisting, logout, and speculative
service or selector layers.
