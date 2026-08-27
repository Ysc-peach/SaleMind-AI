# SalesMind AI Phase Two Sales Domain Design

## Scope

Phase two adds the Customer and Opportunity backend skeleton, minimum role-based
data isolation, safe customer collision search, and a minimal active Presales
option endpoint. It does not add AI, RAG, pgvector, frontend code, background
jobs, complex RBAC, ownership transfer, customer merge, or editable Django
Admin screens for these models.

## Domain model

`Customer` is shared company master data. It has no owner in V1. Its
`created_by` field records the original creator for database audit only and is
not exposed by ordinary Customer APIs. Duplicate names are allowed.

`Opportunity` represents one sales project for a Customer. Its `sales_owner`
and `created_by` are set to the authenticated Sales user at creation time.
`presales_owner` is optional. Users are deactivated instead of deleted, so all
User audit/ownership foreign keys, including `presales_owner`, use `PROTECT`.
The Customer foreign key also uses `PROTECT`.

Opportunity stage values are `initial_contact`, `requirement_analysis`,
`presales_support`, `solution`, `quotation`, and `negotiation`. Status values
are `active`, `won`, `lost`, and `closed`; `closed` means manually terminated
or archived, distinct from won/lost. Stored values and API fields remain
English; labels are Chinese.

## API and permissions

Customer endpoints are create, retrieve, and `search/?q=`. Admin and Sales may
use them; Presales may not. Customer PATCH, PUT, DELETE, and ordinary list are
not exposed. Search uses `name__icontains`, paginates at 20 customers per page,
and intentionally adds no B-Tree name index. A future optimization may use
PostgreSQL `pg_trgm` with GIN.

Customer search/detail expose shared company fields and a whitelisted summary
of active Opportunities only: id, project_name, stage, status, is_mine, and
is_followed_by_other_sales. They never expose Customer.created_by or sensitive
Opportunity fields. Prefetch with `.only()` and `to_attr` is a performance
optimization, not a security boundary. Security comes from role-filtered
querysets and dedicated serializer field whitelists.

Opportunity endpoints are list, create, retrieve, and PATCH. Task 4 implements
only list/create/retrieve and must not include `UpdateModelMixin` or PATCH;
Task 5 adds the update interface atomically. PUT and DELETE remain disabled and
return 405. Opportunity lists paginate at 20 and order by `-updated_at, -id`.

Admin can list/retrieve all Opportunities but cannot create or update them.
Sales can create and can list/retrieve/update only their own Opportunities.
Presales can list/retrieve only Opportunities assigned to them and cannot
create or update. Business API checks use `User.role` only, never Django staff
or superuser flags. Objects outside a role-filtered queryset return 404.

Create payloads containing sales_owner, created_by, stage, or status return
400. PATCH payloads containing customer, sales_owner, created_by, created_at,
or updated_at return 400. These fields are explicitly rejected, not silently
ignored. Opportunity.customer cannot be changed by ordinary PATCH.

The active Presales option endpoint is `GET /api/users/presales-options/`, is
available to Sales users, returns only active users with role=presales, orders
by username/id, and exposes only id, username, first_name, and last_name.

## Data handling decisions

Customer.basic_info may contain only shared non-sensitive company information.
Opportunity.raw_requirement may be blank. Presales assignment accepts only an
active user with role=presales. No editable Customer/Opportunity Django Admin
is provided in this phase so API invariants cannot be bypassed there.

## Verification

Tests cover model defaults and deletion protection; Customer creation, search,
pagination, safe summaries, non-active exclusion, and 405 methods; Opportunity
automatic ownership, explicit forbidden-field errors, per-role list/detail
isolation, stable pagination, assignment validation, update rules, and 405
methods; the Presales option filter; and separation between business roles and
Django technical privileges. Final verification runs the full PostgreSQL test
suite, migration drift check, migrations, Django system/deployment checks,
dependency check, diff check, and independent code review.
