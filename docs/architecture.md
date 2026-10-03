# SalesMind AI Architecture

## 当前快照

核心功能冻结于 `1141281c07b2f5f92d51151fc9b2f0803814ef60`。本文以该提交的源码为准，替代早期“前端待实现 / 单次 proposal generation”的架构说明；历史决策和实验结果不因此被重写。

系统是模块化 Django 单体 + Vue 前端。目标是辅助销售与售前形成可审核的技术方案，不是让 LLM 承担企业事实批准或技术方案终审。

## 分层与模块

```text
Vue / TypeScript 工作台与方案详情
                ↓ JWT / 角色与对象可见性
Django REST API ── LangGraph 人工审核编排
                ↓
Accounts / Sales / Knowledge / RAG / LLM 服务
                ↓
PostgreSQL：业务数据 + pgvector + 来源快照 + workflow checkpoints
```

| 模块 | 责任 |
| --- | --- |
| `apps/accounts` | 用户、业务 role、JWT、技术管理入口 |
| `apps/sales` | Customer/Opportunity、需求分析、方案生成/准入/组装、版本持久化、审核、评估 harness |
| `apps/knowledge` | 文档验证/解析/分块、embedding/index/search、Grounding Facts 提议与审批 |
| `apps/rag` | 基于检索证据的问答及引用处理 |
| `apps/llm` | DeepSeek 生成及独立 OpenAI-compatible verifier 的 provider 边界 |
| `frontend` | 销售/售前工作台、V1/V2 renderer、review 与 stale 状态展示 |
| `config` | Django settings、数据库、API 路由及环境配置 |

精确版本见 [requirements](../requirements/base.txt) 与 [package.json](../frontend/package.json)。不引入独立向量数据库、Celery 或微服务。

## 1. Customer / Opportunity 与权限

Customer 是共享主数据，`created_by` 为审计字段，不是销售私有所有权。Opportunity 关联 Customer，分别保存 `sales_owner`、可选 `presales_owner`、`created_by`、原始需求和业务状态。

Admin 可见全部商机；Sales 只见自己拥有的商机；Presales 只见被指派的商机。版本级 reviewer 可查看其被指派的确切方案，但不因此获得整个商机的权限。

`User.role` 与 `is_staff / is_superuser` 独立。Grounding Facts 管理审批需 active + staff + `role=admin`，不能由技术 superuser 标记绕过业务 role。详见 [业务规则](business-rules.md)。

## 2. Requirement Analysis

需求分析基于 Customer / Opportunity 的冻结输入快照，输出十个固定维度：业务目标、使用场景、人数、部署、安全、环境、集成、时间、预算、技术约束。每个维度为 `known / unknown / unclear / conflict`。

`OpportunityRequirementAnalysis` 为 append-only 历史记录。方案请求必须选择一个明确的已保存 analysis，不能偷偷替换成最新版本。readiness 确定是否可生成、有缺口但可继续，或应交回 Sales/Presales；缺信息不等于允许模型补事实。

入口：[requirement_analysis.py](../apps/sales/services/requirement_analysis.py)、[requirement_analysis_history.py](../apps/sales/services/requirement_analysis_history.py)、[solution_readiness.py](../apps/sales/services/solution_readiness.py)。

## 3. BGE Retrieval / RAG

```text
文档 → 验证/解析 → 分块 → BGE-M3 embedding → PostgreSQL/pgvector
                                                     ↓
需求派生查询 → 同 provider/model/dimension 的 query embedding → 检索与来源标签
```

当前真实配置使用 `BAAI/bge-m3`、1,024 维。正式 search 仅查询 READY 且 embedding provider/model/dimension 匹配的文档。离线 Demo 向量不能作为真实 BGE 的兼容索引。

检索相关性不等于事实已获准进入方案。RAG 问答与 Solution generation 使用知识证据，但后者还需要企业事实准入。文档内容始终是不可信数据，不可当作执行指令。

索引成功后，文档 index-run 更新、旧 chunks 替换、旧事实 stale；旧来源快照保留用于审计。

入口：[indexing.py](../apps/knowledge/services/indexing.py)、[search.py](../apps/knowledge/services/search.py)、[solution_retrieval.py](../apps/sales/services/solution_retrieval.py)。

## 4. Grounding Facts / 事实准入

```text
LLM extraction → EnterpriseGroundingFact PROPOSED
                                   ↓ 有权限人员 approve/reject
                            APPROVED 候选事实
                                   ↓ current / status / provenance 校验
                           确定性企业事实准入
```

批准不等于永久有效。事实还需非 stale、文档 READY、当前 index-run 一致、内容 hash 与引用来源匹配。明确正向/负向事实可分别陈述；缺失、未确认、冲突、拒绝、过期或来源无效都不能成为正向能力依据。

代码从已确认需求产生 `customer_fact`，从合格企业事实产生 `enterprise_fact`，从信息缺口产生 `unresolved`。LLM 不能把客户需求转成企业能力，也不能批准自己抽取的事实。

入口：[grounding_facts.py](../apps/knowledge/services/grounding_facts.py)、[grounding_fact_approval.py](../apps/knowledge/services/grounding_fact_approval.py)、[solution_admission.py](../apps/sales/services/solution_admission.py)。

## 5. Core / Implementation / Assurance

三段按序使用同一 Requirement Analysis 与准入证据；后段额外接收经过校验的前段紧凑上下文。每段输出 generation-only `semantic_v1`，不是最终 Solution JSON。

| Pass | 语义范围 | proposal hard ceiling |
| --- | --- | ---: |
| Core | 总体推荐、能力建议、架构 overview / components / dependencies / request flows / data flows、部署/集成/安全/环境 | 46 |
| Implementation | phase objective/tasks/deliverables/可选 timing、milestones、phase dependencies | 18 |
| Assurance | risk 四部分、acceptance、out_of_scope、phase→acceptance | 20 |
| 合并 | 只合并三个合法 pass；全局再校验 | 84 |

每段输出最多 6,000 tokens；组件最多 4 个。这些是 ceiling，不是生成目标或要求填满的数量。局部 cardinality 与总预算同时有效，关系不计入 proposal 数。

Core ceiling 来自局部上限：`5 + 2 + 4×(1+2+1+2) + (4+3+2+2) + 2×2 = 46`。新组件必须有一个 identity claim，并有 responsibility、rationale、interface。Implementation 使用 `T <= 18 - 2P - M` 的剩余工作预算，仍有阶段/tasks/timing/section 局部限制。Assurance 最多 3 个 risk，每项四字段各一条；最多 6 个 acceptance、2 个 out_of_scope。

LLM claim 只写 `text / citations / related_requirement_fields`，以及明确的局部 ref 与关系方向。converter 负责 placement、field、kind、relation enum、稳定映射和排序；不造 citation、需求关联、理由或 flow。不合格 IR 不截断、不合并、不修半截 JSON。

每段 strict contract 拒绝最多触发一次重新生成（最多两次 attempt）；provider error、deterministic guard、Qwen veto 和 persistence failure 不触发这一机制。两个 attempt 都不合法则整份失败，无部分方案持久化。

合同真源：[solution_generation_contract.py](../apps/sales/services/solution_generation_contract.py)。链路：[solution_prompt_v2.py](../apps/sales/services/solution_prompt_v2.py)、[solution_semantic_ir_v2.py](../apps/sales/services/solution_semantic_ir_v2.py)、[solution_draft.py](../apps/sales/services/solution_draft.py)。

## 6. Deterministic Guards / Qwen Verifier

结构解析及 merge 先检查字段、citation allowlist、需求维度、数量、关系端点、组件完整性和 phase dependency cycle。Qwen 前再检查引用/需求上下文、unresolved 被断言成 confirmed，以及缺乏依据的 precision 等规则。不能把全部安全判断都描述成正则 guard：自然语义相关性、矛盾和 atomicity 还由独立 proposal admissibility 审查。

当前独立 verifier 为 Qwen `qwen3.8-flash`，DashScope compatible-mode；正式 wrapper 显式关闭 thinking。single claim/request，timeout 60s、SDK retries 0、每份方案 concurrency 2。调度只维持有限 in-flight 请求；已观察到 veto 后停止补充任务，已经开始的请求可能仍需完成。它不是跨进程全局限流器。

V2 decision 为 `ADMISSIBLE / INADMISSIBLE`，atomicity 为 `ATOMIC / COMPOUND`。通常需 `ADMISSIBLE + ATOMIC`；组件 identity 仍需 admissibility，但不以 COMPOUND 单独 hard veto。task、deliverable、mitigation 的 ATOMIC 分别按统一工作包、统一阶段成果包、同一风险缓解策略判断；这不是允许这些字段跳过 atomicity。

phase objective 或 risk condition/impact 是理解建议的上下文，不会变成已确认事实。Qwen 只能否决，不能扩大可用事实集或授予 review APPROVED。

事实准入在外部调用之后再次构建，持久化事务中再次验证，防止模型调用期间的重建索引/审批变更导致陈旧方案返回或保存。

入口：[solution_grounding.py](../apps/sales/services/solution_grounding.py)、[proposal admissibility prompt](../apps/sales/services/solution_proposal_admissibility_prompt.py)、[verifier_factory.py](../apps/llm/verifier_factory.py)。

## 7. Solution V2 / 前端

`schema_version=2`：central atomic claim registry 是语义真源，结构对象保存 claim references 与关系。`ArchitectureComponentV2.identity_claim_id` 指向 identity proposal；`name` 仅历史/中性 fallback。历史 V2 缺少 identity/flows 可读取，不回填；V1 使用独立 mapper/renderer。

三种关系独立：dependency 表示 A 依赖 B；request flow 表示请求 A→B；data flow 表示数据 A→B。前端展示已保存的 flow，不从 dependency 或文本猜新边。phase 关联 acceptance，milestone 关联 phase，risk 使用 condition/impact/mitigation/trigger 四段结构。

Vue 详情页区分推荐/理由/取舍、职责/交互/依赖、实施任务/交付物/验收、风险与信息缺口；企业能力依据与 source 位于次级可展开区域。review/stale 状态清楚展示，窄视口安全换行。

入口：[solution_schema_v2.py](../apps/sales/services/solution_schema_v2.py)、[solution_payloads.py](../apps/sales/services/solution_payloads.py)、[SolutionV2Renderer.vue](../frontend/src/components/solution/SolutionV2Renderer.vue)。

## 8. Persistence / Provenance

外部模型调用不在长数据库事务内。所有 pass、global structure、guards、Qwen 和 V2 validation 均通过后，短事务锁定 Opportunity、再次校验来源、分配版本、一起写入 `SolutionDraftRecord` 与 `SolutionDraftProvenance`。失败不保存部分 Solution 或孤立 provenance。

持久化 provenance 包含 Fact、文档、citation/claim 对应路径、chunk-id/index-run/hash/excerpt 快照，不依赖可被重新索引删除的 chunk 外键。多个 citation/fact binding 可对应同一 claim，所以 provenance 行数不是独立事实数量。

workflow generation idempotency key 使用 advisory lock 保证同 key 不重复生成版本，不把整个网络等待放入事务。已批准版本仍可能因新需求或知识变化 stale，历史记录不被改写。

入口：[solution_persistence.py](../apps/sales/services/solution_persistence.py)、[models.py](../apps/sales/models.py)。

## 9. Presales Review / LangGraph

```text
DRAFT → submit → PENDING_REVIEW
                       ├── approve → APPROVED
                       └── return → NEEDS_REVISION
                              ├── CUSTOMER_INFO_REQUIRED：销售补客户事实
                              └── TECHNICAL_REVISION_REQUIRED：售前修技术方案
```

review 为版本级审计记录。作者不能自审；技术 superuser 不绕过业务 role；审批时重新检查 stale。业务表是最终真源。

LangGraph 编排 generate/persist、submit、human interrupt、resume。官方 PostgresSaver 保留稳定 ID 与路由状态，不存整份文档、provider response、凭据或方案语义。重放使用既有服务校验业务状态；checkpoint 不能覆盖已提交决策。退回后当前是 terminal/handoff，不自动生成新版。

入口：[solution_review.py](../apps/sales/services/solution_review.py)、[solution_review_workflow.py](../apps/sales/services/solution_review_workflow.py)、[solution_workflow_checkpoint.py](../apps/sales/services/solution_workflow_checkpoint.py)。

## 验证与范围

离线自动化验证工程和安全合同，真实 benchmark 验证一次真实链路，人工售前审核决定业务使用。三者不能互相替代。当前不是高并发生产部署，也未证明跨场景 SLA。

进一步阅读：[AI pipeline](ai-pipeline.md)、[真实 benchmark](real-provider-benchmark-summary.md)、[Known Limitations](known-limitations.md)、[配置说明](local-configuration.md)。
