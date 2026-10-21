# Admin Grounding Fact Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Django Admin 内完成正常文档上传、索引、显式抽取待审事实与既有人工审批衔接，不依赖演示脚本。

**Architecture:** 复用现有上传 serializer、索引、严格事实 parser 和审批服务；独立 Admin 操作视图避免默认表单长事务。新增最小持久化抽取尝试，以文档行锁、条件唯一约束和执行 token 防重，并在候选保存事务内同步提交成功状态。

**Tech Stack:** 当前 Django/DRF、PostgreSQL/pgvector、Django templates、pytest-django；不新增依赖、队列或 Vue 页面。

**Spec:** [2026-10-15-admin-grounding-fact-ingestion-design.md](../specs/2026-10-15-admin-grounding-fact-ingestion-design.md)

状态：用户已批准在原目录按 Native 方式实施。Task 1–9 的主要实现与离线验收已完成，2026-10-16 恢复中断后核对完成记录。后端2884项、知识库专项425项、前端150项通过，构建及管理检查通过；独立评审的重要并发问题已以RED→GREEN修复。确认页版本及重试编号的可见展示有一项Minor暂缓。未应用业务库迁移、调用真实模型或重启服务。下列任务步骤保留原始计划，实际逐项证据与裁定记录在本计划对应的 `.superpowers/sdd/` 进度记录中。

## Global Constraints

- “抽取只提出候选事实；批准不等于事实永久有效，也不等于方案通过技术审核。”
- “原方案准入、引用、当前索引、过期判断、verifier veto-only、返回时来源复验均保留。”
- “这些 Admin 入口统一要求当前用户 active、staff 且业务 role=admin。”
- “操作使用 Admin 会话、CSRF 和 POST；GET 仅展示/确认，不调用 provider、不写数据。”
- “当前支持 UTF-8 TXT、Markdown 和可提取文字的 PDF，沿用大小、页数和解析限制。”
- “同一文档同一 index-run 最多一个 RUNNING 或 SUCCEEDED 记录，数据库条件唯一约束兜底”。
- “候选创建与 SUCCEEDED 转换必须同一事务完成。”
- “模型内部传输重试沿用已有 provider 配置，不增加新一层格式重试或循环重试。”
- “不引入任务队列、后台线程、定时清理、自动 lease 接管或新服务。”
- “先在现有测试环境验证，不在用户业务库应用 migration，也不自动重启项目。”
- 保留 dirty 工作区，禁止 staging/commit/stash/reset/清理；不触碰 `.workbuddy/` 或 `docs/code-review-2026-08-29.md`。
- 不维护 PostgreSQL 实例、端口、角色、模板、扩展；无真实 provider 验收请求。所有数据库测试串行运行。
- 工作位置继续使用用户已选择的当前目录；执行前使用只读检查确认，不自行换工作区或丢失现有改动。
- GitNexus 绑定 `SalesMind AI`；已有索引 storage43/runtime42 不兼容，不自动重建，记录源码导航退化。
- 新增 managed 抽取及 Admin 外部调用测试使用 `pytest.mark.django_db(transaction=True)`，与现有抽取测试一致；普通 pytest 外层测试事务会掩盖或触发 nested-transaction 防线，不能据此删除事务外调用断言。纯模型约束测试可用普通 django_db。

## Review Focus

1. 无候选成功与“从未执行”不同：Task 4 固化 SUCCEEDED/0 的无再次付费回放测试。
2. 失败后旧确认页重放不能变成再次付费重试：Task 2/4 以失败尝试 ID 作前置条件，测试旧 ID 冲突。
3. 上传/抽取期间管理员被停用或改角色：Task 3/6 测试完成前重新鉴权，不能因初始会话有效而写入候选。
4. 取消、迟到完成与索引切换交错：Task 3/8 用真实数据库锁和受控事件证明旧 token 无写入资格。
5. 用户文档标题/摘录含 HTML，存储或 provider 抛出敏感异常：Task 5/6/7 测试转义与固定错误文案，不显示 traceback/文件路径/密钥。

## File Structure / Interfaces

以下均为仓库相对路径。执行者先读 spec、本计划和 `AGENTS.md`；未列出的业务模块默认不改。

| 文件 | 职责 |
| --- | --- |
| `apps/knowledge/models.py` | 追加 `GroundingFactExtractionStatus`、`GroundingFactExtractionAttempt`；不重构现有模型 |
| `apps/knowledge/migrations/0004_grounding_fact_extraction_attempt.py` | 新表、约束、索引；依赖 `0003_knowledge_grounding_facts`；无数据回填 |
| `apps/knowledge/services/grounding_fact_attempts.py`（新） | 认领、token/权限检查、短事务状态转换与取消；不调用 provider |
| `apps/knowledge/services/grounding_facts.py` | 新增可选 managed binding；复用原 parser；候选与成功状态同事务 |
| `apps/knowledge/services/grounding_fact_operations.py`（新） | Admin 用例编排、结果类型、安全失败记录；调用既有 extractor |
| `apps/knowledge/admin_documents.py`（新） | 文档 Admin、显式 URL、GET/POST 操作视图和安全展示；不默认保存可编辑文档 |
| `apps/knowledge/admin_forms.py`（新） | 上传、索引版本确认、失败重试确认、取消确认表单 |
| `apps/knowledge/admin.py` | 注册文档 Admin；保留事实审批服务与全部权限门禁 |
| `apps/knowledge/templates/admin/knowledge/knowledgedocument/`（新） | `change_list.html`、`change_form.html`、`upload.html`、`operation_confirm.html` |
| `apps/knowledge/tests/admin_grounding_fixtures.py`（新） | 当前测试局部导入的用户/文档/fake helpers，不添加全仓 autouse |
| `apps/knowledge/tests/test_grounding_fact_attempt_model.py`（新） | 数据库约束 |
| `apps/knowledge/tests/test_grounding_fact_attempts.py`（新） | 认领、重放、权限和状态机 |
| `apps/knowledge/tests/test_managed_grounding_fact_extraction.py`（新） | 原子完成、错误、撤销 token、来源变化 |
| `apps/knowledge/tests/test_admin_knowledge_documents.py`（新） | 后台列表、元数据/上传/索引操作 |
| `apps/knowledge/tests/test_admin_grounding_fact_operations.py`（新） | 抽取/重试/取消 HTTP 边界、CSRF、人工审批衔接 |
| `apps/knowledge/tests/test_grounding_fact_attempt_concurrency.py`（新） | 多连接约束/锁竞争 |
| `docs/admin-knowledge-workflow.md`（新） | 管理员使用说明及失败恢复边界 |

### Shared types（在 Task 2 定义）

- `ExtractionBinding` frozen dataclass: `document_id:int`, `index_run_id:UUID`, `attempt_id:int`, `token:UUID`, `actor_id:int`。
- `ExtractionClaim` frozen dataclass: `state:Literal['claimed','running','succeeded','legacy_facts']`, `binding:ExtractionBinding|None`, `attempt_id:int|None`, `index_run_id:UUID`, `proposed_count:int`。
- `FactExtractionOperationError`: 仅 `code:str` 和白名单 `safe_message:str`；不持有模型原文作为公开属性。
- 下文 `actor_id` 必须服务器生成；`expected_index_run_id` 必须确认页冻结。retry 的 `retry_after_attempt_id:int|None` 是被确认的失败/取消记录，不是通用 `force=True`。
- 新 fixtures 模块导出并由具体测试文件显式导入 `admin_actor(django_user_model)`（active/staff/admin）、`admin_client(client,admin_actor)`（force_login）、`ready_document(admin_actor)`（返回 document/chunk）、`attempt_factory(admin_actor,ready_document)`（返回 `(**overrides)->GroundingFactExtractionAttempt` 闭包），以已有 extraction 测试的 READY/chunk 构造为参考。所有文件存储用测试局部临时 MEDIA_ROOT。
- 复用 `apps.knowledge.tests.test_grounding_fact_extraction.ExtractionFakeLLM`、`payload` 和 `apps.knowledge.tests.embedding_fakes.DeterministicEmbeddingProvider`；若因测试模块耦合需搬到新 helper，保持原测试接口和行为不变，不新造外部联网 fixture。

## Task 1: 持久化抽取尝试与数据库防线

**Files:** models、migration、`test_grounding_fact_attempt_model.py`。

**Interfaces:** 产生 `GroundingFactExtractionAttempt`，后续代码不复用文档 indexing 状态当作抽取状态。

- [ ] 写失败测试。用合法最小文档/用户 fixture 覆盖：

```python
def test_running_and_success_share_one_slot(attempt_factory):
    first = attempt_factory(status='running')
    with pytest.raises(IntegrityError), transaction.atomic():
        attempt_factory(document=first.document, index_run_id=first.index_run_id,
                        status='succeeded', finished_at=timezone.now())

def test_terminal_failure_does_not_hold_the_slot(attempt_factory):
    first = attempt_factory(status='failed', finished_at=timezone.now(),
                            error_code='fact_extraction_provider_failed')
    second = attempt_factory(document=first.document, index_run_id=first.index_run_id)
    assert second.pk != first.pk
```

  `attempt_factory` 在新 fixtures 模块定义为接收 `**overrides` 的闭包。新增非法状态、重复 token、负候选数、RUNNING 有完成时间/错误/条数、成功有错误、失败无安全码、终态无完成时间、PROTECT 删除测试。
- [ ] RED：`python -B -m pytest apps/knowledge/tests/test_grounding_fact_attempt_model.py -q`，因模型缺失/约束缺失失败。
- [ ] 实现字段：默认 BigAutoField PK；document/requested_by PROTECT；index_run_id UUID；token UUID unique/default uuid4；status choices；started_at 默认 now；finished_at nullable；error_code max_length64/default空；proposed_count 正整数/default0。
  RUNNING 必须 unfinished/count0/error空；SUCCEEDED finished/error空/count>=0；FAILED/CANCELLED finished/count0/安全码非空；完成时间不得早于开始时间。
  条件唯一 `knowledge_extract_active_run_unique(document,index_run_id)` 条件 status in running/succeeded；显式候选非负及状态/元数据 CHECK；索引 document/index_run_id/id。
- [ ] 用 Django 生成 migration 并检查只新增该表，禁止 RunPython/改既有数据。GREEN 跑同文件；执行 `makemigrations --check --dry-run`。不对业务库 migrate。

## Task 2: 短事务认领、权限、防重与取消

**Files:** 新 `grounding_fact_attempts.py`、`test_grounding_fact_attempts.py`、fixtures。

**Interfaces:**

```python
claim_extraction(document_id:int, *, actor_id:int, expected_index_run_id:UUID,
                 retry_after_attempt_id:int|None=None) -> ExtractionClaim
require_binding_locked(document:KnowledgeDocument, binding:ExtractionBinding
                       ) -> GroundingFactExtractionAttempt
mark_succeeded_locked(attempt:GroundingFactExtractionAttempt, *, proposed_count:int) -> None
fail_extraction(binding:ExtractionBinding, *, code:str) -> None
cancel_extraction(document_id:int, *, actor_id:int, attempt_id:int
                  ) -> GroundingFactExtractionAttempt
```

- [ ] 写 `test_claim_is_idempotent_without_provider`：第一次 claimed，第二次 running；仅一个 RUNNING。同 run 成功返回 succeeded；零候选也返回 succeeded。已有当前历史事实且没有 active/succeeded attempt 返回 legacy_facts，不补审计记录。
  `test_retry_requires_exact_latest_terminal_attempt`：失败/取消后无 retry ID 拒绝，正确 ID 可认领新记录；过期 retry ID 拒绝，旧记录不覆盖。状态读/取消均验证文档归属关系，不能跨文档使用 attempt ID。
- [ ] RED 跑该文件，预期缺少接口失败。
- [ ] 实现：每次加载当前用户并复用 `actor_can_review_grounding_facts`；claim 锁 document 后查状态、索引 ID、indexing_run_id、既有 active/成功/历史事实，再认领。历史失败按 PK 排序，不靠时间戳猜先后。任何嵌套外层事务入口以 `fact_extraction_nested_transaction` 拒绝，避免 provider 被包进调用者事务。
  外层事务拒绝只作用于需要在事务外编排的公开认领/执行入口；require_binding_locked 和 mark_succeeded_locked 必须在既有短事务内工作，不能反向拒绝其自身事务。
  取消锁 document→attempt，RUNNING→CANCELLED；重放同一 CANCELLED 幂等；SUCCEEDED/FAILED 取消冲突，不影响后来尝试。内部 fail 仅更新 token 匹配的 RUNNING，不覆盖已取消/成功。
- [ ] GREEN；额外参数化 inactive、admin无staff、staff Sales/Presales、技术superuser非admin、未知role，以及错 UUID/文档未READY/重建中，全部在认领前拒绝且无新记录。

## Task 3: 给现有 extractor 增加受管理的原子完成

**Files:** `grounding_facts.py`、`test_managed_grounding_fact_extraction.py`。

**Interfaces:**

```python
extract_grounding_facts(document_id:int, *, llm_provider:LLMProvider|None=None,
                       managed_attempt:ExtractionBinding|None=None
                       ) -> tuple[EnterpriseGroundingFact,...]
```

- [ ] RED 测试 `test_managed_completion_commits_facts_and_success_together`：provider callback 观察 `connection.in_atomic_block is False`；候选全 PROPOSED、无审批字段；成功条数吻合。
  `test_success_write_failure_rolls_back_candidates`：在 mark_succeeded_locked 注入异常，断言候选0、无 SUCCEEDED。
  `test_revoked_actor_or_token_cannot_publish`：provider callback 停用/降级用户或取消执行，断言零候选、无假成功，CANCELLED 不被覆盖。
- [ ] 仅 managed 分支在调用前检查 binding 文档/index 及权限，拒绝外层 atomic；原始 parser/主题/摘录/hash 逻辑不变。最终已有 document 锁内调用 require_binding_locked，重检 user、run、无重建、chunks；bulk_create 与 mark_succeeded_locked 同一 atomic。不要在外面再包一层长事务。
- [ ] GREEN managed 文件及既有 `test_grounding_fact_extraction.py`。再测 provider 期间 run ID 改变、开始 reindex、内容 hash 改变、未知subject、伪造APPROVED、非法JSON：均不得有部分候选。保留不传 managed_attempt 的历史调用默认行为。

## Task 4: Admin 用例编排与安全结果

**Files:** 新 `grounding_fact_operations.py`、managed 测试文件。

**Interfaces:**

```python
run_document_fact_extraction(document_id:int, *, actor_id:int,
                            expected_index_run_id:UUID,
                            retry_after_attempt_id:int|None=None,
                            llm_provider:LLMProvider|None=None) -> ExtractionClaim
```

- [ ] RED：`test_successful_empty_run_is_not_called_again` 用 `ExtractionFakeLLM('{"facts":[]}')` 跑两次，断言 calls1、count0、attempt1、SUCCEEDED。`test_failed_run_needs_a_new_confirmed_retry` 首次非法输出留FAILED但无facts，重复无retry ID 不再调模型；正确最新失败ID仅启动一次新尝试。
- [ ] claim 不是 claimed 立即返回，不构造 provider；claimed 后调用 Task 3 接口；捕获既有安全抽取/LLM异常映射码并 fail_extraction，保留原失败记录，重新抛安全操作错误。未知异常统一 `fact_extraction_failed`，不对用户展示原 cause。成功查询该 attempt 得到 succeeded 返回，不重复写事实。
- [ ] 固定操作错误码至少包括 `fact_extraction_permission_denied`、`fact_extraction_not_ready`、`fact_extraction_index_changed`、`fact_extraction_retry_required`、`fact_extraction_state_conflict`、`fact_extraction_nested_transaction`、`fact_extraction_provider_failed`、`fact_extraction_cancelled`、`fact_extraction_failed`；原 `grounding_fact_invalid_response`/`grounding_fact_index_changed` 可沿用。错误清理只用 token，不能因发起人权限已撤销而遗漏失败审计。
- [ ] GREEN Task 2/3 文件。测试持久化前失败与取消保持 READY 文档、原 chunks、历史 facts 完全不变；不改变 provider 自身 retry 配置。

## Task 5: Admin 只读文档列表、详情与状态

**Files:** 新 `admin_documents.py`，修改 `admin.py`，新模板 change_list/change_form，`test_admin_knowledge_documents.py`。

**Interfaces:** `KnowledgeDocumentAdmin(admin.ModelAdmin)`；在 `admin.py` 显式注册。原事实 Admin 不改变批准/拒绝逻辑。

- [ ] RED：真实 Client 强制会话登录各角色，断言仅 active+staff+admin 能看到文档列表/详情；无效角色不论superuser标记都拒绝。普通 Django add/change POST 禁止改文档和事实；无删除/批量抽取。
- [ ] 所有具体字段只读；native add/delete关闭，文档上传使用下一任务专用入口。展示标题、类型、索引状态/是否重建、当前 run 抽取状态、各审核状态计数。详情使用安全信息，不渲染可下载 source_file 链接或存储路径。
  表达严格区分未索引/失败/READY未抽取/RUNNING/FAILED/CANCELLED/SUCCEEDED零候选/历史事实/待审核；已批准旁加来源仍需准入校验说明。事实链接用 reverse + urlencode 到现有 fact changelist，不硬编码用户值。
- [ ] GREEN：参数化全部展示状态、旧run attempt不得冒充当前run；HTML标题及摘录转义；查询可通过 annotations/prefetch 避免每行独立查询，但不顺带重构其它列表。

## Task 6: 专用上传与重建索引视图

**Files:** `admin_documents.py`、新 `admin_forms.py`、upload/operation_confirm 模板、后台文档测试。

**Interfaces / URLs（通过 ModelAdmin.get_urls 注册并 reverse）：**

- `admin:knowledge_knowledgedocument_upload`：`upload/` GET/POST；上传标题、document_type、source_file。
- `admin:knowledge_knowledgedocument_reindex`：`<int:object_id>/reindex/` GET/POST；隐藏 expected_index_run_id UUID。
- forms：`KnowledgeDocumentUploadForm`、`DocumentIndexConfirmationForm`；所有校验错误固定安全文案。

- [ ] RED：GET两个入口零provider/零数据写；Client(enforce_csrf_checks=True) 无CSRF POST403。合法 TXT/MD/PDF 上传经实际serializer、临时 MEDIA_ROOT、fake embedding 后 READY/created_by正确；篡改元数据或created_by不能生效。
- [ ] 在专用视图调用既有 create serializer（validate + save(created_by=当前actor)），不调用原 API HTTP端点。GET不初始化provider；POST校验后 index_document。结束再次检查当前actor权限，权限失效不回传文档内容；已完成的可信索引不伪装回滚。
  索引失败保留真实FAILED记录并重定向只读详情显示安全错误；READY重建复用 reindex_document，先比较确认页旧run，不偷偷重建新run。外部调用禁止放在 ModelAdmin.save_model 或默认 _changeform_view atomic 中。
  admin_site.admin_view 包装后保留 CSRF、GET/POST 方法限制，并对最终注册视图应用 non_atomic_requests；仍在事务内被调用则安全拒绝，不能假设该装饰器能拆掉调用者事务。
- [ ] GREEN：fake callback 断言 embedding 不在 atomic；无权限不创建文件/记录/调用provider；超限/伪PDF/加密PDF/无文字/不支持Word沿原拒绝；存储写失败不显示成功或原异常；reindex失败保留旧索引；failed初索引不开放未经设计的原地强制重试。

## Task 7: 抽取、重试、取消和审核导航

**Files:** Admin documents/forms/operation_confirm、`test_admin_grounding_fact_operations.py`。

**Interfaces / URLs:**

- `admin:knowledge_knowledgedocument_extract`：`<int:object_id>/extract/` GET/POST；expected_index_run_id UUID、可选 retry_after_attempt_id 正整数。
- `admin:knowledge_knowledgedocument_cancel_extraction`：`<int:object_id>/extractions/<int:attempt_id>/cancel/` GET/POST。
- forms：`FactExtractionConfirmationForm`、`ExtractionCancellationForm`。禁止任意 redirect 参数；返回后台当前文档详情或其受限事实列表。

- [ ] RED：确认页显示费用/不自动批准说明；GET不调用/认领。POST fresh role/CSRF/method/版本/attempt归属全部检查。重复POST只一个模型调用；失败确认表单精确绑定失败ID，浏览器重发旧表单不启动第三次。
- [ ] 实现视图复用 Task 4/Task 2 服务；成功/处理中/历史事实/零候选分别明确提示；原始异常不进入 messages。取消明确告知仅撤销结果保存、不保证中止外部请求/计费，取消后重新执行需独立确认。不实现自动超时重试或GET轮询写状态。
- [ ] GREEN：新资料抽取后通过现有事实Admin的真实action POST人工批准/拒绝，不直接在fixture设APPROVED；验证服务端最终准入而非页面计数。优先复用 `build_solution_admission` 的现有fixture准备及 `test_solution_admission.py` 中来源构建模式，新增 `test_admin_upload_to_human_approval_admission` 在同文件验证：未批准/拒绝/过期不能获准，已批准且来源匹配才可。
  该验收只使用fake providers与现有准入服务，不生成方案、不运行 seed_demo、不调用真实provider。

## Task 8: 真 PostgreSQL 多连接竞争与迟到结果

**Files:** 新并发测试文件；必要时只修上面任务的实现，不扩其它模块。

**Interfaces:** 与 Task 2/3/4 相同，不新增产品接口。所有这些测试标记 `django_db(transaction=True)`。

- [ ] RED 写受控 Event/Barrier 并发测试；每工作线程独立 Django DB connection，finally关闭。只用fake provider，等待有超时，禁止 sleep 作为竞争保证或复用跨线程connection。
  `test_parallel_claims_make_one_model_request`：两客户端/服务同时开始，最多一个claimed/外部调用/结果集合。
  `test_cancelled_slow_completion_cannot_write`：旧provider阻塞，取消后明确新尝试，旧返回不写候选/不覆盖新状态。
  `test_reindex_switch_during_extraction_rejects_old_result`：模型等待期间走实际reindex事务切换run，旧结果零写入，新run仍可明确抽取。
  `test_database_active_slot_survives_direct_parallel_inserts`：不靠服务guard，数据库最多一个active/success，另一方IntegrityError；不同文档或不同run允许独立执行。
- [ ] 对失败只修因果已确认的锁/token/提交边界；每个修复先保留其RED证据。GREEN 跑并发文件及 Task 1–4 文件；不得通过多跑几遍掩盖不稳定。

## Task 9: 操作文档、整体验证与独立评审

**Files:** 新 `docs/admin-knowledge-workflow.md`；定向更新 `docs/architecture.md`、`docs/ai-pipeline.md`、`docs/business-rules.md`、`docs/known-limitations.md`、README 的相关入口段落。

**Interfaces:** 无新产品接口；文档必须区分已验证离线行为、尚未真实provider验收和未应用业务库migration。

- [ ] 写使用说明：所需权限、支持格式、上传/索引/抽取/审批含义、失败重试、取消和费用、历史事实处理、初次索引失败重新上传、审批≠方案终审。保留历史基线数字，只另外记录本轮真正验证的基线，不把设计写成已交付。
- [ ] 在 `.superpowers/sdd/2026-10-15-admin-grounding-fact-ingestion/` 建立本任务测试日志/进度记录，不改用户保护文件。执行前排除同库其它pytest并发；若有，等待，不终止用户进程。
  仅向测试子进程加载 `.env` 的 DATABASE_URL/TEST_DATABASE_TEMPLATE，不输出值；清空LLM/EMBEDDING/VERIFIER API key，移除URL环境覆盖以保留受测默认值，并使用局部fake fixtures。不得加载真实模型凭据；不要依赖仅patch verifier就不会联网。
- [ ] 依次运行：

```powershell
.\.venv\Scripts\python.exe -B -m pytest apps/knowledge/tests -q --tb=short
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short
.\.venv\Scripts\python.exe -B manage.py check --settings=config.settings.test
.\.venv\Scripts\python.exe -B manage.py makemigrations --check --dry-run --settings=config.settings.test
# Repeat dry-run under LANGUAGE_CODE=en-us via override_settings if translated labels drift.
# Only inspect new migration SQL; do not apply to business DB.
.\.venv\Scripts\python.exe -B manage.py sqlmigrate knowledge 0004 --settings=config.settings.test
git diff --check
# In frontend/, separately:
npm.cmd test
npm.cmd run build
```

  PostgreSQL测试仅使用既有测试环境/临时测试数据库，不创建/修理实例、角色或模板。
  全部命令必须记录真实退出码，PowerShell后续成功不能掩盖前一步失败。预期新迁移只CREATE本表/约束/索引，无既有业务数据UPDATE/DELETE。
- [ ] 独立只读评审规格符合度和新增diff，尤其权限、事务/网络、旧token、并发、XSS/敏感日志。按 requesting-code-review 使用 reviewer；没有该review结果不得称完成。修复反馈仍需RED/GREEN；仅文档计划阶段不派实现代理。
- [ ] 最终交付说明新增表尚未应用业务库，真实模型验收尚未进行，现有进程未自动重启。不得自动转入其它审查条目，不提交Git。

## Plan Self-review / Coverage

- Spec 1–4：Task 5–7，Admin-only/双门权限/显式入口；无Vue或业务API扩张。
- Spec 5：Task 6，既有文件验证/索引、事务外外部调用、失败索引保留。
- Spec 6：Task 1–4/7/8，条件唯一、成功0、历史事实、确认重试、取消fence、原子完成。
- Spec 7：Task 3/5/7/8，当前版本、人工批准、不继承旧审批、安全文案。
- Spec 8–9：Global Constraints/Task 9，无其它review修复、无实例操作/业务库迁移/真实调用。
- Spec 10–11：各任务RED/GREEN、Task 8多连接、Task 9全量/独立review/真实性边界。
- 所有跨任务接口均定义于 Shared types 或 Task 2/3/4；没有未定义 force flag 或后台worker。
- 用户选择执行方式前，不进入Task 1，不安装依赖、不创建隔离工作区、不改业务代码。
