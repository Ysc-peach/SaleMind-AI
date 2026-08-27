# SalesMind AI Phase Two Sales Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Customer and Opportunity backend resources with minimum role isolation, safe collision search, explicit write protection, pagination, and active Presales options.

**Architecture:** Add one `apps.sales` domain app with separate Customer and Opportunity models. Expose only required routes through restricted DRF GenericViewSets; role-filtered querysets are the primary object-security boundary and resource permissions are defense in depth.

**Tech Stack:** Python 3.12.14, Django 5.2.17, Django REST Framework 3.18.0, PostgreSQL 17, pytest 9.1.1, pytest-django 4.14.0.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-two-sales-domain-design.md`

## Global Constraints

- Keep all Python names, API fields, URLs, and enum storage values in English; Chinese is display-label text only.
- Use `settings.AUTH_USER_MODEL` for every User foreign key.
- Customer is shared master data and has no sales_owner in V1.
- Customer.created_by is a required PROTECT audit field and must not appear in Customer search/detail responses.
- Opportunity.customer, sales_owner, presales_owner, and created_by use PROTECT; presales_owner remains nullable/blank.
- Admin Opportunity access is read-only; Presales Opportunity access is read-only; only Sales can create/PATCH their own Opportunities.
- Business API permissions use User.role only and never is_staff/is_superuser.
- Task 4 must not include UpdateModelMixin or PATCH; Task 5 adds the complete update surface.
- Customer search and Opportunity list use page-number pagination with default page size 20.
- Opportunity list ordering is always `-updated_at, -id`, including paginated queries.
- Customer name search uses `name__icontains` without a normal B-Tree db_index; future optimization is pg_trgm + GIN.
- Prefetch, `.only()`, and `to_attr` are performance optimizations, not security boundaries.
- Create rejects sales_owner/created_by/stage/status with 400; PATCH rejects customer/sales_owner/created_by/created_at/updated_at with 400.
- PUT/DELETE Opportunity and PATCH/PUT/DELETE Customer return 405 and have API tests.
- No editable Customer/Opportunity Django Admin, new dependency, AI, RAG, pgvector, frontend, Redis, Celery, complex RBAC, transfer endpoint, or customer merge.

---

### Task 1: Customer and Opportunity models

**Files:**
- Create: `apps/sales/__init__.py`
- Create: `apps/sales/apps.py`
- Create: `apps/sales/models.py`
- Create: `apps/sales/migrations/__init__.py`
- Create: `apps/sales/migrations/0001_initial.py`
- Create: `apps/sales/tests/__init__.py`
- Create: `apps/sales/tests/conftest.py`
- Create: `apps/sales/tests/test_models.py`
- Modify: `config/settings/base.py`

**Interfaces:**
- Produces: `Customer`, `Opportunity`, `OpportunityStage`, `OpportunityStatus`.
- Produces related names: `Customer.opportunities`, User `created_customers`, `sales_opportunities`, `presales_opportunities`, and `created_opportunities`.

- [ ] Write model tests before models exist: duplicate Customer names, Opportunity defaults, nullable presales_owner, one-to-many relationship, database stage/status constraints, and PROTECT behavior for customer and every User relation.
- [ ] Run `python -m pytest apps/sales/tests/test_models.py -q`; verify RED is caused by missing sales models.
- [ ] Implement Customer fields: name(200), industry(100 blank/default empty), company_size(100 blank/default empty), basic_info(TextField blank/default empty), required created_by(PROTECT), and timestamps. Do not add db_index/unique to name.
- [ ] Implement Opportunity fields exactly from the spec. Use TextChoices with English storage/Chinese labels, defaults initial_contact/active, nullable PROTECT presales_owner, CheckConstraints for stage/status, and composite indexes `(sales_owner,status)`, `(presales_owner,status)`, `(customer,status)`.
- [ ] Add `apps.sales` to INSTALLED_APPS, generate `sales.0001_initial`, inspect `sqlmigrate`, and confirm it creates only new tables/constraints/indexes with swappable User dependency and no data migration.
- [ ] Run focused tests, `makemigrations --check --dry-run`, and `manage.py check` until green.
- [ ] Run the full suite once and commit `feat: add customer and opportunity models`.

### Task 2: Active Presales options API

**Files:**
- Create: `apps/accounts/api/permissions.py`
- Create: `apps/accounts/api/user_urls.py`
- Create: `apps/accounts/tests/test_presales_options_api.py`
- Modify: `apps/accounts/api/serializers.py`
- Modify: `apps/accounts/api/views.py`
- Modify: `config/urls.py`

**Interfaces:**
- Produces: `GET /api/users/presales-options/`, Sales-only, returning a JSON list of `{id, username, first_name, last_name}`.

- [ ] Write API tests first: unauthenticated 401; Sales 200; Admin/Presales 403; include only active role=presales users; exclude inactive and other roles; exact fields; username/id ordering.
- [ ] Run the focused test and verify RED because the route does not exist.
- [ ] Implement `IsSales`, `PresalesOptionSerializer`, `PresalesOptionListView`, and the `/api/users/` URL include. Query only active Presales and order by username/id. Do not expose email or permission flags and do not build user CRUD.
- [ ] Run focused and full tests, then commit `feat: add active presales options API`.

### Task 3: Customer create, retrieve, and safe search

**Files:**
- Create: `apps/sales/api/__init__.py`
- Create: `apps/sales/api/pagination.py`
- Create: `apps/sales/api/permissions.py`
- Create: `apps/sales/api/serializers.py`
- Create: `apps/sales/api/urls.py`
- Create: `apps/sales/api/views.py`
- Create: `apps/sales/tests/test_customer_api.py`
- Modify: `config/urls.py`

**Interfaces:**
- Produces `DefaultPageNumberPagination` with `page_size=20`.
- Produces Customer endpoints: POST `/api/customers/`, GET `/api/customers/{id}/`, GET `/api/customers/search/?q=`.
- Produces safe opportunity summary fields exactly: id, project_name, stage, status, is_mine, is_followed_by_other_sales.

- [ ] Write Customer API tests first: Sales/Admin create, Presales forbidden, duplicate name allowed, created_by stored but absent from search/detail, q required, pagination 20, active summary included, won/lost/closed excluded, own/other flags, exact summary whitelist, sensitive values absent, and Customer PATCH/PUT/DELETE 405.
- [ ] Run focused tests and verify RED because routes/serializers do not exist.
- [ ] Implement `CustomerPermission`, explicit create/search/detail serializers, and CustomerViewSet from CreateModelMixin + RetrieveModelMixin + GenericViewSet with `http_method_names=["get","post","head","options"]`.
- [ ] Implement `name__icontains` search ordered by name/id. Prefetch active Opportunities with `.only(...)` and `to_attr="active_opportunity_summaries"`; security must come from the summary serializer whitelist, not deferred fields.
- [ ] Apply page-size-20 pagination to search. Save created_by=request.user but never serialize it in ordinary Customer APIs.
- [ ] Run focused and full tests, then commit `feat: add customer create and safe search APIs`.

### Task 4: Opportunity list, create, and retrieve only

**Files:**
- Create: `apps/sales/tests/test_opportunity_api.py`
- Modify: `apps/sales/api/permissions.py`
- Modify: `apps/sales/api/serializers.py`
- Modify: `apps/sales/api/views.py`
- Modify: `apps/sales/api/urls.py`

**Interfaces:**
- Produces Opportunity list/create/retrieve routes with no PATCH implementation.
- Produces `RejectForbiddenFieldsMixin`, list/detail/create serializers, role-filtered queryset, stable pagination, and active Presales assignment validation.

- [ ] Write tests first: Sales create with automatic sales_owner/created_by and default initial_contact/active; each forbidden create field returns 400 and creates no record; invalid/inactive presales_owner returns 400; Admin/Presales create 403; Sales own list/detail isolation; assigned Presales visibility; Admin sees all; technical flags do not bypass roles; 20-item pagination ordered by `-updated_at,-id`; PATCH/PUT/DELETE Opportunity all 405 at this commit.
- [ ] Run focused tests and verify RED because Opportunity routes do not exist.
- [ ] Implement list/detail/create serializers. Explicitly reject create keys sales_owner, created_by, stage, status in `to_internal_value`; do not silently ignore them. Validate presales_owner through an active role=presales queryset.
- [ ] Implement OpportunityPermission and OpportunityViewSet using only ListModelMixin + CreateModelMixin + RetrieveModelMixin + GenericViewSet. Do not import or inherit UpdateModelMixin. Set `http_method_names=["get","post","head","options"]`.
- [ ] Filter queryset by role before retrieval, select related objects, and order by `-updated_at,-id`. Apply page-size-20 pagination. In perform_create force both ownership fields to request.user.
- [ ] Run focused and full tests, verify PATCH/PUT/DELETE are 405, then commit `feat: add opportunity create and read APIs`.

### Task 5: Opportunity PATCH and explicit update protection

**Files:**
- Modify: `apps/sales/api/permissions.py`
- Modify: `apps/sales/api/serializers.py`
- Modify: `apps/sales/api/views.py`
- Modify: `apps/sales/tests/test_opportunity_api.py`

**Interfaces:**
- Adds PATCH only by adding UpdateModelMixin and `patch` to http_method_names.
- Produces `OpportunityUpdateSerializer`; writable fields are project_name, presales_owner, raw_requirement, budget, stage, status, expected_launch_date.

- [ ] Write update tests first: Sales can PATCH own allowed fields; each of customer/sales_owner/created_by/created_at/updated_at returns 400 and leaves data unchanged; inactive/non-Presales assignment returns 400; Sales B gets 404; Admin/Presales get 403; PUT/DELETE remain 405.
- [ ] Run focused update tests and verify RED because PATCH is still 405.
- [ ] Add UpdateModelMixin, PATCH-only method support, update serializer selection, explicit forbidden-key rejection, and update action permission for owning Sales only. Customer remains immutable.
- [ ] Run focused and full tests, then commit `feat: protect opportunity updates`.

### Task 6: Documentation, complete verification, and review readiness

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents delivered models, APIs, pagination, role matrix, safe search, explicit forbidden fields, 405 methods, basic_info data policy, closed meaning, and deliberate exclusions.

- [ ] Update README without describing out-of-scope work as implemented.
- [ ] Apply migrations and run `python -m pytest -q`; require all tests pass with zero warnings.
- [ ] Run `manage.py makemigrations --check --dry-run`, `manage.py migrate`, `manage.py check`, production `check --deploy`, `pip check`, and `git diff --check`.
- [ ] Confirm no editable sales Django Admin registration, no new dependency, Customer APIs omit created_by, Opportunity stable pagination remains intact, and Task 4 history introduced no partial PATCH surface.
- [ ] Commit `docs: document phase two sales APIs`.
- [ ] Generate a whole-branch review package and run final independent review; fix all load-bearing findings in one fix wave and re-review that wave once.
