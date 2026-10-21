# 方案待确认条件统一校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不授予事实或审批权限的前提下，统一 V2 规划表达判定，并准确区分客户缺信息与生成内容问题。

**Architecture:** 共享的有界表达解析器提供内部子句类型；纯策略模块结合可信 placement、原关联与冻结分析判断候选/拒绝/无法识别。生成指导从同一策略表派生；所有候选继续经过精度、语义否决、来源复核及正式保存。不得把内部分类当成模型输出意图授权。

**Tech Stack:** Python 3.12、Django/DRF、frozen dataclasses/StrEnum、pytest、现有 LangGraph 工作流、Vue/TypeScript/Vitest。无新依赖或数据库迁移。

**Spec:** `docs/superpowers/specs/2026-10-13-solution-unresolved-policy-design.md`。

状态：用户已批准并选择现有目录顺序实施。Task 1–6 已实现并验证；Task 7 回归通过，用户手动重启后已进行一次真实调用，仍在 objective 的需求关联检查处拒绝，未保存新方案，已停止重试。详细证据见本计划对应的 `.superpowers/sdd` 执行记录。

## Global Constraints

- 不新增模型输出字段或模型自报的安全意图标签，不自动给原文添加条件或修改关联。
- 不自动修补 JSON、替换引用、拆分文本、添加免责声明或删除失败条目。
- 不增加生成预算、尝试次数、模型调用或 provider fallback。运行链路不新增分类模型。
- 无数据库迁移、历史重写、角色权限调整或 PostgreSQL 实例操作。
- semantic verifier remains veto-only；候选不等于准入，需求状态不晋升。
- citations、approval/status/current-index/hash、precision、return-time provenance、stale、自审与权限检查保留。
- V1 保留旧路径；readiness 与商业不确定性规则不变；新策略不能覆盖冲突阻断。
- 影子比对不改变正式决策。无法可靠识别的表达失败关闭，不交由模型批准。
- 保留现有脏工作区、`.workbuddy/` 和 `docs/code-review-2026-08-29.md`。不自动 reset、覆盖、stage 或 commit 用户改动。
- 当前合同上限仍为 Core 46、Implementation 18、Assurance 20、global 84、components 4；6,000 output tokens/pass，结构拒绝最多两次 attempt。

## Review Focus

1. “核验完成”与“核验通过”混用：Task 1/2 成对测试；部署结果依赖不能由前者释放。
2. 关联清空或错挂已知 business_goal：Task 2/4 检测明确对象依赖的错误关联，拒绝而不补写字段。
3. 父级核验目标加子项既成结论：Task 2/4 每个原始 claim 独立判断；上下文不能豁免。
4. 首次 HTTP 422 与重放 HTTP 200 FAILED：Task 5/6 同类别、同幂等 key、无新模型调用/方案/导航。
5. 并发请求日志串号及敏感 excerpt：Task 5 ContextVar 隔离、finally reset、UUID 类型校验、普通日志排除正文和 container_key。

## Phase 0：当前源码与允许接口（已完成只读核查）

两项独立 Documentation Discovery 已核实以下接口；执行者仍须阅读相应源码和本 Spec。

| 当前接口/范例 | 来源 | 用途 |
| --- | --- | --- |
| `clear_clarification_action(text) -> bool`、`scoped_statements(text) -> tuple[str,...]` | `solution_clarification_actions.py:48-55` | 复用对象、环境限定语与完整子句机制 |
| `conditional_parts(text)`、`normalized_consequence(text)`、`assertive_consequence(text)` | 同文件 `:58-72` | 借鉴前置/后果拆解，不复制成字段词表 |
| `_requirement_has_context(analysis, field)` | `solution_grounding.py:555` | 既有关联上下文验证，不能跳过 |
| `verify_atomic_solution_v2_proposals(*, analysis, proposals, sources, allowed_source_labels, llm_provider=None, diagnostics=None)` | `solution_grounding.py:239-472` | 保持返回原 proposals 及校验顺序 |
| `SolutionDraftGroundingError(code: SolutionGroundingErrorCode, *, violations=())` | 同文件 `:149-171` | 构造参数为 enum；公开 code 为固定字符串 |
| `_log_proposal_rejection(*, proposal_index, placement, related_fields, citation_count, stage, reason_code, guard_name, decision=None, atomicity=None)` | 同文件 `:701-730` | 普通日志仅投影 enum 位置/序号，不用 evaluation safe_dict |
| `SolutionV2Placement`、`AtomicSolutionProposalV2`、`AtomicSolutionProposalSetV2` | `solution_prompt_v2.py:147-174` | 原文、关联、引用与结构关系保持不变 |
| `_clarification_action_style_context(pass_name)`、`_semantic_pass_prompt(pass_name, ...)` | 同文件 `:852`、`:562` | 接入派生指导，保持 Core 无该指导 |
| `_generate_solution_node(state)`、`_failure(outcome,error_code)` | `solution_review_workflow.py:152-218`、`:482-487` | 已有 typed grounding code 保留路径与 checkpoint |
| `_business_projection(workflow_id,state,draft,*,actor=None)` | `api/solution_workflow_views.py:262-318` | 原 DTO 字段、FAILED 无 action、旧 checkpoint 不回填 |
| `safeError(error: unknown): string`、`generationNextAction(error)` | `frontend/src/utils/errors.ts:27-40` | 静态文案，不信任 message/detail |
| `_proposal`、`_AdmissibilityVerifier`、`_verify`、`partial_analysis` | `test_solution_proposal_admissibility_v2.py:47-122`、`test_solution_clarification_action_guard.py:27` | 复制真实 guard/外部 fake verifier 的测试接线 |

源码校正：milestone 只允许 outcome/timing（`solution_prompt_v2.py:211-214`、`solution_generation_contract.py:40`）；原 Spec 中 trigger/criterion 不是合法 milestone 字段。本计划仅接入 outcome，总计 **8 个合法组合**，不开放新输出位置；milestone timing 与 risk trigger 保留旧行为。

GitNexus 已绑定 SalesMind AI，但 index 43/reader 42 不兼容，graph 风险 UNKNOWN，未重建。以当前源码/测试替代导航，不声称图分析已通过。

## 文件与依赖边界

新增：`solution_plan_expressions.py`（有界子句解析）、`solution_unresolved_policy.py`（用途/状态策略及指导数据）、`solution_log_context.py`（UUID 日志上下文）。
修改：`solution_clarification_actions.py`（共享解析入口）、`solution_grounding.py`（V2 8 个组合接线及 typed codes）、`verifier_diagnostics.py`（明确拒绝类别）、`solution_prompt_v2.py`（输入指导）、`solution_review_workflow.py`（安全失败投影/日志 scope）、`frontend/src/utils/errors.ts` 与相应测试/文档。

新模块不 import `solution_prompt_v2` 或 `solution_grounding`，使用 primitive 三元组，避免 prompt→policy→prompt 循环。policy 可以 import requirement_analysis 的域类型；该模块含 Django/provider imports，不能宣称整个 import 链 stdlib-only，但求值函数不得执行 I/O。

fact admission、schema assembler、persistence、review、readiness 和生成合同不是改造对象；其测试是不可削弱的保护带。

## Task 1：共享有界表达解析器

**Files:** Create `apps/sales/services/solution_plan_expressions.py`、`apps/sales/tests/test_solution_plan_expressions.py`；Modify `solution_clarification_actions.py`。

**Interfaces（新增，不是当前 API）:**
- `PlanClauseKind` 成员 `INQUIRY/CONDITIONAL_WORK/PLANNED_ARTIFACT/HYPOTHETICAL_RISK/VERIFICATION_OUTCOME/ASSERTION`，value 为对应小写。
- `PlanPrerequisite` 成员 `NONE/COMPLETED/SATISFIED`，value 为对应小写。
- frozen `PlanClause(kind: PlanClauseKind, prerequisite: PlanPrerequisite = PlanPrerequisite.NONE, dependencies: tuple[str,...] = ())`；dependencies 仅为闭合对象词条确定产生的校验提示，不能写回关联。
- `parse_plan_expression(text: str) -> tuple[PlanClause,...] | None`；None 表示未完整识别。没有 raw text 或“已准入”字段。
- `clarification_object_sequence(text: str) -> bool` 在旧 clarification 模块提供共享对象序列入口；不改旧 `clear_clarification_action` 契约。

- [ ] 写 RED 表驱动测试：两个 OBSERVED 原句均为 inquiry；第二/第三对象限定语、4/5 个 ASCII 词、32/33 字符边界；并列核验动词复用同一对象解析。
- [ ] 成对固定 `核验完成后开展建设`→conditional_work/completed，`经核验确认部署条件满足后开展建设`→conditional_work/satisfied；`形成容量核验记录`、`容量核验记录`→planned_artifact；`若容量不满足，则试点部署可能受到影响`→hypothetical_risk；`完成容量核验并记录结果`→verification_outcome。
- [ ] 反例固定：句尾保证、已完成/已足够、假条件、否定核验、失败条件后仍建设、任意未知对象/残留片段不能变成安全节点。断言节点不可在 inquiry 分支吞掉。
- [ ] 在已安全设置测试连接的终端运行 `.\.venv\Scripts\python.exe -B -m pytest apps/sales/tests/test_solution_plan_expressions.py -q`，确认预期缺接口/行为失败，再实现最少解析。纯单元测试禁止 DB 访问；测试设置不读取本地 .env，不打印测试连接。
- [ ] 解析算法：逐完整子句消费；先匹配闭合核验对象与动词，再匹配明确前置关系、成果、假设风险、核验结果任务。并列动作只在完整合法子句边界识别；任何未消费片段返回 None，不忽略片段。明确结果断言返回 assertion，不因一个“若/是否”屏蔽另一段。前置对象不明确、只有完成事件时不能生成 satisfied。
- [ ] 在同一终结符表定义而不是逐句补丁：核验/评估动词复用旧闭合集合；环境 qualifier 支持现有/当前/目标/沿用及有界 ASCII 名称；阶段前缀为准备/建设/实施/部署/上线/验收/联调/试点 + 可选“阶段” + 前/期间；疑问对象为对象序列 + 是否/能否 + 满足 + 可选本期/平台/试点范围的 + 部署需求。ASCII 名称边界的空格不能全部删除来绕过词数限制。
- [ ] 环境/配置背景序列可带完整“对本期部署的承载条件”核验尾部；对象中的 PostgreSQL/pgvector 等 ASCII 名称只标识待核验对象，不证明存在/受支持。在分析匹配时允许 ASCII 名称外侧的空白，但原文不改写。
- [ ] 固定实际诊断变体的判定：`核验沿用环境的部署条件与服务器容量是否满足本期平台部署需求`、`评估现有服务器容量是否满足本期试点范围的部署需求`、`在建设阶段前核验部署条件并评估服务器容量是否满足本期部署需求` 均为 inquiry；配置背景序列仍须完整识别，否则 unclassified。不得因“可能”或前置免责声明忽略另一句“已经足够”。
- [ ] 完整消费仅用于内部分析，原 text 仍作为一条原 proposal 交给 atomicity verifier；不拆出新 claim。对象中的容量/部署提示 deployment_requirement，环境配置提示 existing_environment；不做通用自然语言维度推断。
- [ ] GREEN 后以内存 mutation 恢复旧首项限定语规则，确认原句测试变红，再恢复；只读评审此交付物。不得临时改生产文件后遗忘恢复。

## Task 2：统一纯策略与离线影子矩阵

**Files:** Create `apps/sales/services/solution_unresolved_policy.py`、`apps/sales/tests/test_solution_unresolved_policy.py`、`apps/sales/tests/test_solution_unresolved_shadow.py`。

**Consumes:** Task 1 的 `parse_plan_expression` / `PlanClause`。**Produces（新增）:**
- `PlacementKey = tuple[str,str,str]`。
- `PolicyDecision` 成员 `CANDIDATE/REJECT/UNCLASSIFIED`，value 为对应小写；`PolicyReason` 成员 `UNCONFIRMED_ASSERTION/UNQUALIFIED_PRECONDITION/EXPRESSION_UNCLASSIFIED/INVALID_LINKAGE`，value 为对应小写。
- frozen `UnresolvedPolicyResult(decision: PolicyDecision, reason: PolicyReason | None = None)`。
- `evaluate_unresolved_v2_policy(*, analysis: OpportunityRequirementAnalysis, related_fields: tuple[RequirementDimension,...], text: str, placement: PlacementKey) -> UnresolvedPolicyResult | None`；None 仅表示不适用，交回原 guard，不是直接准入。

**唯一目标表:** phase objective/tasks/deliverables/timing，risk condition/impact/mitigation，milestone outcome；均按完整 section/kind/field 字符串组合。

| 目标 | 可进入后续审核的内部用途 |
| --- | --- |
| phase objective/tasks、risk mitigation | inquiry、核验成果工作包、qualified conditional_work |
| phase deliverables | planned_artifact、verification_outcome |
| phase timing | conditional_work |
| risk condition/impact | hypothetical_risk |
| milestone outcome | verification_outcome、planned_artifact、qualified conditional_work |

- [ ] RED 测试：每个组合 × unknown/unclear/conflict × 合法用途/断言/无法识别；全 known 普通技术表述返回 None；不适用组合返回 None；维度/原文不可变。
- [ ] RED 示例必须直接调用新 API，期待字面值，不从 parser 生成预期结果：

```python
result = evaluate_unresolved_v2_policy(
    analysis=partial_analysis(), related_fields=(RequirementDimension.DEPLOYMENT_REQUIREMENT,),
    text="核验完成后开展建设。", placement=("implementation_plan", "implementation_phase", "timing"),
)
assert result.decision is PolicyDecision.REJECT
assert result.reason is PolicyReason.UNQUALIFIED_PRECONDITION
```

- [ ] 实现顺序：目标表查找→闭合对象的明确依赖与原关联核对→判断是否真正有非 known 关联→完整解析→逐节点用途与前置检查。明确指向未确认部署/容量却关联为空或只挂 business_goal 时 invalid_linkage；只拒绝，不补齐字段。不明确的对象提示不能擅自推断维度。
- [ ] 输入为空/非字符串、未知枚举/非法关联类型先失败关闭，不利用空集合全 known 的 vacuous truth 放行。已通过正式合法输入校验、无非 known 真实依赖时才返回 None。不会因有限语法无法理解正常的已知技术建议而新增拒绝。
- [ ] 非 known 的部署/环境/规模/集成/安全/技术约束关联存在时，conditional_work 不能由 completed 解锁；必须是明确确认/核验条件满足的 satisfied。inquiry 与报告记录不要求核验必定通过。仅 TIMELINE 未明确的 `确认完成后再上线` 保留现有条件排期含义，不把该案例泛化到未核验容量。
- [ ] assertion→reject，用途不匹配或任何未识别节点→unclassified；父级 objective/condition 不能成为例外；同一 claim 内任何拒绝节点优先于 candidate。
- [ ] 离线影子测试同时运行旧 helper 与新函数，不改正式调用、不调用 verifier；记录只含预期旧/新结果、enum 位置与类别。成对对照原拒绝片段与安全新表述，所有无依据断言/假条件/错挂关联必须仍拒绝。不得以影子结果保存方案。
- [ ] 运行新测试与三组既有 clarification 测试；修复代码而非删除负例；评审后进入接线。

## Task 3：从同一策略派生生成指导

**Files:** Modify `solution_unresolved_policy.py`、`solution_prompt_v2.py`、`test_solution_clarification_generation_guidance.py`；Create `apps/sales/tests/test_solution_unresolved_generation_guidance.py`。

**Interfaces（新增于 policy）:** frozen `PlanGuidanceExample(target: str, kind: PlanClauseKind, text: str)`；frozen `UnresolvedGenerationGuidance(targets: tuple[str,...], action_examples: tuple[str,...], result_counterexamples: tuple[str,...], field_examples: tuple[PlanGuidanceExample,...])`；`unresolved_v2_generation_guidance(pass_name: str) -> UnresolvedGenerationGuidance | None`。

- [ ] RED 测试：implementation targets 恰为 phases objective/tasks/deliverables/timing 和 milestones outcome；assurance 为 risks condition/impact/mitigation；Core 返回 None，不含标签。非法 milestone trigger/criterion、合法但未扩展的 milestone timing/risk trigger 不进入 targets。
- [ ] 从唯一 PlacementKey/用途表派生 targets 与字段范例。既有 `_clarification_action_style_context` 使用 `dataclasses.asdict(guidance)` 后继续 XML escape JSON；只扩展输入指导，不修改输出 contract/schema。保存原 action_examples/counterexamples，新增 field_examples 仅指导表达，不是声明已批准的结果。
- [ ] 更新 system 指导，明确完成/通过/满足、假设风险与未来成果；不得机械给无依据句子加“若”。测试删除系统指导的内存 mutation 不能仍全绿。
- [ ] 测试客户 requirements/value/evidence/conflicts/questions 与 prior validated pass 上下文逐项保持；所有指导键作为模型输出 extra keys 仍被 strict parser 拒绝。
- [ ] 与 `test_solution_requirement_design_scope.py`、`test_implementation_generation_guidance.py`、`test_solution_semantic_ir_v2.py` 一起运行；评审指导与真实解析器保持一致，不写只断言文本存在的空转测试。

## Task 4：V2 guard 接线及安全类别

**Files:** Modify `solution_grounding.py`、`verifier_diagnostics.py`、三组 clarification 测试与 `test_solution_proposal_admissibility_v2.py`；Create `apps/sales/tests/test_solution_unresolved_policy_integration.py`。

**Consumes:** Task 2 result。**Produces:** 原 `verify_atomic_solution_v2_proposals` 签名/返回对象不变；新增 `SolutionGroundingErrorCode` 成员：

- `UNCONFIRMED_ASSERTION = "solution_draft_unconfirmed_assertion"`。
- `UNQUALIFIED_PRECONDITION = "solution_draft_unqualified_precondition"`。
- `EXPRESSION_UNCLASSIFIED = "solution_draft_expression_unclassified"`。

三者均有固定 data-free safe_message。invalid_linkage 仍使用现有 INVALID_INPUT，语义否决仍使用 NOT_GROUNDED。diagnostics 新增 unqualified_precondition / expression_unclassified 两个 reason，明确断言保留 unresolved_as_confirmed。

- [ ] 先写实际 `_verify` RED：candidate 返回原对象、完整原文/关联/状态进入 packet；全部新用途均可被 INADMISSIBLE/COMPOUND、provider error 或无效 verdict 拒绝；每个未通过类别无 provider 调用。
- [ ] 在 citations/linkage 之后、precision 之前接 Task 2。result None 时沿用原 scoped/legacy guard；candidate 只继续，不提前 return；reject/unclassified 正式记录安全类别并抛 typed grounding error。保留 `_log_proposal_rejection` 对 enum 位置的校验，普通日志不能 dump evaluation safe_dict。
- [ ] 有意更新旧 exclusion 参数：phase deliverables 与 risk condition 不再是 blanket exclusion；architecture rationale、risk trigger、milestone timing、V1 仍保留原规则。非法 milestone trigger/criterion 的真实 parser 测试继续拒绝。
- [ ] 将旧 `若客户确认，配置2台服务器` 精度例与“不充分前提”区分：保留其拒绝；新增 `若经核验部署条件满足，则配置2台服务器` 证明实际 precision 分支仍拒绝无依据 2 台。不得把“仍失败”当作 precision 被保留的充分证据。
- [ ] 覆盖来源不准入、原文句尾承诺、已知/未知混合、强制清空关联、父级免责声明、return-time drift；不改变 packet context、架构 identity 原 atomicity 例外、并发/超时/预算。
- [ ] 运行全部 `apps/sales/tests` 相关套件及新增集成测试；审查新安全路径后才考虑加载应用。普通测试必须 fake 外部 provider，不能使用真实 credentials。

## Task 5：工作流错误投影与可关联的安全日志

**Files:** Create `apps/sales/services/solution_log_context.py`、`apps/sales/tests/test_solution_log_context.py`；Modify `solution_grounding.py`、`solution_review_workflow.py`、对应 workflow/API/logging 测试。

**Interfaces（新增）:** `@contextlib.contextmanager` 的 `solution_log_scope(workflow_id: UUID) -> Iterator[None]`、`current_solution_workflow_id() -> str | None`，基于 ContextVar，非 UUID 参数拒绝，不接受任意 string 为日志标识。

- [ ] RED：嵌套 scope、异常 finally reset、不同线程/context 隔离；普通日志存在合法 workflow UUID，但不含原文/source/container_key/Authorization/cause。复用 `_verify_bounded_packets` 已有 `copy_context().run`，不改调度。
- [ ] `_generate_solution_node` 在已解析的 workflow_key scope 中调用原持久化服务；异常日志使用局部已验证 UUID。`_log_proposal_rejection` 只在 context 有值时追加 workflow_id，直接 service 调用无值时旧投影保持。evaluation collector 的 excerpt 仍只用于受限评估，绝不复制到 API/普通日志。
- [ ] 扩展现有 `test_grounding_rejection_returns_422_and_terminal_replay_without_partial_rows` 到三种新 enum code：首个 422 恰 `{code,message}`，重放 200 FAILED/same error_code/no actions，生成一次、零 draft/provenance/review、私密 cause 不泄露。
- [ ] 为 Spec 的服务/格式分类保留 typed 错误：`LLMProviderError` 只允许公开 `LLMErrorCode` 的四个固定 code；`SolutionDraftErrorCode.INVALID_RESPONSE` 保留 `solution_draft_invalid_response`。其它未知/持久化/输入异常仍沿用安全 fallback，不投影任意 provider code、failure body 或错误 message。
- [ ] 上一条是**有意改变新工作流的 code 值**（原为 solution_generation_failed），不改变 HTTP/DTO 字段；更新 `test_workflow_logs_safe_original_failure_without_changing_failure_state` 的该项期待并保留 FAILED、零保存、无 traceback。历史失败 checkpoint 不重写，旧通用 code 继续可显示。
- [ ] readiness、insufficient approved evidence、权限、冲突与提交/退回路径仍保持原 code/行为；对所有新错误运行首次失败+幂等重放测试。来源变化与 SDK 错误不能被包装为客户澄清。

## Task 6：前端按类别说明下一步

**Files:** Modify `frontend/src/utils/errors.ts`、`frontend/src/test/errors.spec.ts`、`frontend/src/test/workflow.spec.ts`；AnalysisPanel/vue 与 workflow DTO 无需新增字段。

**Produces:** 原 `safeError` / `generationNextAction` 签名不变。

- [ ] RED 静态文案：unqualified_precondition 含“前提”“核验完成不等于条件满足”“未保存”；expression_unclassified 含“表达”“技术核对”“未保存”；unconfirmed_assertion 含“未确认”“断言”“未保存”；solution_draft_invalid_response 含“格式”“未保存”。不得含后台 message/detail/canary 或“补充客户需求”。
- [ ] 只扩静态 code 映射，保留旧 fallback。三个技术内容 code 的 `generationNextAction` 为 undefined；readiness 仍指向 requirement/overview；不制造不存在的诊断路由。
- [ ] 实际挂载 AnalysisPanel：首个 422 与后续 200 FAILED 的静态文案一致、同 key、不导航、不自动重试、不展示失败 claim 或新增待审核方案。
- [ ] 运行 `npm.cmd test -- --run`、`npm.cmd run build`；人工/组件测试确认“客户缺信息”和“生成表述需要修正”分开，不让销售重复填已经确认的内容。

## Task 7：完整验收、应用加载与受控真实流程

**Files:** Modify `docs/business-rules.md`、`docs/ai-pipeline.md`、`docs/known-limitations.md`；本计划中记录最终证据，不写私密模型输出。

- [ ] 对照 Spec/本计划审查全部 8 个合法组合、依赖方向与先后顺序；只读独立评审 Critical/Important 清零。现有 import 方应保持兼容，无隐式模式开关、用户“跳过审核”参数或新输出 keys。
- [ ] 正式前执行完整 `.\.venv\Scripts\python.exe -B -m pytest -q`（使用已授权测试库与模板，安全注入配置；不打印 URL/凭据）；前端完整 tests/build、`.\.venv\Scripts\python.exe -B manage.py check`、`manage.py makemigrations --check --dry-run`、`git diff --check`。以新输出为证据，不沿用先前 2489/111 的历史数量。
- [ ] 普通测试只 fake 外部 provider。应用有自动重载时先停止编辑并处理项目应用进程，不能让未评审接线热加载；不得操作 PostgreSQL 服务/实例。不得复制未确认数据到其它数据库绕过测试。
- [ ] 全部验收及评审通过后仅重启身份已验证的项目后端，检查前后端 HTTP；既有 Analysis297/旧 Solution150/Review92 与 Opportunity242 基线保留，不重新分析或改客户原始需求。
- [ ] 真实验收预算：本轮最多 **2 个新 workflow 请求**，每份仍使用既有三 pass/结构 attempt/verifier 上限。首个成功即停止生成；失败必须定位并停止，第二个名额只在另一次获准修正并验收后使用，不执行自动 retry-until-success。
- [ ] 请求前检查商机可见性、actor sales 业务身份、所选 Analysis297 与原需求仍匹配、来源准入/模型可用、是否已有该快照的有效方案。任何过期或变化立即停止，请用户选择正确快照；不得自动换成最新或伪造 facts。
- [ ] 使用正式 `/api/opportunities/242/solution-workflows/` + `{analysis_id:297}` + 新 UUID Idempotency-Key，不传测试标记或策略开关。凭据沿用已配置 provider；不得改额度、budget、fallback。只读观察不能替换 parser/guard/verifier 的结果。
- [ ] 成功须证实 parser、deterministic policy、semantic veto、return-time provenance 与数据库保存都通过；返回草稿 ID/版本/可用 action，并只读核对页面。不得代用户提交、审批或退回售前审核。
- [ ] 失败须记录可信 stage/code/index/enum位置，semantic 未触及时明确 0/NOT_REACHED；无新方案就如实报告未成功。若有限解析仍反复遗漏，不继续扩词或调用，返回下一轮结构协议设计讨论。
- [ ] 文档同步实际 V2 8 组合/三类错误和完成≠通过边界；保留历史失败、source-first 校正、当前限制。不得用一次成功宣称任意需求稳定通过。
- [ ] 不自动提交用户脏工作区；若用户要求提交，先逐块分清本轮与既有改动并取得范围确认，再考虑仅本轮的 commit。

## 执行及回滚边界

执行时读取 AGENTS、Spec 与计划；每项 RED→GREEN→针对性回归→评审后进入下一项。先离线 shadow，后正式接线，最终应用加载前完整验证。测试期待值的有意变化必须逐例说明，不批量删改失败测试来换绿。

任何新代码/文案尚未获本计划执行授权。本轮仅形成计划与 Spec 的源码校正，没有新增模型调用或业务写入。应用加载后有回归时只撤回本轮可分辨的接线/指导到原行为，不整库 reset、不删除业务版本、不回填失败状态；旧事实/引用/审核门槛始终存在。

建议执行方式：当前会话顺序实施，接口由同一实现者保持一致，最后进行独立只读评审；也可选择每项独立实现代理与评审，代价是更多上下文与协调。用户评审本计划并选择方式后，才能进入实现。
