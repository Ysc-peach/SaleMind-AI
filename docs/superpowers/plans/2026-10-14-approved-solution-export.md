# Approved Solution Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 有权限的用户从方案详情页下载仍有效、已获技术审核批准的确切版本，支持真正的 Word 和 PDF。

**Architecture:** 后端只读 gate 建立不可变导出快照，V1/V2 适配为共享文档投影，两个 renderer 在内存生成文件；返回前重新加载业务状态并比较指纹。独立下载 API 不进入生成/审核工作流，前端使用已有认证桥和下载生命周期保护。

**Tech Stack:** Django/DRF、Vue/TypeScript、python-docx 1.2.0、ReportLab 5.0.1、静态 Noto Sans SC TrueType、既有 pypdf/pytest/Vitest。

**Spec:** `docs/superpowers/specs/2026-10-14-approved-solution-export-design.md`（用户已确认设计与本计划，选择 Native 执行；2026-10-14 实施验收完成，证据见本计划专属 ledger）。

## Global Constraints

- 在当前目录保留全部既有改动；不 stage、commit、切分支、清理用户文件；不触碰 `.workbuddy/` 与 `docs/code-review-2026-08-29.md`。每个任务的“提交”步骤由本约束替换为局部差异检查。
- 不修改、重启或修复 PostgreSQL 实例、配置、端口、PID、角色、模板、扩展；测试仅使用项目既有测试数据库机制。数据库不可用时报告，不自行修复。
- role 独立于 staff/superuser；LLM 不授予准入，semantic verifier 保持 veto-only；不放宽审批、grounding、当前索引、stale 或返回时来源复核。
- `GET /api/solution-drafts/{solution_id}/export/?file_type=docx|pdf`；不使用 DRF 保留的 `format` 参数。只读、无模型调用、无业务数据写入、无迁移、无匿名分享或外部正文资源下载。
- 同时满足 actor 当前活跃/业务角色、确切版本可见、APPROVED 投影及真实已完成 APPROVED 记录、无 stored/computed stale、原需求 strip 后匹配、严格 payload 和完整 provenance 对应。
- 不强加“最大版本号才可导出”；不能给独立版本审核人增添整个商机或知识库权限。
- 固定声明原文：本文件为导出时有效的内部技术审核版本，可用于技术沟通；不构成报价、合同、客户验收、性能或 SLA 承诺。导出后的编辑内容不自动继承系统审核。
- A4 纵向；中文字体、自动换行、跨页内容、版本页眉和页码；完整正文，不截断。默认最大 `10 * 1024 * 1024` 字节，在内存整体生成后才返回，不提前流式输出。
- 正文仅普通文本；PDF markup 转义；无宏、外部资源、可执行 HTML。默认不导出原需求、来源 excerpt、内部审核备注/退回历史、诊断、密钥。
- 文件名 `SalesMind-solution-{id}-v{version}.{file_type}`；正确 MIME、attachment、`Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff`。
- 错误按 spec 第 7 节 code/HTTP 合同，日志只记安全 ID/版本/格式/受控类别/时间；不记录原文和 exception cause。
- 测试先 RED 后 GREEN；计划只是实施授权范围，不代表依赖已安装、样例已下载或功能已验证。

## Review Focus

1. 同用户退出后重新登录、甚至重新登录同一账号：旧请求也不得触发下载（Task 5 以 session epoch，而非仅 user ID 验证）。
2. V1 同文 executive alias、V2 同文不同 claim ID、一个引用支持多个事实：完整对应不能靠文本相等或“有一行即可”（Task 1/2）。
3. 摘录未导出但文档标题发生变化，或者生成时角色/归属变更：指纹覆盖所有使用字段，最终复核拒绝（Task 1/4/6）。
4. 超长连续文本、超高表格单元格、正文未被字体覆盖的字符：不能裁剪、缺字或出现空白成功文件（Task 3，缺字受控失败）。
5. 二进制成功状态却返回 JSON/HTML，错误 Blob 非 JSON，浏览器提前卸载：不保存错误页、不泄漏原文、不遗漏 URL 清理（Task 5）。

---

## 文件边界与当前依据

新增业务文件均按单一责任拆分，不重构既有生成/审核模块：

- `apps/sales/services/solution_export_guard.py`：只读 actor/状态/来源检查与一致性指纹。
- `apps/sales/services/solution_export_document.py`：不可变文档值类型、版本适配、章节/引用映射。
- `apps/sales/services/solution_export_docx.py`、`solution_export_pdf.py`：各格式 renderer；`solution_export_rendering.py`：公共大小限制与渲染分派。
- `apps/sales/api/solution_export_views.py`：只读 HTTP 合同；修改 `apps/sales/api/urls.py` 注册。
- `apps/sales/assets/fonts/`：静态 TTF、OFL、来源 manifest；`scripts/prepare_solution_export_font.py`：一次性可重现资产准备。
- `frontend/src/api/solutionExports.ts`：认证二进制下载/错误解码；`frontend/src/utils/download.ts`：本地 Blob 保存；修改 `SolutionDetailView.vue` 和 `utils/errors.ts`。
- 新增本计划各任务列明的测试，不修改旧测试使其“适配”安全规则变化。

已核对可复用的真实符号：`visible_solution_drafts_for`、`deserialize_solution_payload`、`evaluate_solution_draft_stale_reasons`。后者没有检查零 provenance 与尚未分析的原需求变化，不能当作全部导出 gate；不使用会写元数据的 `refresh_solution_draft_staleness`。V1 provenance 路径目前来自 `_iter_cited_statements`：`executive_summary[i]` 与 `solution_sections.{key}.statements[i]`，适配器严格保留这两种路径，不猜测 JSON 索引。

GitNexus 当前查询因 storage 43/runtime 42 失败，图谱覆盖 UNKNOWN；不重建索引，不把失败查询说成已完成影响分析。当前 source/tests 是实施真源。

## 执行与测试前置

所有后端命令在项目根目录执行，使用 `.\.venv\Scripts\python.exe -B`，现有 Python 3.12.14。数据库测试先仅将 `.env` 的 `DATABASE_URL` / `TEST_DATABASE_TEMPLATE` 加载至当前测试进程环境，不打印、不修改文件、不向测试导入真实模型密钥；`config.settings.test` 保留清空 verifier/checkpoint 配置。不得同时运行多个 pytest 数据库套件。

前端命令在 `frontend` 执行。所有新文件通过 apply_patch 创建；依赖安装/字体格式转换属于获准实施阶段的运行步骤，本计划阶段不执行。

### Task 1: 建立只读准入快照与完整引用校验

**Files:** Create `apps/sales/services/solution_export_guard.py`; Test `apps/sales/tests/test_solution_export_guard.py` and `apps/sales/tests/export_fixtures.py`.

**Interfaces:**
- Produces frozen `ExportSnapshot`：`solution_id, version, schema_version, analysis_id, created_by_id, created_at, approval_id, reviewer_id, approved_at, exported_at, title, domain, sources, fingerprint`；domain 为现有严格 V1/V2 对象，sources 为冻结的 durable provenance 值。内部快照可用于复核，不直接序列化为下载正文。
- `load_export_snapshot(*, actor_id: int, solution_id: int, exported_at: datetime) -> ExportSnapshot` 每次从 DB 重新加载 actor 和对象；`SolutionExportError(code: str, status: int)` 只允许 spec 受控值。不可见使用既有 NotFound，角色拒绝使用 PermissionDenied。
- `revalidate_export_snapshot(snapshot: ExportSnapshot, *, actor_id: int) -> None` 重新调用同一完整检查并使用原 exported_at 比较指纹；差异 `solution_export_changed`。Task 4 消费这两个接口。

- [ ] **Step 1 — 写 RED 测试和专用 fixtures。** 在 `export_fixtures.py` 定义 `make_export_case(schema_version: int) -> ExportCase`（owner、独立 reviewer、opportunity、analysis、solution、approved_review、document、chunk、fact、provenance），由已有合法 domain fixtures 和真实持久化/review 服务创建测试数据，再设置 matching raw requirement；不要使用生产记录。覆盖 `test_export_requires_completed_approval`（投影 approved、无已决定 approval ->409）、`test_export_does_not_authorize_staff_flags`、`test_independent_version_reviewer_can_export_only_assigned_version`、`test_raw_requirement_drift_rejects_export`、`test_old_valid_approved_version_is_not_rejected_only_by_version_number`。

```python
case = make_export_case(schema_version=2)
case.approved_review.delete()  # 仅测试库；仍保留 approved 投影。
with pytest.raises(SolutionExportError) as caught:
    load_export_snapshot(actor_id=case.owner.pk, solution_id=case.solution.pk, exported_at=timezone.now())
assert (caught.value.code, caught.value.status) == ('solution_export_not_approved', 409)
```
- [ ] **Step 2 — 确认失败。** Run `.\.venv\Scripts\python.exe -B -m pytest apps/sales/tests/test_solution_export_guard.py -q --tb=short`；预期因新模块/接口不存在失败，不能把数据库连接错误当作 RED。
- [ ] **Step 3 — 实现完整 gate。** 最新有效 approval 按 `decided_at,id` 排序，status 为 APPROVED 且 decided_at 非空。检查已存 stale 和 pure computed stale；比对 raw requirement。V2 对所有 claim 的 citations 生成 `(claim_id,label)` 期望集合；每行还须有准确 `claims.{claim_id}` path，不允许未知 claim/label。V1 对每个 cited statement 的现有路径生成 `(statement_path,label)`；允许同一 pair 的多个不同 fact，拒绝重复同 fact 行，期望与实际 pair 集合严格相等。复用 pure stale 检查每行 fact/document/chunk/index/hash/excerpt；fact 不能被替换为仅 label 相同的其他来源。
- [ ] **Step 4 — 增加边界测试并 GREEN。** `test_missing_and_extra_provenance_fail_closed` 参数化 V1/V2、缺/多/错路径；`test_multiple_facts_per_citation_are_preserved`；`test_new_analysis_revoked_fact_changed_index_and_chunk_reject`；`test_snapshot_is_read_only_and_has_no_provider_calls` 断言业务表计数/相关字段不变，provider 构造 monkeypatch 为一旦调用即失败。指纹用 canonical JSON + SHA256，覆盖 actor role/active、决定可见性的 owner/assignment/reviewer、方案全 payload/metadata、analysis/raw matching、approval、所有来源使用字段/状态/hash，包括标题；不把 source excerpt 写日志。再次运行 Step 2 全绿。
- [ ] **Step 5 — 局部检查。** `git diff --check`，记录本任务新文件与 RED/GREEN 证据，不提交。

### Task 2: 将 V1/V2 完整适配成共享文档

**Files:** Create `apps/sales/services/solution_export_document.py`; Test `apps/sales/tests/test_solution_export_document.py`.

**Interfaces:** Consumes Task 1 `ExportSnapshot`。Produces `build_export_document(snapshot: ExportSnapshot) -> ExportDocument`；所有类型为 frozen dataclass/tuple：`ExportDocument(title, metadata, disclaimer, sections, source_index)`，metadata 为 `(label,value)` tuples；`DocumentSection(title, blocks)`；`DocumentBlock(kind, text, rows)`，kind 为 paragraph/list/table，rows 为 tuples of cell strings；`ExportSource(label, document_id, title, statement_ids)`。renderer 只消费这个投影，不再查询 DB。

- [ ] **Step 1 — 写内容 RED 测试。** `test_v2_projection_has_all_sections_and_relationships` 断言 12 个 spec 正文章节（客户事实/未确认事项同属客户背景）、所有 claim 原文/ID/标签、component/flow端点方向、phase任务/责任/依赖/验收/timing分类、risk各引用、milestone关系均出现在对应块，不只是 dump JSON。`test_v1_projection_preserves_five_sections_and_summary_aliases`；`test_equal_text_claims_keep_distinct_identity_and_sources`；`test_projection_omits_private_excerpt_raw_requirement_and_review_comment` 使用不同唯一 sentinel 检查未出现；固定声明按 Global Constraints 原文完全相等。

```python
document = build_export_document(snapshot)
assert len(document.sections) == 12  # 来源附录另存 source_index。
assert '客户原文-PRIVATE-SENTINEL' not in repr(document)
assert '来源摘录-PRIVATE-SENTINEL' not in repr(document)
```
- [ ] **Step 2 — 确认 RED。** Run `.\.venv\Scripts\python.exe -B -m pytest apps/sales/tests/test_solution_export_document.py -q`。
- [ ] **Step 3 — 实现版本适配。** V2 每个结构显式按现有 dataclass 字段映射，不遍历任意 dict 静默吞字段；claim ID -> exact text/type/requirement fields/citations，relation ID ->显式确定性关系。公共 metadata 限制为 spec 页首 ID/版本/时间，无额外 Customer/Opportunity 查询。V1 使用原五个章节、summary/assumptions/path。sources 聚合 exact label+document ID，保留多个文档/事实绑定及 statement IDs，不能按 label 单一 dict 覆盖。对未引用但已保存的 claim 在其类别所属章节保留，防止获批正文丢失。缺对象拒绝 invalid_payload。
- [ ] **Step 4 — GREEN。** 增加 `test_projection_fails_on_missing_referenced_object` 与 `test_projection_has_no_current_opportunity_enrichment`，运行 Task 1/2 测试均通过。
- [ ] **Step 5 — 局部检查。** `git diff --check`，对照 spec 第 4 节逐项记录投影覆盖，不提交。

### Task 3: 真实双格式 renderer、字体和大小上限

**Files:** Create `solution_export_docx.py`, `solution_export_pdf.py`, `solution_export_rendering.py`（均位于 `apps/sales/services/`）；Modify `requirements/base.txt`; Create `scripts/prepare_solution_export_font.py`, `apps/sales/assets/fonts/{NotoSansSC-Regular.ttf,OFL.txt,manifest.json}`; Test `apps/sales/tests/test_solution_export_renderers.py`.

**Interfaces:** Consumes Task 2 `ExportDocument`。`render_docx(document: ExportDocument) -> bytes`、`render_pdf(document: ExportDocument) -> bytes`；公共 `render_export(document: ExportDocument, *, file_type: Literal['docx','pdf']) -> bytes` 分派；`MAX_EXPORT_BYTES = 10 * 1024 * 1024` 和 `BoundedBytesIO` 对 write/truncate/seek 后 extent 超限拒绝。renderer 不持有 snapshot/actor/DB，不调用网络。

**Locked assets/dependencies:** 在 base 追加 `python-docx==1.2.0`、`reportlab==5.0.1`，不升级已有依赖。字体准备工具仅在实施资产阶段使用 `fonttools==4.60.1`（不加入应用运行依赖）。Google Fonts 修订 `a85815a42757630ce188fdad368c2dfc444d4773`，文件 `ofl/notosanssc/NotoSansSC[wght].ttf`，17772300 bytes，SHA256 `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`；同修订 OFL 一起存档。固定 `wght=400` 全字符实例化、不 subset 原资产；manifest 保存输入 hash/修订/轴/tool版本及生成静态资产 hash，运行按 manifest 核对静态资产。不得 runtime 下载。版本/资产已查询官方发布与 immutable URL；真正相容性由本任务安装和生成测试证明。

- [ ] **Step 1 — 写 renderer RED 测试。** `test_docx_is_real_a4_document_with_complete_content_and_page_fields` 用 zipfile/pypdf 同级已有工具先检查结构，再安装后用 Document 读回正文/表格/页眉 PAGE 字段；`test_pdf_embeds_cjk_font_and_preserves_text` 读回所有中文字/首尾 sentinel，断言 embedded font；`test_special_characters_are_plain_text_not_markup` 用 `<>&`/URL sentinel，无外部关系或网络调用；`test_font_missing_or_unsupported_glyph_fails_safely` ->503，无成功文件。Run `.\.venv\Scripts\python.exe -B -m pytest apps/sales/tests/test_solution_export_renderers.py -q`，确认新增代码缺失的 RED。
- [ ] **Step 2 — 安装/准备资产。** 按已锁定版本安装应用依赖，`pip check`；先通过 apply_patch 写 asset preparation 脚本（默认读取明确输入文件路径/输出目录参数，拒绝哈希不符/覆盖非目标资产），再执行获得二进制 TTF；作为资产机械转换，禁止用 shell 文本写二进制。脚本生成 manifest，检查 TTFont 有 glyf、无 fvar，ReportLab TTFont 能注册；保留 OFL。应用启动可不加载可选 renderer，缺依赖时请求返回503而非使整个 Django 无法启动。
- [ ] **Step 3 — 实现 renderers。** DOCX 普通 runs，中文 eastAsia 字体 Noto Sans SC、fallback，A4、20mm边距、11pt正文、heading层级、页眉版本/页脚 PAGE、表格允许跨页但短标题不孤页。PDF Platypus、embedded TTF、Paragraph escape/换行、CJK wordWrap、可拆分长文本/大表格（不将整章节 KeepTogether），长连续字串可折行。所有 text glyph 校验，缺字整体 unavailable，不替换成方块。PDF subset 只由 renderer 在文件内完成。使用 BoundedBytesIO 避免先无限增长再检测；超限 too_large。
- [ ] **Step 4 — GREEN/长内容。** 增加 `test_many_pages_keep_final_source_and_long_table_cell`、`test_exact_size_boundary_and_growth_after_seek`（limit 和 limit+1）、`test_renderers_do_not_query_database`，运行 Task 1–3 测试。测试真实中文，不依赖开发机系统字体存在；失败不得自动换字体或降级内容。

```python
assert render_docx(document).startswith(b'PK')  # 还必须用 Document 解析，不止 magic。
pdf = render_pdf(document)
assert pdf.startswith(b'%PDF-')
assert '中文正文末尾-SENTINEL' in ''.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
```
- [ ] **Step 5 — 版式验证。** 主执行者先完整读取当前 documents/pdf 技能与必要参考，使用其工具将 DOCX/PDF 渲染为逐页图像，检查全部页的中文、首尾、表格/列表跨页、页眉页码、声明、来源。QA 可用本地转换工具，生产无 Office/LibreOffice 依赖；若本机无法 render DOCX，标明验收未完成并寻求明确工具安排，不只用 XML/PDF header 宣布完成。
- [ ] **Step 6 — 局部检查。** `git diff --check`、manifest 哈希/OFL/package check 记录，不提交。

### Task 4: 下载 API 和返回时复核

**Files:** Create `apps/sales/api/solution_export_views.py`; Modify `apps/sales/api/urls.py`; Test `apps/sales/tests/test_solution_export_api.py`.

**Interfaces:** `SolutionExportAPIView.get(request, solution_id: int) -> HttpResponse`；consumes Task 1/2/3 接口，按 spec 错误返回 `{code: <controlled code>}` JSON。路由名 `solution-draft-export`。冻结 `exported_at=timezone.now()`，重验时同值。PDF MIME `application/pdf`，Word MIME `application/vnd.openxmlformats-officedocument.wordprocessingml.document`。

- [ ] **Step 1 — 写 API RED。** `test_approved_visible_version_downloads_both_formats` 参数化 docx/pdf，assert200、exact MIME、ASCII attachment、private/no-store、nosniff、真实可解析 bytes；`test_anonymous_and_invisible_are_not_downloads` assert401/404；`test_export_uses_file_type_not_format` assert缺少/重复/非法 file_type400，POST405；`test_export_does_not_refresh_or_mutate_stale_metadata` assert0业务 writes。Run `.\.venv\Scripts\python.exe -B -m pytest apps/sales/tests/test_solution_export_api.py -q`，确认路由不存在 RED。
- [ ] **Step 2 — 最小实现。** 新 APIView 使用 SolutionDraftPermission，snapshot service 仍重新核验 actor active/role；先确认可见再回状态/参数错误，避免泄漏。先 load、build、render，渲染期间无 atomic/行锁；之后短 `transaction.atomic()` 调用 revalidate，再在退出边界构造普通 HttpResponse（非 Streaming/FileResponse）。最终校验时点是效力边界，不宣称阻止校验后的所有变更。HTTP层不暴露异常 detail/cause；dependency/renderer错误503，受控业务错误按 spec，Unexpected错误安全日志无栈正文。GET/HEAD 可支持，HEAD遵守同gate不返回body；禁止接受客户端正文/force参数作为行为控制。
- [ ] **Step 3 — 在 renderer 边界变更后 GREEN。** `test_revoke_fact_during_render_returns_no_binary`、`test_change_payload_or_document_title_during_render_returns_changed`、`test_role_or_assignment_change_during_render_denies_download`：包装真实 renderer，在其返回前更新测试记录，期望409/403/404且 JSON、无 attachment。`test_renderer_runs_outside_long_transaction` assert非atomic；`test_no_source_excerpt_or_internal_comment_in_response`。Run Task 1–4 套件全绿。

```python
# renderer hook 先撤销本 case 的 fact，再返回真实 PDF。
response = client.get(f'/api/solution-drafts/{case.solution.pk}/export/?file_type=pdf')
assert response.status_code == 409
assert response.json()['code'] == 'solution_export_stale'
assert 'Content-Disposition' not in response
```
- [ ] **Step 4 — 局部检查。** 确认 route 的 retrieve 不被调用、无工作流/resume/get_model路径、无新模型/迁移；`git diff --check`，不提交。

### Task 5: 前端下载入口、认证和错误体验

**Files:** Create `frontend/src/api/solutionExports.ts`, `frontend/src/utils/download.ts`; Modify `frontend/src/views/SolutionDetailView.vue`, `frontend/src/utils/errors.ts`, `frontend/src/stores/auth.ts`; Test `frontend/src/test/solution-export.spec.ts`, `frontend/src/test/auth.spec.ts`.

**Interfaces:** `SolutionExportFormat = 'docx'|'pdf'`；`fetchSolutionExport(id: number, version: number, fileType: SolutionExportFormat, signal?: AbortSignal): Promise<{blob: Blob; filename: string}>`，用既有 `http.get` 的 responseType blob，固定 filename由已选id/version构造；匹配 MIME及非空/max10MiB，错误 JSON Blob规范化成既有 safeError 接受的 `{response:{status,data:{code}}}`。`saveDownload(blob: Blob, filename: string): void` 创建 anchor/Blob URL，执行点击并清理（延迟释放满足浏览器消费，失败/卸载也释放）。不改认证桥默认语义。

- [ ] **Step 1 — 写 UI/API RED。** `approved_current_version_offers_word_and_pdf`、`draft_pending_returned_and_stale_disable_export`、`double_click_is_one_request`、`binary_json_or_html_is_not_saved`、`error_blob_is_controlled_message_without_server_text`；mock URL.createObjectURL/revokeObjectURL/anchor.click，验证两种下载；assert error 文案不出现“生成请求/补客户条件”。Run `npm.cmd test -- --run src/test/solution-export.spec.ts`，观察缺入口/模块 RED。
- [ ] **Step 2 — 实现 API 和 save utility。** 复用 http JWT/session interceptor；error Blob decode仅 JSON且有限大小（64KiB），只读 code不显示 message/detail；无效内容选本地受控 unavailable。401既有同epoch refresh可重放一次，不新建循环；网络无HTTP也使用下载专用固定提示。success MIME为application/pdf或application/vnd.openxmlformats-officedocument.wordprocessingml.document，Content-Disposition不直接作为不可信路径。AbortController 可取消离页请求，浏览器不支持也依 generation/epoch 检查拒绝消费。
- [ ] **Step 3 — 实现按钮和消费时保护。** 刷新旁放“导出 Word”“导出 PDF”，`approved && !is_stale`+busy/loading/exporting禁用；独立exportbusy/error不改变审核权限。请求捕获当前 `auth.sessionEpoch()`、route solution ID、draft version和递增下载请求序号，await完毕再检查相等及mounted才save；refresh/route/session/unmount取消并使旧序号失效，不能仅比userID。当前 auth store 的 epoch 只供 http bridge使用，未对页面暴露；本任务追加 `sessionEpoch(): number` 只读方法并在 auth tests 证明logout/login递增、不泄漏token。
- [ ] **Step 4 — 错误映射和 GREEN。** utils/errors追加所有spec export code的固定中文提示，409“方案状态、需求或依据已变化，请刷新并核对；未导出文件”，422区分格式/大小、503提示服务；不自动load后循环导出。新增 `same_account_relogin_suppresses_old_download`、`route_change_refresh_and_unmount_suppress_old_download`、`url_is_released_when_click_throws`、`401_refresh_only_for_same_epoch`，运行本文件及auth/workflow测试，然后 `npm.cmd run build`。

```typescript
// 测试已点击导出、退出并重新登录同账号，再 resolve 原下载 Promise。
expect(anchorClick).not.toHaveBeenCalled()
expect(createObjectURL).not.toHaveBeenCalled()
```
- [ ] **Step 5 — 局部检查。** 错误不落入生成fallback、token不入URL、无失效请求下载/修改新页busy，`git diff --check`，不提交。

### Task 6: 回归矩阵与实际文件验收

**Files:** Test `apps/sales/tests/test_solution_export_revalidation.py`; Modify `docs/architecture.md`, `docs/business-rules.md`, `docs/local-configuration.md`, `README.md`; Create `docs/solution-export.md`.

**Interfaces:** 不新增生产接口。文档说明 Task 1–5 实际功能和as-of最终检查效力边界；不宣称客户验收/永久有效/生产SLA。

- [ ] **Step 1 — 写返回时矩阵 RED 测试。** 真实renderer包装参数化：actor inactive/role变更、owner或presales/reviewer归属变更、approval/projection撤回、raw requirement、新analysis、payload、缺provenance、fact审批/stale、index/chunk/hash/excerpt、来源标题；一律无成功附件。指纹与gate未覆盖的情况先失败，按Task 1对应实现最小修正，不改变全局policy。

```python
assert response.status_code in {403, 404, 409, 422}
assert response['Content-Type'].startswith('application/json')
assert 'Content-Disposition' not in response
```
- [ ] **Step 2 — GREEN及安全自检。** 本任务测试通过；同文不同ID/多事实、历史有效获批、真实V1/V2、全部下载无业务 writes/providercalls。保存差异证据，检查新模块无额外商机查询/网络资源/异常正文日志；不复用详情GET的mutating refresh。
- [ ] **Step 3 — 完整回归。** 顺序运行 `.\.venv\Scripts\python.exe -B -m pytest -q --tb=short`；`npm.cmd test -- --run`；`npm.cmd run build`；Django check、makemigrations --check --dry-run、`git diff --check`。报告真实计数和任何既有基线失败，不以旧2684/119计数替代当前验证。
- [ ] **Step 4 — 实际151验收。** 获准实施后只重启已核实本项目backend进程加载代码，不碰数据库服务；真实用户登录，用按钮下载151两种格式。若此时非有效approved，报告状态原因、不改数据/审批/模型重生成。比对两格式与保存version/payload/来源，按Task 3逐页visual QA，证据置ignored本地验收目录，不入业务数据库/公开目录，不日志输出token/正文。
- [ ] **Step 5 — 文档和独立评审。** 更新新功能操作/权限/错误/依赖/fonts/OFL/10MiB部署打包说明（字体必须随部署复制），mainagent读取 requesting-code-review技能并按所选执行方式安排只读审查新diff及保护规则；不得把整个dirty worktree归为本任务。修复发现后重跑受影响+完整验证；没有实际下载/逐页QA证据则明确尚未完成。
- [ ] **Step 6 — 用户交付。** 给实际可用入口、已验证格式、限制、当前样例状态及未完成项；保留所有改动、不提交。没有下载成功证据不能宣布功能已完成。

## 自检与覆盖

Spec 1/3 ->Task1/4；Spec4 ->Task2；Spec5 ->Task1/4/6；Spec6 ->Task3/4；Spec7 ->Task4/5；Spec8 ->Task1–6。Review Focus 五类分别有具名测试。接口均由上游Task定义，renderer只收ExportDocument、HTTP只输出validated bytes。当前没有并行执行要求；建议 Native，六个任务接口紧密，顺序TDD实施后一次独立整体审查，比每步切换执行者开销更小。

**阶段门槛记录：计划经用户审阅并选择 Native 后实施；保留用户现有目录和改动、不提交、不合并。实际执行记录保存在 `.superpowers/sdd/2026-10-14-approved-solution-export/progress.md`，含偏差判定、测试和验收证据。**

## 核对来源

- [python-docx 1.2.0 发布记录](https://pypi.org/project/python-docx/1.2.0/)、[ReportLab 5.0.1 发布记录](https://pypi.org/project/reportlab/5.0.1/)、[fonttools 4.60.1](https://pypi.org/project/fonttools/4.60.1/)。
- [已固定字体/OFL目录修订](https://github.com/google/fonts/tree/a85815a42757630ce188fdad368c2dfc444d4773/ofl/notosanssc)；字体 hash 本轮通过读取该immutable URL bytes计算，不持久化字体资产。
