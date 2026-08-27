# SalesMind AI

SalesMind AI is a modular Django monolith with a PostgreSQL-backed identity
foundation, Django Admin user management, business roles, JWT authentication,
and the Phase Two Customer/Opportunity sales-domain APIs.

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
- `apps/accounts/api/` contains authentication, the current-user API, and the
  Sales-only active Presales option endpoint.
- `apps/sales/` contains the shared Customer and Opportunity models, migrations,
  role-filtered API views, explicit serializers, and page-number pagination.

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

## Phase Two sales domain

Phase Two delivers the Customer and Opportunity backend skeleton, minimum
business-role isolation, safe Customer collision search, and active Presales
options. API field names, URLs, and stored enum values are English; Chinese
text is used for model display labels.

### Domain model

`Customer` is shared company master data and has no owner in V1. It contains
`name`, `industry`, `company_size`, `basic_info`, `created_by`, and timestamps.
Duplicate names are allowed. `created_by` is a required, database-audit-only
`PROTECT` relation and is never returned by ordinary Customer APIs.

`Customer.basic_info` is reserved for shared, non-sensitive company
information. Do not put passwords, tokens, private personal data, or other
secrets in it. Customer and Opportunity deletion relationships are protected;
users are deactivated (`is_active=false`) instead of deleted so audit and
ownership relations remain valid.

`Opportunity` represents one sales project for a Customer. It contains
`project_name`, `customer`, `sales_owner`, optional `presales_owner`,
`raw_requirement`, `budget`, `stage`, `status`, `expected_launch_date`,
`created_by`, and timestamps. Its Customer relation and all three ownership or
audit user relations (`sales_owner`, `presales_owner`, and `created_by`) use
`PROTECT`; `raw_requirement` may be blank.

Stages are `initial_contact`, `requirement_analysis`, `presales_support`,
`solution`, `quotation`, and `negotiation`. Statuses are `active`, `won`,
`lost`, and `closed`. `closed` means manually terminated or archived; it is
distinct from a won or lost opportunity.

### API conventions and role matrix

All routes below use JSON and Bearer authentication. Customer search and the
Opportunity list use page-number pagination with 20 records per page.
Business access checks use `User.role` only; Django `is_staff` and
`is_superuser` do not grant or bypass business access. An object outside a
role-filtered Opportunity queryset returns `404`.

| Resource/action | Admin | Sales | Presales |
| --- | --- | --- | --- |
| Customer create, search, detail | yes | yes | `403` |
| Ordinary Customer list | `405` | `405` | `403` |
| Customer PATCH/PUT/DELETE | `405` | `405` | `403` |
| Opportunity list/detail | all Opportunities | own Opportunities | assigned Opportunities |
| Opportunity create | `403` | yes | `403` |
| Opportunity PATCH | `403` | own Opportunities only | `403` |
| Opportunity PUT/DELETE | `405` | `405` | `405` |
| Presales options | `403` | yes | `403` |

Thus Admin and Presales have read-only Opportunity access. Sales can update
only Opportunities they own.

### Customer APIs

- `POST /api/customers/` creates a Customer for an Admin or Sales user. The
  server stores the authenticated user as `created_by`; clients cannot use
  this API to set or change it.
- `GET /api/customers/{id}/` retrieves the safe Customer shape.
- `GET /api/customers/search/?q=...` performs a case-insensitive
  `name__icontains` collision search. A non-empty `q` is required, and results
  are ordered by `name`, then `id`, with 20 results per page.

Customer search/detail responses contain only shared Customer fields and an
active-Opportunity summary. Each summary is exactly:
`id`, `project_name`, `stage`, `status`, `is_mine`, and
`is_followed_by_other_sales`. Won, lost, and closed Opportunities are excluded.
The summary never exposes `raw_requirement`, `budget`, ownership objects,
`created_by`, or other sensitive Opportunity fields. Customer `created_by` is
also absent from create, search, and detail responses. The ordinary Customer
collection is intentionally not exposed; Customer PATCH, PUT, and DELETE all
return `405`.

The search uses `name__icontains` without a normal B-Tree name index. A future
PostgreSQL `pg_trgm`/GIN optimization is not part of the current delivery.

### Opportunity APIs

- `GET /api/opportunities/` lists Opportunities visible to the caller.
- `POST /api/opportunities/` lets Sales create an Opportunity.
- `GET /api/opportunities/{id}/` retrieves an authorized Opportunity.
- `PATCH /api/opportunities/{id}/` lets the owning Sales user update an
  Opportunity.

Opportunity lists always order by `-updated_at`, then `-id`, including across
  20-record pages. A Sales create accepts the project, Customer, optional
  active Presales assignment, raw requirement, budget, and expected launch
  date. The server sets `sales_owner` and `created_by` to the authenticated
  Sales user and leaves stage/status at their model defaults
  (`initial_contact`/`active`). A Presales assignment must reference an active
  user whose business role is `presales`.

Create payloads containing `sales_owner`, `created_by`, `stage`, or `status`
are explicitly rejected with `400`; they are not silently ignored. PATCH
writes only `project_name`, `presales_owner`, `raw_requirement`, `budget`,
`stage`, `status`, and `expected_launch_date`. PATCH payloads containing
`customer`, `sales_owner`, `created_by`, `created_at`, or `updated_at` are
explicitly rejected with `400`, including when the value is `null`.
`Opportunity.customer` is immutable through ordinary PATCH. PUT and DELETE
remain disabled and return `405`.

### Active Presales options

`GET /api/users/presales-options/` is available only to Sales users. It returns
active users with business role `presales`, ordered by `username`, then `id`,
and exposes only `id`, `username`, `first_name`, and `last_name`.

## Out of scope

The following remain deliberately unimplemented: AI, RAG, LLM integrations,
pgvector, LangGraph, frontend code, background jobs, Redis, Celery, Kafka,
Docker, microservices, complex or runtime-configurable RBAC, ownership
transfer, customer merge, and speculative service/selector layers. There are
no editable Customer or Opportunity Django Admin screens; Django Admin is
still for User management only. PostgreSQL `pg_trgm`/GIN search optimization
is future work, not an implemented index. JWT rotation, JWT blacklisting,
logout, and related token lifecycle features also remain out of scope.
