# SalesMind AI AI Pipeline

当前合同快照：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。本文解释数据与权限边界；模块视图见 [architecture](architecture.md)。

> 概率组件提出建议；确定性代码或有权限的人工操作决定准入。

## 两条准备链路

### 企业知识

`KnowledgeDocument → validate/parse/chunk → BGE-M3 → pgvector → READY/index-run → fact extraction → PROPOSED → human approve/reject`。

检索只使用 READY 且 provider/model/dimension 匹配的索引。事实抽取不在索引长事务内；写入前检查来源快照。重新索引替换 chunks，并使旧 facts stale，而不是覆盖旧审计证据。

Admin 文档操作提供普通资料的显式抽取入口，不在上传或重建索引后自动触发。
持久化执行记录区分未执行、进行中、成功零候选和失败；同版本重复提交不构造新的 provider。
失败/取消后的重试需新的明确确认；取消只撤销旧结果写入资格，不承诺远端请求停止或退款。
人工批准仍由原事实审核服务完成，抽取模型不能批准自己提出的事实。
详见 [后台操作](admin-knowledge-workflow.md)；新增 schema 的业务库部署和真实模型验证未由源码完成替代。

### 客户需求

`Customer + Opportunity → frozen analysis input → requirement fact analysis → strict ten-dimension contract → deterministic follow-up questions → final snapshot validation → append-only analysis record`。

需求分析生成合同 `v2` 的模型输出顶层只有 `summary / requirements / conflicts`；
`clarifying_questions` 不再由模型生成，也不兼容猜测或悄悄过滤旧 provider 格式。
后端先通过正式校验验证事实、状态、证据和冲突，再按固定业务问题模板生成追问：
仅涉及 `unknown / unclear / conflict`，冲突优先、模糊其次、未知最后；同一优先级按十维枚举顺序排列，最多八条。
模板只询问客户事实，不补事实、证据、数值、技术选型或承诺，不改变维度状态。
组装后仍通过原四键快照 parser；API 和存储仍保留 `clarifying_questions`。
新记录使用 `analysis_version=v2`，历史 `v1` 快照及其原始追问继续原样读取、严格校验；无数据库迁移，无额外模型调用或重试。

known 客户方向用于设计；unknown/unclear/conflict 保留为信息边界。客户希望获得某项能力，不证明企业已经具备该能力。

## V2 请求链路

```text
明确的已保存 analysis ID → readiness
          ↓
需求派生 retrieval intents → BGE/pgvector → labelled sources
          ↓
当前已批准 facts 的 deterministic admission
          ↓
Core Semantic IR → strict parser / converter
          ↓
Implementation Semantic IR（含 validated core context）→ strict parser / converter
          ↓
Assurance Semantic IR（含 validated core + phases）→ strict parser / converter
          ↓
AtomicSolutionProposalSetV2 deterministic merge / global structure validation
          ↓
citation / requirement / unresolved / precision deterministic guards
          ↓
独立 verifier single-claim proposal admissibility
          ↓
return-time admission revalidation → Solution V2 assembly / validation
          ↓
短事务 provenance revalidation → Solution + durable provenance
          ↓
DRAFT → Presales human review
```

readiness 阻塞或没有检索证据时提前返回；非法输出不送 verifier。三段均不单独保存方案。pipeline 不删除被拒绝的 claim 来制造“可用的剩余方案”。

正式 readiness 阻塞通过无客户文本的错误码区分：
`solution_needs_sales_clarification` 指向销售确认需求方向或信息冲突，
`solution_needs_presales_involvement` 指向售前澄清技术冲突。
首次失败和同一工作流回放均保留该分类；原失败状态、HTTP 422 和幂等规则不变。
前端提供客户需求或售前负责人入口，并展示所选快照的待确认维度与现有追问。
`ready_with_gaps` 不因此新增阻塞；预算、时间或用户规模未知不被机械解释为必须补齐。
生成内容准入拒绝与 verifier 返回无效结果仍分别显示，不能自动归因于客户信息缺失；
错误提示不展示模型原文、客户原文或 secret，不自动触发再次生成。

V2 即使检索命中文档，也必须存在由正式事实准入服务授权的 proposal citation。
没有检索结果或合法引用列表为空时，在构造 generation provider 前以
`solution_draft_insufficient_approved_evidence` 停止；前端提示补充相关资料或由有权限人员
核对并审核事实，不自动批准事实。V1 历史路径不改变。

三段 Semantic IR 输入均显式携带 `allowed_citation_ids`，不得推断编号连续性或借用其它
上下文中未授权的编号。canonical 示例使用本次允许的编号只是展示格式，不证明示例的
技术结论；真实 proposal 仍需引用内容支持。系统不替换模型输出中的非法 citation。

三段生成上下文将已确认不支持、冲突和待确认的内容单独放入
`solution_boundaries`，保留原事实文本和类型，但不展示其 proposal citation 编号。
企业事实按正式准入 decision/provenance 区分支持与边界，不按 source 编号简单过滤：
同一来源可以同时支持某项能力并明确否定另一项。该投影仅用于生成输入；原始
admission、事实状态、审批和 durable provenance 不改写，可引用编号仍由正式准入决定。

strict parser 拒绝输出时，现有唯一一次 bounded regeneration 接收正式拒绝路径的
category/path/expected/actual 反馈；引用错误同时提供原允许列表。反馈不附上完整
模型输出、未知键名、非法引用原值或异常 cause，不自动替换编号、裁剪或修复 JSON。
第二次输出仍完整通过同一 strict parser，连续失败即终止；provider error 不增加重试。

Implementation 输入另携带程序计算的 `implementation_budget_options`：按阶段数、里程碑数，
同时核算总量、section 和局部 tasks/timing 上限。模型仍选择适合项目的阶段划分；表格不批准
业务事实，也不放宽预算。示例包含完整、可解析的阶段依赖对象，恰好只有 `from / to`。
示例中的阶段、技术内容和顺序仅用于说明格式，不能代替项目设计或来源证据。

closed-object 正式拒绝携带该位置的 `allowed_keys`，供原有唯一一次重新生成使用。
字段清单来自程序合同，不来自模型额外字段；未知字段名继续脱敏，不反馈其值或完整输出。
不自动改字段名、删除条目、修补 JSON、扩大数量上限或增加重试次数。

Assurance 的生成指导另明确验收对象的层级：`acceptance[]` 外层恰好包含
`ref / criterion`；`criterion` 恰好包含一条 claim，其正文、引用与需求关联位于
`text / citations / related_requirement_fields`。阶段与验收的关联单独写入顶层
`phase_acceptance`，关系对象只含 `from / to`，不承载正文或引用。
这是既有闭合合同的输入说明，不新增输出字段、不修补模型输出、不改变事实或审核准入。
提示词和解析器一致性测试不能证明真实模型一定遵守格式。

规划生成指导明确：涉及部署条件、服务器容量或承载条件时，模型必须保留直接
`deployment_requirement` 关联，不能只用环境或集成关联代替；程序不自动补字段。
有限规划语法支持已解析的满足/完成前提与工作动作之间使用中文或英文逗号，仍区分
“核验完成”和“确认条件满足”。新增技术接入动作仅识别检索入口、上传索引、检索服务
及最多三个这类对象的组合，支持“完成……的（落地）接入”或“接入……”；
可带“按已验证方案”限定词，但该措辞不批准事实或能力。
前提对象和整个工作正文必须完整匹配；不接受任意工作尾句、不消除额外未确认前提。
识别结果仅是候选，仍须引用、数值精度、语义/原子性否决及返回时来源复核，不能自动保存。
此机制仍不是任意自然语言理解，也不能保证模型关联完整或所有新表述均可识别。

三段生成输入的 `requirement_design_scope` 按原分析状态列出 `confirmed_fields` 和
`conditional_fields`。它只提供设计边界，不新增事实、不拆分或重分类 unclear 内容，也不改写快照。
已知环境背景不能证明未知的服务器容量、部署位置或性能。直接依赖非 known 维度的建议须
在该条判断自身表达真实确认前提；不能用更换关联维度、空关联或机械条件前缀逃避规则。
Core 部署示例采用条件性安排；企业证据、precision guards、语义审核与返回时来源复核保持不变。

## 语义与结构的所有权

| 内容 | 来源 | 权限边界 |
| --- | --- | --- |
| customer_fact | 已保存 analysis 的 known dimensions，由代码构造 | LLM 不改写客户事实 |
| enterprise_fact | approved/current/provenance-valid facts，由代码构造 | verifier 不能批准事实 |
| unresolved / 信息缺口 | 需求状态与企业事实准入，由代码构造 | 不能被建议升格为 confirmed |
| proposal text / citations / related_requirement_fields | generation LLM | 仍需 strict contract、guards、admissibility |
| component/phase/risk 局部 refs 与关系端点/方向 | generation LLM | 不得引用不存在的对象；代码不猜语义关系 |
| placement / kind / field / relation enum | deterministic converter | 不生成新建议、citation 或需求关联 |
| claim/container IDs、稳定排序、V2 references | deterministic parser/assembler | 不靠 first-seen 顺序猜身份，不拼接新语义 |
| 最终业务审批 | authorized human review | generation / score / verifier 均不能代替 |

Semantic IR 是 generation-only `semantic_v1`；最终 persisted schema 仍是 Solution V2。每个 semantic claim 包含恰好 `text / citations / related_requirement_fields`；relations 使用恰好 `{from,to}`，不把 citation 或 rationale 塞入 edge。closed objects 拒绝额外 keys，非法类型先校验再去重。

当前 Semantic IR 的 Assurance 仅由模型生成 risks、acceptance、out_of_scope 和 phase_acceptance；最终的 assumptions/open_questions 由确定性内容构建，不由该 pass 自行补写。

合同与预算以 [solution_generation_contract.py](../apps/sales/services/solution_generation_contract.py) 为唯一源码真源：Core 46、Implementation 18、Assurance 20、global 84、components 4，6,000 output tokens/pass。ceiling 不是 target count。converter 不裁剪超预算内容。

## 有限重新生成，而不是安全重试

V2 每段第一次 output 被 strict parser/generation contract 拒绝时，最多重新生成一次。新输出完整重新解析，不修补前次 JSON，也不保存部分内容。

该机制不重试 provider error、unsupported precision、unresolved-as-confirmed、verifier INADMISSIBLE/COMPOUND 或 persistence error。SDK transport retries 是独立 provider 配置；不能与 pass regeneration attempts 混算。

统一 evaluation diagnostics 来自正式拒绝分支，记录 category/path/expected/actual，不再用另一套规则猜测原始输出。业务 API 仍使用稳定安全错误，不返回 provider raw JSON。

生成失败的安全日志复用正式 parser 已脱敏的 citation subtype、allowed IDs 和 offending
IDs；非法自由文本编号只保留类型或脱敏占位符，不写入完整输出、客户文本或异常 cause。

## Deterministic admission 与 guard

事实准入校验 approval/status/stale/document readiness/index-run/hash；相互矛盾的 approved 正/负事实不授权正向能力。proposal citation 只能引用允许的 source labels；requirement linkage 必须有效且存在对应上下文。

语义 verifier 前 guard 拒绝把相关 unresolved 需求断言成 confirmed，或使用相关需求/引用依据中未出现的精确承诺。有限条件表达识别不代表通用自然语言理解；条件式也不豁免 precision 校验。

V2 使用单一用途策略表覆盖 phase objective/tasks/deliverables/timing、risk condition/impact/mitigation、
milestone outcome，共 8 个合法组合。有限表达解析区分待核验动作、未来核验成果、假设风险、
条件性工作与结果断言；候选继续经过精度、atomicity/semantic veto 与返回时来源复核。
核验完成不等于核验通过或条件满足，未确认技术条件依赖的实施动作必须有明确满足前提。
父级 objective/condition 不豁免子项；不改变需求状态、原文、关联、引用、预算、尝试次数或输出合同。
全部关联已知的普通技术建议仍走原 guard；risk trigger、milestone timing、其它位置与 V1 不变。
回归见 `test_solution_unresolved_policy.py` 与 `test_solution_unresolved_policy_integration.py`。

阶段目标自身也可表达尚待执行的环境/实施边界核验。有限项目限定语只限定核验对象，
不会证明环境可用、容量足够或实施日期已承诺；所有通过识别的目标仍须单独语义审核。

对象列表支持网络访问边界，每个对象前均可使用“现有/当前/目标 + 有限 ASCII 产品名称 + 环境的”限定语。
限定语仅标识待核验的环境，后续对象仍必须逐个属于闭合核验对象列表；不消费任意自由文本，
不把声明结果或保证交付当成名称。完整动作可作为 coherent 核验工作包送审，但原文不会被
自动拆分或修补，相关需求状态和引用保持不变；语义审核仍可否决不受支持的环境名称、技术
判断或 COMPOUND 输出。回归见 `test_solution_combined_clarification_actions.py`。

Implementation/Assurance 生成输入另携带 `clarification_action_style`，只针对
上述 8 个合法组合示意待执行核验、未来成果、条件性工作、假设风险与结果断言的区别，
targets/field_examples 从同一策略表派生，仅为生成输入。
纯核验不声称结果已确认；依赖结果的实施/交付安排仍需真实确认前提。该内容仅是输入表达
指导，不新增输出字段、意图标签或审批权限，不改写模型文本、需求状态、引用列表、预算或
重试。模型若忽略指导，仍按原合同和全部准入规则拒绝。

### 规划表达失败分类与请求关联

`solution_draft_unconfirmed_assertion` 表示把未确认条件写成确定断言；
`solution_draft_unqualified_precondition` 表示结果前提不充分或满足的对象未覆盖实际技术依赖；
`solution_draft_expression_unclassified` 表示有限表达解析无法可靠判定，需要技术核对。
三者不等同于客户缺信息，不返回或保存失败内容。明确未知对象的关联检查不因尾句无法解析而取消。

新工作流保留四个 allowlisted LLM 服务错误与 `solution_draft_invalid_response` 格式错误，
未知错误仍使用安全 fallback。首次失败 HTTP 422，仅 `{code,message}`；同 key 重放 HTTP 200
返回已有 FAILED/error_code、空 allowed_actions，不重新调用模型，也不回填历史 checkpoint。
普通拒绝日志由 typed UUID ContextVar 关联 workflow_id，记录可信 placement、条目序号与固定类别；
不记录原文、来源正文、container_key、异常 cause 或 evaluation diagnostics 的 excerpt。

自然语义相关性、未支持的能力/厂商、冲突与 atomicity 不能全部靠这些 guards 保证，因此仍有独立 semantic verifier veto 和人工 review。

## Proposal admissibility / atomicity

正式 V2 packet 含 proposal、placement、相关需求、完整已分析客户上下文、被引用的企业 evidence；仅 task/deliverable 加 phase objective，仅 risk mitigation 加 risk condition/impact。这些建议上下文都不能成为新的事实依据。

普通 claim 的 ATOMIC 是“一个可独立批准/拒绝的技术判断”，不是“一句话一个动词”。implementation task 按 coherent work package，deliverable 按同目标可统一验收的成果包，mitigation 按同 risk 的 coherent strategy 判断，均禁止独立技术选型或无依据承诺混入。

V2 需要 `decision=ADMISSIBLE`，并通常需要 `atomicity=ATOMIC`。architecture identity 的 atomicity 不单独 hard veto，但其他合法性和 admissibility 检查照常。V1 旧路径独立保留 `SUPPORTED / INSUFFICIENT / CONTRADICTED` 合同，不用 V2 规则解释历史输出。

single claim/request、per-draft concurrency 2、60s timeout、0 SDK retries。当前 DeepSeek verifier wrapper 发送 `thinking.type=disabled`；显式选择 Qwen 的旧兼容路径时发送 `enable_thinking=false`。两种协议不混用，生成端的 thinking 设置不影响独立 verifier。当前选择与验证边界见 [本地配置](local-configuration.md)。

出现 provider error 是 provider availability failure，不是 INADMISSIBLE verdict。401 为 auth_error，403 为 permission_denied；可安全保留 provider code，例如 `AllocationQuota.FreeTierOnly`，但不把全部 403 视为额度错误。

## Return-time / transaction-time provenance

外部调用之后重新构建 admission 并要求与调用前一致；持久化短事务里再次验证来源。即使 verifier 全通过，若事实被重建索引、变 stale 或审批状态改变，仍 fail closed。

SolutionDraftRecord 按 Opportunity 分配不可变版本；provenance 保存 Fact/文档、citation/claim 映射及 index/hash/chunk/excerpt 快照。模型调用在事务外，不能用长锁覆盖网络等待。workflow idempotency replay 返回匹配已有版本，不重复调用 provider 或创建 review。

## 人工审核与工作流

DRAFT → PENDING_REVIEW → APPROVED 或 NEEDS_REVISION。退回分别为 CUSTOMER_INFO_REQUIRED / TECHNICAL_REVISION_REQUIRED。作者不能自审，stale 与 review 状态独立。

LangGraph 负责路由、human interrupt 与 resume，PostgresSaver 仅保留稳定 ID/路由状态；Django service 和业务表仍执行权限、有效性与状态转换。当前没有自动 revision loop。

## 评估与相关源码

质量只对真正持久化的最终 V2 评分。provider availability、generation contract、deterministic admission、verifier admission、assembly/persistence、quality 分层报告；`NOT_REACHED` 不是某层测得失败，`NOT_EVALUATED` 不是零分。

- [正式 Semantic IR converter](../apps/sales/services/solution_semantic_ir_v2.py)
- [三段 prompt/parser/merge](../apps/sales/services/solution_prompt_v2.py)
- [guard / verifier / bounded scheduler](../apps/sales/services/solution_grounding.py)
- [persistence / stale](../apps/sales/services/solution_persistence.py)
- [review / workflow](../apps/sales/services/solution_review_workflow.py)
- [分层报告口径](benchmark-layered-evaluation.md) / [真实结果](real-provider-benchmark-summary.md)
