# SalesMind AI Phase One Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-phase SalesMind AI Django backend with a PostgreSQL-only configuration, custom user and role model, Django Admin management, JWT login/refresh/current-user APIs, and regression tests.

**Architecture:** Use a modular Django monolith with project configuration in `config` and identity/authentication in `apps.accounts`. Authentication delegates token mechanics to Simple JWT while database-backed `JWTAuthentication` keeps `is_active` and role state live. Configuration is environment-driven and intentionally limited to base, local, production, and test settings.

**Tech Stack:** Python 3.12.14, Django 5.2.17, Django REST Framework 3.18.0, Simple JWT 5.5.1, PostgreSQL with psycopg 3.3.4, pytest 9.1.1, pytest-django 4.14.0.

**Spec:** `docs/superpowers/specs/2026-08-25-phase-one-backend-design.md`

## Global Constraints

- Implement only project initialization, User/Role, Django Admin, JWT login/refresh/me, and corresponding tests.
- Use Python 3.12.14 and pin every direct dependency to an exact version.
- Use Django 5.2.17, Django REST Framework 3.18.0, and djangorestframework-simplejwt 5.5.1.
- Use PostgreSQL from development onward; no SQLite fallback is permitted.
- `accounts.User` subclasses `AbstractUser`, keeps username/password login, requires a unique email, and requires an explicit TextChoices role from `admin`, `sales`, or `presales`.
- Business role is completely independent of `is_staff` and `is_superuser`.
- JWT access lifetime is 15 minutes; refresh lifetime is 7 days; refresh rotation and blacklist are disabled.
- DRF defaults to `IsAuthenticated`; only login and refresh are public.
- Do not add Redis, Celery, Docker, AI, RAG, Customer, Opportunity, speculative service/selector layers, or unrelated infrastructure.
- Store Django and JWT signing secrets separately in environment variables.
- Use test-first red/green cycles for behavioral code and commit each task independently.

---

### Task 1: Repository and Django Configuration Foundation

**Files:**

- Create: `requirements/base.txt`
- Create: `requirements/dev.txt`
- Create: `.python-version`
- Create: `.env.example`
- Create: `manage.py`
- Create: `config/__init__.py`
- Create: `config/urls.py`
- Create: `config/asgi.py`
- Create: `config/wsgi.py`
- Create: `config/settings/__init__.py`
- Create: `config/settings/base.py`
- Create: `config/settings/local.py`
- Create: `config/settings/production.py`
- Create: `config/settings/test.py`
- Create: `apps/__init__.py`
- Create: `apps/accounts/__init__.py`
- Create: `apps/accounts/apps.py`
- Create: `apps/accounts/migrations/__init__.py`
- Create: `pytest.ini`
- Create: `README.md`

**Interfaces:**

- Produces: Django settings selected through `DJANGO_SETTINGS_MODULE`; installed app label `accounts`; PostgreSQL database configuration from `DATABASE_URL`; dependency environment used by later tasks.
- Consumes: No application interfaces.

- [ ] **Step 1: Declare exact dependencies**

Create `requirements/base.txt` with:

```text
Django==5.2.17
djangorestframework==3.18.0
djangorestframework-simplejwt==5.5.1
django-environ==0.14.0
psycopg[binary]==3.3.4
```

Create `requirements/dev.txt` with:

```text
-r base.txt
pytest==9.1.1
pytest-django==4.14.0
```

Create `.python-version` containing `3.12.14`.

- [ ] **Step 2: Create the virtual environment and install dependencies**

Use a Python 3.12.14 interpreter and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Expected: dependency installation and `pip check` both exit successfully.

- [ ] **Step 3: Generate the Django skeleton and settings modules**

Create the standard `manage.py`, ASGI, WSGI, and root URL modules. `manage.py` defaults to `config.settings.local`; ASGI and WSGI default to `config.settings.production` while allowing an explicit environment value to win.

`base.py` must define:

```python
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
DATABASES = {"default": env.db("DATABASE_URL")}
AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": env("JWT_SIGNING_KEY"),
}
```

Also include the standard Django installed apps/middleware/templates/password validators, `rest_framework`, and `apps.accounts`. Set `LANGUAGE_CODE = "en-us"`, `TIME_ZONE = "Asia/Shanghai"`, `USE_I18N = True`, `USE_TZ = True`, `STATIC_URL = "static/"`, and `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"`.

`local.py` reads `BASE_DIR / ".env"` without overriding real environment variables and sets `DEBUG = True`. `production.py` keeps `DEBUG = False`, requires allowed hosts, configures environment-driven CSRF trusted origins, secure cookies, HTTPS redirect, HSTS, and proxy SSL header. `test.py` uses deterministic non-production test secrets only when test environment variables are absent and continues to require `DATABASE_URL`.

- [ ] **Step 4: Document environment variables**

Create `.env.example` with non-secret placeholders for:

```text
DJANGO_SETTINGS_MODULE=config.settings.local
DJANGO_SECRET_KEY=replace-with-a-long-random-development-key
JWT_SIGNING_KEY=replace-with-a-different-long-random-development-key
DATABASE_URL=postgresql://salesmind:salesmind@127.0.0.1:5432/salesmind
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000
```

README instructions must explain Python 3.12.14, PostgreSQL database creation, copying `.env.example` to `.env`, dependency installation, migrations, superuser creation, server startup, and tests. Do not document Docker or second-phase features.

- [ ] **Step 5: Configure pytest and root URLs**

Create `pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.test
python_files = tests.py test_*.py *_tests.py
addopts = -ra --strict-markers
```

Root URLs expose Django Admin at `/admin/` and reserve `/api/auth/` for the accounts API included in Task 3.

- [ ] **Step 6: Verify the configuration foundation**

With PostgreSQL environment values set, run:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe -m pip check
```

Expected: both commands exit successfully without warnings.

- [ ] **Step 7: Commit the foundation**

```powershell
git add requirements .python-version .env.example manage.py config apps pytest.ini README.md
git commit -m "chore: initialize Django backend foundation"
```

---

### Task 2: Custom User, Explicit Roles, and Django Admin

**Files:**

- Create: `apps/accounts/managers.py`
- Create: `apps/accounts/models.py`
- Create: `apps/accounts/forms.py`
- Create: `apps/accounts/admin.py`
- Create: `apps/accounts/migrations/0001_initial.py`
- Create: `apps/accounts/tests/__init__.py`
- Create: `apps/accounts/tests/conftest.py`
- Create: `apps/accounts/tests/test_models.py`
- Create: `apps/accounts/tests/test_admin.py`

**Interfaces:**

- Consumes: `AUTH_USER_MODEL = "accounts.User"` and the `accounts` app registered by Task 1.
- Produces: `UserRole`, `UserManager.create_user(username, email, role, password, **extra_fields)`, `UserManager.create_superuser(...)`, `User`, initial migration, and registered `UserAdmin`.

- [ ] **Step 1: Write failing model tests**

Tests must demonstrate:

```python
def test_create_user_requires_email(): ...
def test_create_user_requires_role(): ...
def test_create_user_hashes_password(): ...
def test_email_is_unique(): ...
def test_database_rejects_invalid_role(): ...
def test_business_admin_role_does_not_grant_django_admin_flags(): ...
def test_superuser_flags_do_not_rewrite_business_role(): ...
```

Use real database writes. For missing email/role expect a clear `ValueError`; for duplicate email and invalid role expect `IntegrityError` inside `transaction.atomic()`.

- [ ] **Step 2: Run model tests to verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_models.py -q
```

Expected: collection/import failures because `accounts.User` and `UserRole` are not implemented.

- [ ] **Step 3: Implement the minimal manager and model**

`UserRole` is a top-level `models.TextChoices`:

```python
class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    SALES = "sales", "Sales"
    PRESALES = "presales", "Presales"
```

`UserManager` subclasses Django's manager, rejects blank email and role, normalizes email with `normalize_email`, delegates password hashing to Django, and keeps the ordinary/superuser flags independent from role. `create_superuser` enforces `is_staff=True` and `is_superuser=True` but does not force `role=admin`.

`User` subclasses `AbstractUser`, overrides email with `models.EmailField(unique=True)`, defines required role without a default, assigns the custom manager, and adds a named check constraint limiting role to `UserRole.values`.

- [ ] **Step 4: Generate and inspect the initial migration**

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations accounts
.\.venv\Scripts\python.exe manage.py migrate
```

Expected: `0001_initial.py` creates the swappable user model and role check constraint before any dependent application migrations.

- [ ] **Step 5: Run model tests to verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_models.py -q
```

Expected: all model tests pass with no warnings.

- [ ] **Step 6: Write failing Admin boundary tests**

Tests must demonstrate that a user with `role=admin` and `is_staff=False` cannot access `/admin/`, a Sales or Presales role does not set staff/superuser flags, and a technical superuser can open the custom user changelist.

- [ ] **Step 7: Run Admin tests to verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_admin.py -q
```

Expected: failures because the custom UserAdmin/forms are not registered.

- [ ] **Step 8: Implement Admin forms and registration**

Subclass Django's `UserCreationForm` and `UserChangeForm`, set `model = User`, and include username, email, role, and standard name fields as appropriate. Extend `django.contrib.auth.admin.UserAdmin` with:

```python
list_display = (
    "username", "email", "first_name", "last_name",
    "role", "is_active", "is_staff", "date_joined",
)
list_filter = ("role", "is_active", "is_staff", "is_superuser")
search_fields = ("username", "email", "first_name", "last_name")
ordering = ("username",)
```

Add role to both change and add fieldsets while preserving Django's permission and password handling.

- [ ] **Step 9: Verify User/Admin behavior and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_models.py apps\accounts\tests\test_admin.py -q
.\.venv\Scripts\python.exe manage.py check
git add apps\accounts
git commit -m "feat: add custom user roles and admin management"
```

Expected: all focused tests and checks pass without warnings.

---

### Task 3: JWT Login, Refresh, and Current User API

**Files:**

- Create: `apps/accounts/api/__init__.py`
- Create: `apps/accounts/api/serializers.py`
- Create: `apps/accounts/api/views.py`
- Create: `apps/accounts/api/urls.py`
- Create: `apps/accounts/tests/test_auth_api.py`
- Modify: `config/urls.py`

**Interfaces:**

- Consumes: `accounts.User`, DRF default authentication/permission settings, and Simple JWT settings.
- Produces: URL names `auth-login`, `auth-refresh`, and `auth-me`; `CurrentUserSerializer`; `CurrentUserView`.

- [ ] **Step 1: Write failing authentication API tests**

Tests must cover:

```python
def test_login_returns_access_and_refresh_for_valid_credentials(): ...
def test_login_rejects_wrong_password(): ...
def test_login_rejects_unknown_username(): ...
def test_login_rejects_inactive_user(): ...
def test_me_rejects_unauthenticated_request(): ...
def test_me_returns_current_user_and_role(): ...
def test_refresh_returns_new_access_token(): ...
def test_refresh_rejects_malformed_token(): ...
def test_refresh_token_cannot_authenticate_me(): ...
```

Assert HTTP status codes, response keys, and consumer-visible payloads. Do not assert Simple JWT private implementation details.

- [ ] **Step 2: Run API tests to verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_auth_api.py -q
```

Expected: URL reversal or 404 failures because the auth routes are not implemented.

- [ ] **Step 3: Implement the three endpoints**

Map Simple JWT's `TokenObtainPairView` and `TokenRefreshView` under the exact required paths with `AllowAny`. Implement a read-only `CurrentUserSerializer` exposing exactly:

```python
fields = ("id", "username", "email", "first_name", "last_name", "role")
```

Implement `CurrentUserView` as a focused DRF retrieve-style API view that serializes `request.user` and requires `IsAuthenticated`. Include `apps.accounts.api.urls` at `/api/auth/` in `config.urls`.

- [ ] **Step 4: Run API tests to verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_auth_api.py -q
```

Expected: all authentication API tests pass without warnings.

- [ ] **Step 5: Add deactivation and live-role regression tests**

Write tests that obtain tokens while a user is active, then update the database user:

```python
def test_existing_access_token_is_rejected_after_user_deactivation(): ...
def test_existing_refresh_token_is_rejected_after_user_deactivation(): ...
def test_me_returns_updated_database_role_for_existing_access_token(): ...
```

The refresh test must require HTTP 401 rather than merely verifying that an issued access token later fails.

- [ ] **Step 6: Run regressions to verify RED or characterize upstream behavior**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_auth_api.py -q
```

Expected: tests either fail on the missing requirement or pass as a narrow characterization of Simple JWT 5.5.1. If refresh incorrectly succeeds for an inactive user, add the smallest custom refresh serializer/view that performs a live user lookup and applies the configured user authentication rule; do not reimplement token parsing.

- [ ] **Step 7: Verify JWT compatibility and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest apps\accounts\tests\test_auth_api.py -q
.\.venv\Scripts\python.exe manage.py check
git add apps\accounts\api apps\accounts\tests\test_auth_api.py config\urls.py
git commit -m "feat: add JWT authentication endpoints"
```

Expected: Simple JWT 5.5.1 works with DRF 3.18.0 for obtain, refresh, database-backed authentication, inactive users, and current-user serialization.

---

### Task 4: Full PostgreSQL Verification and Delivery Documentation

**Files:**

- Modify: `README.md`
- Modify only if a discovered defect requires it: files created in Tasks 1-3 with a covering regression test.

**Interfaces:**

- Consumes: all phase-one interfaces.
- Produces: verified repository state and complete operator/developer instructions.

- [ ] **Step 1: Run the complete test suite on PostgreSQL**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 2: Verify migrations and Django system checks**

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
```

Expected: no pending migrations and no system-check issues.

- [ ] **Step 3: Verify production settings**

Set explicit non-production verification values for every required environment variable, select `config.settings.production`, and run:

```powershell
.\.venv\Scripts\python.exe manage.py check --deploy
```

Expected: no actionable deployment warnings for settings controlled by the project. Any host-level TLS termination requirement must be documented rather than bypassed with insecure defaults.

- [ ] **Step 4: Verify installed versions and dependency integrity**

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip freeze
```

Expected: Python 3.12.14, all exact direct dependency versions from this plan, and no broken requirements.

- [ ] **Step 5: Finalize README and commit**

README must contain the exact API list and request shapes, role/technical-privilege distinction, environment setup, PostgreSQL commands, tests/checks, and an explicit list of excluded next-phase features.

```powershell
git add README.md
git commit -m "docs: document phase one backend workflow"
```

- [ ] **Step 6: Confirm clean repository state**

```powershell
git status --short
git log --oneline --decorate
```

Expected: no uncommitted project changes and a small, task-oriented commit history.
