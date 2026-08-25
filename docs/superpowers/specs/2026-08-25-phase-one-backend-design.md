# SalesMind AI Phase One Backend Design

## Objective

Initialize the SalesMind AI Django backend and deliver only the first-phase identity foundation: a custom user model, three fixed business roles, Django Admin user management, JWT login/refresh/current-user endpoints, and automated tests against PostgreSQL.

## Scope

Included:

- Django and Django REST Framework project initialization.
- PostgreSQL-only database configuration from development onward.
- Custom `accounts.User` model based on `AbstractUser`.
- Required, unique email and explicit business role.
- Django Admin user creation, editing, activation, and deactivation.
- JWT login, refresh, and current-user endpoints.
- Model, API, authentication, deactivation, and Admin permission-boundary tests.

Excluded:

- Customer and Opportunity models or APIs.
- AI, RAG, pgvector, LangGraph, and LLM integrations.
- Redis, Celery, Kafka, Docker, or microservices.
- Server-side JWT blacklist, refresh rotation, or logout endpoint.
- Runtime-configurable roles, object-level permission libraries, and speculative service or selector layers.

## Runtime and Dependency Policy

- Python uses the latest stable Python 3.12 patch release available at implementation time.
- Django uses the latest stable Django 5.2 LTS patch release available at implementation time.
- Django REST Framework is fixed to an explicitly verified stable release. Prefer 3.17.2; use 3.18.0 only if official metadata and compatibility checks confirm it exists and supports Django 5.2 and Simple JWT 5.5.1.
- `djangorestframework-simplejwt` is fixed at 5.5.1.
- All direct dependencies are pinned in requirements files.
- Development and tests use PostgreSQL. There is no SQLite fallback.

## Project Structure

The repository is a modular Django monolith:

- `config` owns settings, root URLs, ASGI, and WSGI integration.
- `apps.accounts` owns identity, roles, Admin integration, and authentication API endpoints.
- Settings are split into `base`, `local`, `production`, and `test` modules. Each module must have a concrete purpose; no additional configuration layers are introduced.
- API code is kept under `apps/accounts/api` so model and Admin concerns remain separate without introducing unused service abstractions.
- Tests live beside the accounts app and use pytest, pytest-django, and DRF's API client.

## User and Role Model

`accounts.User` subclasses `django.contrib.auth.models.AbstractUser` and retains username/password authentication.

The inherited `email` field is overridden so it is required and unique. `username` remains the `USERNAME_FIELD`.

`role` is a required `CharField` backed by `TextChoices` with exactly these stored values:

- `admin`
- `sales`
- `presales`

Role must be supplied explicitly on every supported user-creation path. There is no default role. A custom manager provides clear validation for programmatic creation, and the database migration adds a check constraint for the three allowed stored values.

The default integer primary key is retained. Future models reference users through `settings.AUTH_USER_MODEL` rather than importing the concrete model.

## Privilege Boundaries

Business role and Django administration privileges are independent:

- `role=admin` is a SalesMind business role only.
- `is_staff` gates access to Django Admin.
- `is_superuser` bypasses Django model permission checks and is reserved for technical administration.

No signal, manager rule, Admin form behavior, or serializer automatically maps role to `is_staff` or `is_superuser`. A business Admin without `is_staff` cannot access Django Admin. A Sales or Presales user does not gain Django Admin access from role alone.

## Authentication

DRF uses Simple JWT's database-backed `JWTAuthentication`. The stateless token-user authentication backend is not used because current database state, especially `is_active` and role changes, must be observed on each authenticated request.

JWT settings:

- Access token lifetime: 15 minutes.
- Refresh token lifetime: 7 days.
- Refresh rotation: disabled.
- Blacklist application: not installed.
- Last-login updates from token acquisition: disabled.
- Header type: `Bearer`.
- JWT signing key: supplied independently from Django's `SECRET_KEY`.

Role is not copied into token claims and is never treated as an authorization source from a token. The live database user is authoritative.

Inactive users must be rejected by login, authenticated API requests using previously issued access tokens, and refresh requests using previously issued refresh tokens. These behaviors are regression-tested against the fixed Simple JWT version.

## API Contract

### `POST /api/auth/login/`

Accepts `username` and `password`. Returns `access` and `refresh` on success. Invalid credentials and inactive accounts return a generic HTTP 401 response without disclosing which condition occurred.

### `POST /api/auth/refresh/`

Accepts `refresh`. Returns a new `access` token only. Invalid, expired, or inactive-user refresh tokens return HTTP 401.

### `GET /api/auth/me/`

Requires `Authorization: Bearer <access>`. Returns only `id`, `username`, `email`, `first_name`, `last_name`, and `role` for the current live user.

DRF and Simple JWT's standard validation/error shapes are retained. No custom response envelope or unused token verification endpoint is added.

## Permission Foundation

DRF's global default permission is `IsAuthenticated`. Login and refresh explicitly use `AllowAny`; the current-user endpoint requires authentication.

No role-specific API permission class is introduced before a real business endpoint needs one. Future business apps will own their permission classes, queryset scoping, and object checks. Django Groups and Permissions remain available but are not preconfigured as a speculative role matrix.

## Settings and Secrets

The project reads configuration from environment variables. At minimum:

- `DJANGO_SECRET_KEY`
- `JWT_SIGNING_KEY`
- `DATABASE_URL`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SETTINGS_MODULE`

`django-environ` handles typed environment parsing and database URLs. A committed `.env.example` documents required values; `.env` is ignored. Production settings fail closed when required secrets or hosts are absent. Local and test settings do not silently choose SQLite.

## Django Admin

The custom user is registered using an extension of Django's `UserAdmin` with custom creation and change forms. Role and email are available on creation and editing. Passwords are always processed by Django's password forms.

The user list exposes username, email, name, role, active/staff state, and creation date; supports role and status filters; and supports username, email, and name search. `is_active` provides the first-phase enable/disable capability.

Django Admin continues to use Django session authentication, independent of the JWT API.

## Testing

Tests use pytest, pytest-django, DRF's API client, and PostgreSQL. Required coverage includes:

- Explicit and valid role creation, invalid role rejection, required/unique email, and password hashing.
- Correct ordinary-user and superuser manager behavior without coupling role and privilege flags.
- Successful login, wrong-password rejection, unknown-user rejection, and inactive-user rejection.
- Unauthenticated `/me/` rejection and correct authenticated current-user data.
- Successful refresh and invalid-token rejection.
- Rejection of previously issued access and refresh tokens after user deactivation.
- Live role changes reflected by `/me/`.
- Sales, Presales, and business Admin roles do not independently grant Django Admin access.
- Technical superuser access to user administration.

Tests assert consumer-visible behavior, not framework internals or exact source text.

## Delivery and Verification

Implementation proceeds in small commits. Before phase completion:

- The full PostgreSQL-backed test suite passes without warnings.
- `python manage.py check` passes.
- `python manage.py makemigrations --check --dry-run` reports no pending migrations.
- Production settings receive a deployment-oriented system check with explicit test environment values.
- The final branch receives an independent whole-change code review.

No second-phase business module is started until this phase passes user code review.
