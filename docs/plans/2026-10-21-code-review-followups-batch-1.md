# SalesMind AI 审查后续修复批次 1（交实施 agent 执行）

- 制定日期：2026-10-21
- 输入：本仓库当日两份审查（一份内联审查 + 一份外部 `code-review-2026-10-21.md`）合并复判后的结论
- 分支：`codex/phase-five-presales`；工作树当前 **139 个文件未提交**，本批次不新增未提交项以外的大改动
- 已完成、不要重做：语义否决 REST 422、`reviewer_id` 存在性预言机合并、生成侧锁序 documents→facts + `order_by("pk")`、工作流 except 补 `django.db.OperationalError`（对应测试文件 `test_solution_failure_surface_contract.py`、`test_solution_workflow_database_failure.py`、`test_solution_admission_lock_order.py`）

## 0. 执行环境与前纪律

1. 每个 shell 调用都要重新注入环境变量，否则 `config.settings.test` 直接 `ImportError: Set the DATABASE_URL`，连 `--collect-only` 都跑不起来：
   ```bash
   cd "D:/pycharm-project/SalesMind AI" && set -a && . ./.env >/dev/null 2>&1; set +a
   ./.venv/Scripts/python.exe -m pytest -q --reuse-db        # 全量约 10 分钟
   ```
2. **用例数只信 `pytest --collect-only -q`**。`grep "def test_"` 会把 `.venv` 里第三方测试算进来。当前基线：**2897 passed / 0 failed**。
3. 不要修改、重启、修复或替换 PostgreSQL 实例、端口、PID、角色、模板、扩展；测试库用现成的 `salesmind_test_template`（`--reuse-db` 足够）。本机 `pip-audit` 不可用且无网络，不要声称做过依赖漏洞扫描。
4. 不要改动 `docs/code-review-2026-08-29.md`。
5. **每项修复的验收都是同一套三步**：新测试先红 → 改实现转绿 → **把实现点重新改回缺陷形态，确认新测试必红**（不是"测试恒绿即通过"）。变异用临时脚本做，临时脚本放仓库根目录（Git Bash 的 `/tmp` 与 Windows 解释器路径不一致，`open('/tmp/x')` 会 FileNotFoundError 导致注入静默失败），用完删除。
6. 每项一个独立提交，消息沿用仓库现有 conventional commits 风格（首行祈使句、能独立检索），不要把 5 项混成一个提交。

---

## 任务 1（P1）受管 placement 必须携带非空 requirement linkage

**缺陷**：V2 proposal 合同要求 `related_requirement_fields` 键存在，但不要求非空；空数组让 unresolved 确定性守卫整体短路，`unresolved → confirmed` 的拦截对这条建议失效，只剩概率性 verifier。

**证据链（已逐行核实）**
- `apps/sales/services/solution_generation_contract.py:99-100`：`require_linkage=True` 时闭合键集为 `CLAIM_KEYS = {text, citations, related_requirement_fields}`（:51）。
- 同文件 `:135-143`：`fields = value.get("related_requirement_fields", [])` 之后只做「是 list / 元素是 str / 唯一 / 枚举合法」四件事，**没有非空判定**。
- `apps/sales/services/solution_unresolved_policy.py:75-78`：`unresolved = frozenset(... for field in related_fields ...)`，`if not unresolved: return None` → 空关联直接放行。
- 同文件 `:64-68` 的类型校验同样放过空 tuple。
- `apps/sales/services/solution_grounding.py:593-605` `_asserts_unresolved_as_confirmed`：`any(... for field in related_fields)`，空集合恒 False。

**执行点必须放在这里（关键，放错会打掉设计内用例）**
`apps/sales/services/solution_semantic_ir_v2.py` 的 `_convert.add(section, kind, key, field, value, path=...)`（:120-131 附近）——这里 `validate_claim_fields(...)` 用的是默认 `require_linkage=True`，且 **placement 三元组在同一个函数作用域内已知**。

**不要在 `solution_unresolved_policy.py` / `solution_grounding.py` 里加"空关联即拒绝"**：`apps/sales/tests/test_solution_proposal_admissibility_v2.py` 有 6 处（:680、:704、:710、:807、:822、:920）直接构造 `AtomicSolutionProposalV2` 并在受管 placement 上带 `related=()`，用来验证"这类声明能进入语义审查"。它们在合同层之外，策略层收紧会把它们的预期结果改掉。合同层执行则完全不受影响。

**规则**：对 `_TARGETS` 覆盖的 8 个 (section, container_kind, field) 组合（`solution_unresolved_policy.py:36-45`：implementation phase 的 objective/tasks/deliverables/timing、risk 的 condition/impact/mitigation、milestone 的 outcome），要求 `related_requirement_fields` **至少 1 项**，否则走 `reject_contract("invalid_requirement_link", path + ".related_requirement_fields", "at least one RequirementDimension", "empty")`。其余 placement（proposed_solution overview、architecture identity/responsibilities/rationale/interfaces、out_of_scope、assumptions、open_questions、acceptance 等）保持允许为空。

**必须保持不变的既有行为**
- 省略键 → 仍由 `closed_object` 报缺失（不要改成默认空）。
- 非空但引用了 analysis 中无上下文的维度 → 仍由 `solution_grounding.py:316` `_requirement_has_context` 处理，不要在本任务里搬。
- 类别名与 json_path 形态要与现有合同诊断一致（参考 `test_generation_contract_reliability.py`、`test_solution_semantic_ir_v2.py:721` 的 `invalid_requirement_link` 断言）。

**风险点（务必实跑确认）**
`apps/sales/tests/test_real_provider_pass_diagnostics.py:114-116` 用 `related_requirement_fields: []` 往 `proposed_solution` 追加 37 条来触发 `local_cardinality`。`proposed_solution` 不在 8 个受管组合内，规则正确地不该碰它——如果该用例失败，说明范围写宽了，收紧而不是改测试。同理检查 core/implementation/assurance 三段的 fixture 是否都带非空关联。

**回归测试**（新建 `apps/sales/tests/test_solution_ir_linkage_required.py`）
1. 参数化 8 个受管组合，各一条"空 linkage → `SolutionDraftError`，category `invalid_requirement_link`，json_path 指向该 claim"。
2. 非受管组合（至少 `proposed_solution.overview`、`architecture.components.identity`）各一条"空 linkage 仍然合法"，防止范围过宽。
3. 一条端到端：受管 placement 给非空 linkage 时转换照常成功，证明没误伤。

**可选的第二层（他们报告 §2 的可观测性，本批次可不做）**：目前空关联路径连 `record_rejection` 都不触发，运维看不到"零否决是因为没关联"。若做，只能记固定类别与计数，**不得记录模型原文、excerpt 或 offending id**（`docs/ai-pipeline.md:196` 明令）。

---

## 任务 2（P2 首位）审批期 stale 复检不得把瞬时误判永久落库

**缺陷**：审批/提交路径在只锁 draft 行的事务里，用多次独立查询算 stale，然后把结果**并集落库**；而并集按设计是单调不减的，于是一次跨快照读到的瞬时不一致会把一个合法版本永久打成 stale，之后审批与导出都拒绝，只能人工改库。

**证据链（已核实）**
- `apps/sales/services/solution_review.py:250-255`：`select_for_update(of=("self",))` 只锁 `sales_solutiondraftrecord` 行。
- 同文件 `:351-357` `_require_current`：调 `project_solution_draft_staleness(solution)` 后，若变化就 `solution.save(update_fields=["is_stale","stale_at","stale_reasons"])`；调用点 `:113`、`:271`。
- `apps/sales/services/solution_persistence.py:355-365` `project_solution_draft_staleness`：`dict.fromkeys([...已有..., *新理由...])` + `is_stale = is_stale or bool(reasons)`，docstring 自己写明 "an invalidated immutable version stays invalidated"（**单调是故意的**）。
- READ COMMITTED 下 `evaluate_solution_draft_stale_reasons` 分次读 provenance / document / chunk，并发 reindex 提交在两次读之间落库即可产出跨快照组合，误判 `GROUNDING_PROVENANCE_INVALID` 类理由。
- 仓库**已经有正确形状的 helper** `solution_persistence.py:370-383 refresh_solution_draft_staleness`（行锁内重读派生元数据再落库），但生产代码无人调用。

**两种解法，选一并把理由写进提交信息**
- A（推荐，改动小）：`_require_current` 不再自己 save，改为调用 `refresh_solution_draft_staleness`（行锁内派生+落库），并把 `evaluate_solution_draft_stale_reasons` 所需的来源读收敛到同一原子块内、按 **document → fact** 顺序加锁（与任务 4 已修的生成侧锁序一致，勿再造反序）。注意 `refresh_solution_draft_staleness` 自带 `transaction.atomic()`，在 `:271` 的外层原子内调用是嵌套 savepoint，语义可接受，但要确认失败时不会把已创建 review 一起回滚出非预期状态。
- B（更彻底）：审批期不落任何派生 stale，只做读时投影并据当前投影结果决定是否放行；`is_stale`/`stale_reasons` 列退化为纯派生缓存。代价是历史行的 stale 语义变化面较大，需先确认导出与前端仍按投影读。

**不得改动**：单调并集语义本身（`immutable version stays invalidated` 是有意的不可改写设计，`docs/architecture.md` 与 `docs/ai-pipeline.md:215` 都依赖它）；本任务要消除的是**误判进入落库路径**，不是让 stale 可被清除。

**回归测试**（新建 `apps/sales/tests/test_solution_stale_revalidation_atomicity.py`）
1. 模拟"读 provenance 与读 document 之间发生一次 reindex 提交"（用 monkeypatch 在第一次查询后触发另一个连接/另一次调用提交 `is_stale=True` 的 fact 变更），断言审批被拒的同时 `stale_reasons` **没有**被写入那条误判理由，或者按解法 A 在锁内重检后自愈。
2. 一条正向：真实的 reindex 失效仍应落库为 stale 并阻断审批与导出。
3. 一条防退化：GET 列表/详情路径（`solution_draft_views.py:74-76`、`:128` 用 `project_`）**不得写库**，用查询捕获或 `refresh_from_db` 断言列值不变。

---

## 任务 3（P1）速率限制

**缺陷**：全仓无任何 throttle（`grep -i throttle` 命中 0），`config/settings/base.py:132-139` 的 `REST_FRAMEWORK` 只有认证与权限两项；登录/刷新是 AllowAny。2026-08-29 报告的 P1-3 至今未修。

**要求**
- `base.py` 增加 `DEFAULT_THROTTLE_CLASSES` / `DEFAULT_THROTTLE_RATES`，速率值走 `env.int`/`env` 读配置，**production 下缺失即崩**，不要写死默认字符串（对齐 `production.py:10-16` 的 fail-closed 风格）。
- 登录与刷新用 `ScopedRateThrottle` 单独更严（按 IP 或 anon），方案生成/需求分析/`/api/rag/answer/`/`reindex` 这类真实烧额度或长同步的端点各自独立 scope。
- 需要 cache 后端：确认 `config/settings/base.py` 现有 CACHES 情况后再定 throttle 存储，不要默认依赖 LocMemCache 的多进程一致性——把"限流在多 worker 下不全局精确"写进 `docs/known-limitations.md`，别在文档里声称全局保证。
- 测试：至少 `login` 与 `solution-draft-list`（生成）各一条"超阈值 429 + 结构化 code"，以及一条"阈值内不误伤"。

## 任务 4（P2）前端两行

- `frontend/src/utils/download.ts`：`window.setTimeout(() => URL.revokeObjectURL(url), 0)` 在点击后立即撤销，Firefox/Safari 与大文件可能尚未开始读 blob。该文件头注释写的是 "revoke the URL after browser consumption"，注释与实现不符。改为延时 ≥1s 或窗口 `focus` 后撤销，并让注释与实现一致。测试放 `frontend/src/test/`，用注入的 URL mock 断言撤销时机。
- `frontend/src/stores/auth.ts:16`：`logout()` 递增 `epoch` 但不清 `refreshing`。旧 refresh 仍在飞行时登出并重登，新会话首个 401 会 `if (refreshing) return refreshing` 复用旧 promise，旧 promise 因 epoch 变化抛 `session_changed`，`api/http.ts` 判定后 `expire()` 把新会话踢出。修复：`logout()` 里 `refreshing = undefined`，或用 epoch 包裹整个 promise 生命周期。补一条 `test/auth.spec.ts` 竞态用例（旧 refresh 未 settle → logout → login → 401 → 期望新 token 生效而非登出）。

## 任务 5（P2）唯一约束冲突返回 409 而不是 500

**缺陷**：生产代码里 `IntegrityError` 引用数为 0（仅测试出现），而数据库层有真实唯一约束，例如 `apps/sales/models.py:412` 的 `sales_solution_one_pending_review`、knowledge 的 `knowledge_extract_active_run_unique`。并发双击提交两次审核时违反部分唯一索引 → Django 未捕获 → HTTP 500。

**要求**：在受影响的写入入口把 `django.db.IntegrityError` 映射为已有的受控冲突状态（审核类 → 409 + 现有 `solution_review_*` code 中语义正确的那条；不要新造前端不认识的状态码除非同步改 `frontend/src/utils/errors.ts`）。保持 fail-closed 与事务回滚语义不变；`raise ... from exc` 时不要让原始 constraint 名进入响应体。测试：并发两次 `submit` 断言第二次 409 且只有一条 review。

---

## 明确划在本批次之外（不要顺手做）

1. **`processing` 状态崩溃回收**：语义未定——超时后自动归位（有成功 run → READY，从未成功 → FAILED）还是只给人工入口，等用户拍板。
2. **checkpoint 正向分叉恢复**：涉及"人工 POST 触发对账"的边界收窄（`can_recover_terminal_review_submission` 要求 `solution.reviews.exists() == False`，与 `docs/architecture.md:158` 只承诺不重置"已完成审核"之间存在落差），改动前应确认。
3. **`schema_version` 默认值 1→2**：61 个测试调用点吃这个默认值，属独立清扫。
4. **策略层收紧空关联**：会改掉那 6 处 admissibility 测试的预期，需作者表态。
5. 结构重构（`strict_json` 单入口、权限/错误类上移 `apps/common`、`qwen_*` 改名、拆 `solution_prompt_v2.py`）、性能类（embedding ANN 索引、列表 stale 重算 N+1、批量批准上限）各自另开。

## 交付要求

实施完给回：改动文件清单与每项的 file:line、**测试基线数字对比（2897 → N，不得减少）**、每条新测试的"注入缺陷 → 必红"记录、`manage.py check` 与 `makemigrations --check --dry-run` 结果（若动模型/迁移）、前端 `vue-tsc --noEmit` 与 `vitest run` 结果、**未做项与原因**、以及工作树状态与建议提交分组。

---

# 批次 1.1

已拆为独立方案文件，避免同一份规格存在两个落点：
[2026-10-21-throttle-identity-and-refresh-scope.md](2026-10-21-throttle-identity-and-refresh-scope.md)（匿名限流身份 `NUM_PROXIES` fail-closed、`refresh` 独立 scope、checkpoint 分叉记为已知限制）。
