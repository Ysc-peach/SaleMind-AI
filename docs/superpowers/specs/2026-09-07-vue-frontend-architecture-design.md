# Phase 7 Vue 3 Frontend Architecture Design

## Goal

### Approved Phase 7a scope — 2026-09-08

Phase 7a uses the existing REST business path: generate -> DRAFT -> inspect content/provenance -> explicit submit -> PENDING_REVIEW -> Presales decision. The Phase 6a graph automatically submits after generation, so it is deliberately not the first UI path. Existing LangGraph remains unchanged.

Only login, Opportunity list/workspace, analysis, Solution detail/provenance and direct review actions are in scope. Dashboard analytics, Customer CRUD, Knowledge management, reviewer inbox and LangGraph HTTP adapters below are future reconnaissance proposals, not Phase 7a implementation tasks. Presales reaches review through an assigned Opportunity or an authorized Solution deep link. No backend contract changes are authorized.

Build a professional Vue 3 single-page application around the current SalesMind Django/DRF contracts. The first milestone should demonstrate one real business path from sign-in through Opportunity context, Requirement Analysis, AI Solution generation, submission, and technical review. The frontend presents business language; Django services and PostgreSQL remain the authorization and business-state authorities.

This document describes the current backend surface and the intended frontend. No Vue production code exists yet.

## Sources and verification

The inventory was derived from the current URL declarations, views, serializers, permissions, models, migrations, API tests, and Phase 6a workflow services. GitNexus was used to locate the principal API, review, and orchestration symbols and to trace `SolutionDraftDetailViewSet.submit_review` into `submit_solution_draft_for_review`; source and tests were then used to verify the contracts.

Primary repository sources:

- `config/urls.py`
- `apps/accounts/api/`
- `apps/sales/api/`
- `apps/sales/services/solution_review.py`
- `apps/sales/services/solution_review_workflow.py`
- `apps/sales/services/solution_workflow_checkpoint.py`
- `apps/knowledge/api/` and `apps/knowledge/admin.py`
- `apps/rag/api/`
- the corresponding API tests under `apps/*/tests/`

GitNexus confirmed that the durable LangGraph workflow is currently consumed by tests and service code, but no DRF URL invokes `build_solution_review_graph`. That missing HTTP adapter is an explicit backend gap, not a frontend contract.

## Product and UX principles

- Use business terms: do not expose Graph nodes, checkpoints, thread IDs, grounding internals, or provider names as primary UI concepts.
- Make Opportunity Detail the shared Sales/Presales workspace.
- Distinguish customer-information returns from technical revisions visually and behaviorally.
- Show why an AI-produced statement is trustworthy without dumping all internal grounding data into the default view.
- Frontend role checks improve usability only. Every action remains authorized by the backend.
- Prefer a complete vertical workflow over a collection of disconnected page shells.
- Optimize for a clear interview/demo narrative: customer context -> AI analysis -> grounded Solution -> human technical decision.

## Current API inventory

All paths below are mounted under `/api/`. Collection endpoints use page-number pagination with a default page size of 20 where noted.

### Authentication and user context

| Method | Path | Request | Frontend-relevant response | Access and important statuses |
| --- | --- | --- | --- | --- |
| POST | `/auth/login/` | `username`, `password` | `access`, `refresh` | Public; `200`, invalid/inactive credentials `401` |
| POST | `/auth/refresh/` | `refresh` | new `access` | Public token endpoint; `200`, invalid/inactive `401` |
| GET | `/auth/me/` | none | `id`, names, username, email, `role` | Authenticated; `200`, otherwise `401` |
| GET | `/users/presales-options/` | none | active Presales IDs and display names | Sales only; `200`; other roles `403`, anonymous `401` |

There is no logout/revocation endpoint in the current backend. Client logout means clearing locally held tokens.

### Customers

| Method | Path | Request | Frontend-relevant response | Access and important statuses |
| --- | --- | --- | --- | --- |
| POST | `/customers/` | `name`, optional `industry`, `company_size`, `basic_info` | created Customer | Sales or business Admin; `201`; invalid `400` |
| GET | `/customers/search/?q=...&page=...` | non-empty `q` | paginated matches plus active Opportunity summaries | Sales or business Admin; `200`; missing query `400` |
| GET | `/customers/{id}/` | none | Customer fields plus safe active Opportunity summaries | Sales or business Admin; `200`, missing `404` |

There is deliberately no browse-all Customer list, Customer update, or Customer delete API. `/customers` must therefore be a search-and-create workspace rather than a conventional complete table.

### Opportunities

| Method | Path | Request | Frontend-relevant response | Access and important statuses |
| --- | --- | --- | --- | --- |
| GET | `/opportunities/?page=...` | none | paginated ID, project/customer/owners, stage/status, budget/date | Sales sees owned; Presales sees assigned; Admin sees all; `200` |
| POST | `/opportunities/` | project, customer, optional Presales, raw requirement, budget/date | created Opportunity with server-owned Sales/creator/default state | Sales only; `201`; invalid `400`; other roles `403` |
| GET | `/opportunities/{id}/` | none | full visible Opportunity including `raw_requirement` | Role-filtered; inaccessible objects are `404` |
| PATCH | `/opportunities/{id}/` | project, Presales, requirement, budget, stage/status, launch date | updated Opportunity | Owning Sales only; `200`; invalid `400`; invisible `404`; Admin/Presales `403` |

`is_staff` and `is_superuser` never widen the business-visible queryset.

### Requirement Analysis

| Method | Path | Request | Frontend-relevant response | Access and important statuses |
| --- | --- | --- | --- | --- |
| POST | `/opportunities/{id}/ai/requirement-analyses/` | exactly `{}` | immutable persisted analysis snapshot | Admin/Sales/Presales with Opportunity visibility; `201`; invalid `400`; provider/domain `502/503` |
| GET | `/opportunities/{id}/ai/requirement-analyses/` | optional page | compact analysis history | Same visibility; `200` |
| GET | `/opportunities/{id}/ai/requirement-analyses/latest/` | none | latest full snapshot | Same visibility; `200`, no history `404` |
| GET | `/opportunities/{id}/ai/requirement-analyses/{analysis_id}/` | none | selected full snapshot | Same visibility and parent ownership; `200/404` |

The detail contains summary, ten-dimension `requirements`, conflicts, clarifying questions, frozen raw requirement/context, analysis contract version, model metadata, author, and timestamp. History is immutable; no update/delete API exists.

### Solution Drafts and direct review actions

| Method | Path | Request | Frontend-relevant response | Access and important statuses |
| --- | --- | --- | --- | --- |
| GET | `/opportunities/{id}/solution-drafts/` | optional page | compact version history, review/stale state | Admin/Sales/Presales with Opportunity visibility; `200` |
| POST | `/opportunities/{id}/solution-drafts/` | exactly `analysis_id` | persisted structured draft and provenance | Same visibility; `201`; wrong analysis `400`; safe generation/persistence `422`; provider `502` |
| GET | `/solution-drafts/{id}/` | none | list fields plus `draft_payload` and durable provenance | Opportunity-visible users and explicitly assigned version reviewer; `200/404` |
| POST | `/solution-drafts/{id}/submit/` | optional `reviewer_id` | created `PENDING` review | Eligible submitter; `201`; permission `403`; invalid/stale/state/reviewer conflict `409` |
| POST | `/solution-drafts/{id}/approve/` | optional `comment` | decided `APPROVED` review | Assigned Presales reviewer or eligible business Admin; `200`; permission `403`; state/stale `409` |
| POST | `/solution-drafts/{id}/request-revision/` | exact `return_reason`, non-empty `comment` | decided `RETURNED` review | Same decision authority; `200`; invalid payload `400`; permission `403`; state `409` |
| GET | `/solution-drafts/{id}/reviews/` | none | full immutable review history | Same draft visibility; `200/404` |

No PATCH/DELETE endpoint exists for Solution content, review status, or review history.

Important action rules:

- Sales submits an owned Opportunity's draft to its assigned Presales owner.
- A Presales author must explicitly select a different active Presales reviewer.
- The assigned reviewer, or a non-author business Admin fallback, decides a pending review.
- Sales cannot approve or return a technical review.
- Stale drafts cannot be submitted or approved.
- Technical flags never grant business authority.

### Knowledge and RAG

| Method | Path | Request | Frontend-relevant response | Access and important statuses |
| --- | --- | --- | --- | --- |
| GET | `/knowledge/documents/` | optional page | safe document metadata and indexing state | Business Admin only; `200`; others `403` |
| POST | `/knowledge/documents/` | multipart `title`, `document_type`, `source_file` | indexed document metadata | Business Admin only; `201`; invalid file `400`; indexing conflict `409`; processing error may remain represented on resource |
| GET | `/knowledge/documents/{id}/` | none | safe document metadata | Business Admin only; `200/404` |
| POST | `/knowledge/documents/{id}/reindex/` | no business fields | refreshed document metadata | Business Admin only; `200`; conflict `409`; processing failure `422` |
| POST | `/knowledge/search/` | `query`, optional `top_k`, `document_type` | ranked chunks with citation-safe source metadata | All three business roles; `200`; invalid `400`; provider/config `502/503` |
| POST | `/rag/answer/` | `query`, optional `document_type` | grounded answer and ranked source labels | All three business roles; `200`; invalid `400`; provider/config `502/503` |

`EnterpriseGroundingFact` proposal review exists only in Django Admin. There is no REST list/approve/reject API for a Vue Grounding Fact review screen. Knowledge documents are read/create/reindex only; no document update/delete API exists.

### LangGraph workflow

Phase 6a provides a durable service graph and official PostgreSQL checkpointer, but currently exposes no HTTP endpoints for:

- starting a workflow with `opportunity_id`, explicit `analysis_id`, and workflow identity;
- reading current workflow outcome/interrupt data;
- resuming an interrupt with approve or request-revision input.

Until a minimal adapter is added, the Vue client can use the existing direct Solution/review APIs, but it cannot claim to operate or resume the durable LangGraph flow.

## Role UX matrix

| Capability | Sales | Presales | Business Admin |
| --- | --- | --- | --- |
| Sign in and view own identity | Yes | Yes | Yes |
| Search/create Customer | Yes | No | Yes |
| View Opportunities | Owned only | Assigned only | All |
| Create/update Opportunity facts | Owning Sales | No | No under current API |
| Assign Presales on Opportunity | Owning Sales | No | No under current API |
| Create/read Requirement Analysis | Visible Opportunity | Visible Opportunity | Visible Opportunity |
| Generate/read Solution versions | Visible Opportunity | Visible Opportunity | Visible Opportunity |
| Submit draft | Owned Opportunity | Assigned Opportunity under service rules | Fallback |
| Approve/request revision | Never | Assigned independent reviewer | Non-author fallback |
| Read an explicitly assigned review version | Only through owned Opportunity | Yes, even outside Opportunity assignment | All |
| Manage Knowledge documents | No | No | Yes |
| Search knowledge/use RAG | Yes | Yes | Yes |
| Review Grounding Facts | No | No | Django Admin business-admin surface only |

The UI may hide unavailable actions, but should still render backend `403`, `404`, and `409` responses as authoritative business outcomes.

## Page and route architecture

### Recommended routes

| Route | Purpose | Primary roles | Backend dependency |
| --- | --- | --- | --- |
| `/login` | JWT sign-in | Public | auth login/me |
| `/dashboard` | Role-specific landing and work summary | All | Opportunities; pending-review aggregate is currently missing |
| `/customers` | Search and create Customers | Sales, Admin | Customer search/create |
| `/customers/:id` | Customer context and active Opportunities | Sales, Admin | Customer detail |
| `/opportunities` | Role-filtered Opportunity list | All | Opportunity list |
| `/opportunities/:id` | Main workspace with nested tabs | Visible users | Opportunity, analyses, solutions, reviews |
| `/opportunities/:id/overview` | Owners, stage, dates, requirement editing | Visible; edit by owning Sales | Opportunity detail/PATCH |
| `/opportunities/:id/requirement` | Raw customer facts and clarification work | Visible; edit by owning Sales | Opportunity detail/PATCH |
| `/opportunities/:id/analysis` | Analysis history/detail and trigger | Visible | Requirement Analysis APIs |
| `/opportunities/:id/solutions` | Solution version list and generate action | Visible | Solution collection APIs |
| `/solutions/:id` | Full version, citations, provenance, review history/actions | Visible or assigned reviewer | Solution detail/review APIs |
| `/reviews` | Reviewer inbox | Presales, Admin | **Backend aggregate API missing** |
| `/knowledge` | Document list/upload | Admin | Knowledge document APIs |
| `/knowledge/:id` | Index state and reindex action | Admin | Knowledge document detail/reindex |

Do not create a separate top-level page for every Opportunity subresource. Nested routes preserve deep links while keeping customer facts, AI analysis, Solution history, and review state in one workspace.

### Opportunity Detail as the main workspace

Recommended tabs:

1. **概览** — project/customer, owners, stage/status, budget, expected date.
2. **客户需求** — editable raw requirement and customer facts for the owning Sales user; read-only for others.
3. **AI 需求分析** — immutable snapshot history, dimension status, conflicts, clarifying questions, and explicit analyze action.
4. **技术方案** — version timeline, selected analysis, current/stale indicator, generate action, and links to detail.
5. **审核** — current review state/history and the next business action; initially populated from Solution APIs.

This layout makes the workflow legible without forcing users to jump among analysis, Solution, and review pages. `/solutions/:id` remains a focused deep view for long structured content and provenance.

## Status and Chinese display mapping

Backend enum values remain unchanged. The UI maps them to localized labels and semantic colors/icons.

### Opportunity

| Enum | Chinese label |
| --- | --- |
| `initial_contact` | 初步接触 |
| `requirement_analysis` | 需求分析 |
| `presales_support` | 售前支持 |
| `solution` | 方案制定 |
| `quotation` | 报价 |
| `negotiation` | 商务谈判 |
| `active` | 进行中 |
| `won` | 已赢单 |
| `lost` | 已丢单 |
| `closed` | 已关闭 |

### Requirement dimensions

| Enum | Chinese label | UX treatment |
| --- | --- | --- |
| `known` | 已确认 | normal/success |
| `unknown` | 信息缺失 | warning; prompt Sales clarification |
| `unclear` | 尚不明确 | warning; show clarification question |
| `conflict` | 信息冲突 | danger; show competing facts |

### Solution and review

| Enum | Chinese label |
| --- | --- |
| `draft` | 草稿 |
| `pending_review` | 等待售前审核 |
| `approved` | 技术审核已通过 |
| `needs_revision` | 需要处理退回意见 |
| Review `pending` | 审核中 |
| Review `approved` | 已批准 |
| Review `returned` | 已退回 |
| `customer_info_required` | 需要补充客户信息 |
| `technical_revision_required` | 需要修改技术方案 |
| `is_stale=false` | 当前有效 |
| `is_stale=true` | 已过期，需重新确认 |
| `newer_requirement_analysis` | 存在更新的需求分析 |
| `grounding_fact_invalid` | 企业事实已失效 |
| `grounding_provenance_invalid` | 证据来源已失效 |

### Knowledge

| Enum | Chinese label |
| --- | --- |
| `pending` | 待处理 |
| `processing` | 索引处理中 |
| `ready` | 已就绪 |
| `failed` | 处理失败 |

If a Grounding Fact REST surface is added later, its labels should be `待审核/已批准/已拒绝`, `已确认支持/已确认不支持/未确认/冲突`, and `当前/已过期`.

## LangGraph human-review UX

The frontend must translate orchestration state into business progress:

```text
正在生成 AI 技术方案
  -> 方案已生成，正在提交审核
  -> 等待售前审核
  -> 技术审核已通过
     or 需要补充客户信息
     or 需要修改技术方案
```

Never display `LangGraph`, checkpoint tables, graph node names, `thread_id`, or raw interrupt payloads to ordinary users.

Once backend adapters exist:

- Start: send explicit `analysis_id`; receive a stable workflow ID and current outcome.
- Waiting: render Solution version, assigned reviewer, allowed business actions, and a durable “等待售前审核” state.
- Resume approve: assigned reviewer supplies optional comment.
- Resume revision: reviewer selects exactly one return reason and provides a required comment.
- Reconstruction: a refresh or new browser session queries the workflow/business state again; it never treats client state as authority.
- Conflict: render a stable “审核状态已变化，请刷新” message and reload Solution/Review from PostgreSQL-backed APIs.

Before that adapter is implemented, direct submit/approve/request-revision endpoints provide equivalent business actions but not graph checkpoint/resume semantics.

## Solution detail UX

Default view:

- header: Solution title, version, selected analysis, creator/time;
- prominent badges: review state and current/stale state;
- stale banner: machine reason translated to an actionable message;
- structured executive summary, fixed Solution sections, and assumptions;
- citation markers beside statements;
- review timeline showing submitter, reviewer, decision, return reason, comment, and timestamps;
- role- and state-sensitive actions supplied by backend results.

Expandable “来源与证据” drawer:

- citation label and source document title/ID when resolvable;
- source excerpt, source snapshot identifiers, and Fact identity for audit users;
- avoid presenting content hashes/index run UUIDs as the main business display;
- do not expose provider credentials or raw model responses.

The current detail payload exposes durable provenance but does not include source document titles. The client can show document IDs/excerpts initially; a later bounded serializer enhancement may add safe display names.

## Knowledge UX boundary

Phase 7 first version should implement only what the REST API supports:

- Admin document list with indexing/status/error feedback;
- upload/create with supported file validation feedback;
- document detail and reindex action;
- optional all-role knowledge search/RAG utility after the core Opportunity workflow.

Do not build a Vue Grounding Fact approval page yet. Its required list/detail/approve/reject REST API is missing. Keep the existing Django Admin review surface until a separately scoped backend change is approved.

## Frontend stack

Recommended minimum:

- Vue 3 single-file components with Composition API and TypeScript;
- Vite for development and production builds;
- Vue Router for nested Opportunity routes and authentication/role-aware navigation guards;
- Pinia for authentication/current-user state and small global UI preferences only;
- Axios with one configured API instance and a single-flight refresh interceptor;
- Element Plus for professional tables, forms, dialogs, tabs, steps, status tags, upload, and feedback components;
- Vitest and Vue Test Utils for unit/component contracts.

Element Plus is recommended because this application is form-, table-, status-, and workflow-heavy. Use a small SalesMind theme and domain components rather than wrapping the entire library in a new design system.

Do not add Nuxt, GraphQL, micro-frontends, a second global state system, or the LangChain frontend ecosystem. Pin exact compatible package versions only when implementation begins.

Official references: Vue recommends Vite for new Vue projects; Vue Router supplies the official SPA routing and guard model; Pinia is intended for shared cross-page state and advises against storing component-local state globally; Element Plus targets Vue 3 business UI.

## Authentication architecture

1. Login submits username/password to `/api/auth/login/`.
2. Keep the short-lived access token in memory.
3. Under the unchanged current JWT contract, keep the refresh token in `sessionStorage` if reload continuity is required; do not use `localStorage` by default. Document the XSS trade-off.
4. Set `Authorization: Bearer <access>` from one Axios request interceptor.
5. On one `401`, run a single-flight refresh request, update memory, then replay the original request once.
6. If refresh fails, clear tokens/user state and route to `/login` with the intended return path.
7. On application bootstrap with a refresh token, refresh access and then load `/api/auth/me/`.
8. Router guards require authentication and may hide routes by the current business role. Backend permissions remain authoritative.

Do not infer Admin from `is_staff` or `is_superuser`; `/auth/me/` returns the business `role` needed by the UI.

## API client organization

Recommended modules:

```text
frontend/src/api/http.ts
frontend/src/api/auth.ts
frontend/src/api/users.ts
frontend/src/api/customers.ts
frontend/src/api/opportunities.ts
frontend/src/api/analysis.ts
frontend/src/api/solutions.ts
frontend/src/api/reviews.ts
frontend/src/api/knowledge.ts
frontend/src/api/rag.ts            # defer from first vertical slice
```

Each domain module exposes typed request/response functions. `http.ts` owns base URL, authorization, refresh coordination, bounded error normalization, and cancellation plumbing; it contains no business permission rules.

Keep transport DTOs separate from view-specific derived models. Preserve backend pagination and safe error envelopes rather than inventing a second response taxonomy.

## State management

Global Pinia state:

- access-token/authentication lifecycle;
- current user and business role;
- optional small UI preferences such as collapsed navigation.

Route/page state:

- Customer search and create form;
- Opportunity list filters/page;
- selected Opportunity, analysis history, and Solution versions;
- Solution detail, provenance expansion, and review form;
- Knowledge document list/upload state.

Fetch server state on route entry and after mutations. Do not permanently mirror Customer, Opportunity, Solution, review, or workflow truth in Pinia. PostgreSQL-backed responses are authoritative after refresh/resume.

## Backend API gaps

### Required to expose the Phase 6a workflow

1. Start endpoint accepting Opportunity and explicit `analysis_id`, creating/using a server-side workflow UUID, and returning a safe business-state representation.
2. Read/status endpoint for reconstruction after refresh or sign-in.
3. Resume endpoint accepting approve or request-revision input and adapting interrupts to safe business responses.
4. Server-side mapping from authenticated actor to workflow `actor_id`; the client must not authorize itself by submitting arbitrary actor IDs.

These should be thin adapters around the existing graph/checkpointer, not new business logic.

### Required for an effective review inbox

- A paginated “reviews assigned to me” endpoint, or equivalent pending-review collection. Current APIs can read review history only when the client already knows a Solution ID.

### Optional bounded improvements

- Safe source document display names in Solution provenance detail.
- A later Grounding Fact REST review surface if Vue replaces the current Django Admin workflow.
- Dashboard aggregate counts if loading and aggregating visible Opportunities client-side becomes inefficient.

### Existing intentional limitations

- no Customer browse-all/update/delete;
- no Solution payload update/delete;
- no automatic revision loop;
- no global review assignment management;
- no Vue Grounding Fact review API.

## Phase 7a minimum vertical slice

Phase 7a should prioritize:

```text
Login
  -> role-aware Opportunity list
  -> Opportunity workspace
       -> customer requirement display/edit (Sales)
       -> Requirement Analysis history/generate/detail
       -> generate Solution from explicit analysis
       -> Solution version/detail/provenance
       -> submit review
  -> Presales opens assigned review
       -> approve
          or request revision with one explicit reason/comment
```

Implementation should begin with the currently supported direct Solution/review endpoints. In parallel or immediately afterward, add the narrowly scoped Phase 6a HTTP adapters and switch the same UI state machine to durable workflow start/status/resume. Do not make the Vue screen aware of graph internals.

Admin Knowledge document management is the next bounded slice, not a prerequisite for the core demo. Customer search/create supports Sales Opportunity setup but should not expand into unsupported customer CRUD.

## Recommended implementation order

1. Frontend tooling, typed HTTP client, authentication bootstrap, and protected shell.
2. Opportunity list and Opportunity Detail workspace shell.
3. Sales-owned Opportunity requirement editing and analysis history/detail/generation.
4. Solution version list/detail, structured draft rendering, stale/review badges, and provenance drawer.
5. Direct submit/approve/request-revision actions with role/state-aware UX and backend-authoritative errors.
6. Minimal backend Phase 6a workflow start/status/resume adapters plus a review-inbox endpoint.
7. Bind the existing UI business-state model to workflow reconstruction/resume.
8. Admin Knowledge document list/upload/detail/reindex.
9. Optional Customer search/create polish, RAG utility, dashboard aggregates, and E2E/demo hardening.

## Explicit exclusions

- No Vue code, scaffold, or package file is created by this design task.
- No backend behavior, test, migration, or API is modified.
- No automatic revision loop, multi-agent UI, notifications, delivery workflow, or customer approval.
- No frontend-only authorization assumption.
- No exposure of checkpoint or model-provider internals.
