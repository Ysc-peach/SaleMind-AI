# SalesMind AI AI Pipeline

当前合同快照：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。本文解释数据与权限边界；模块视图见 [architecture](architecture.md)。

> 概率组件提出建议；确定性代码或有权限的人工操作决定准入。

## 两条准备链路

### 企业知识

`KnowledgeDocument → validate/parse/chunk → BGE-M3 → pgvector → READY/index-run → fact extraction → PROPOSED → human approve/reject`。

检索只使用 READY 且 provider/model/dimension 匹配的索引。事实抽取不在索引长事务内；写入前检查来源快照。重新索引替换 chunks，并使旧 facts stale，而不是覆盖旧审计证据。

### 客户需求

`Customer + Opportunity → frozen analysis input → requirement analysis → strict ten-dimension contract → append-only analysis record`。

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
Qwen single-claim proposal admissibility
          ↓
return-time admission revalidation → Solution V2 assembly / validation
          ↓
短事务 provenance revalidation → Solution + durable provenance
          ↓
DRAFT → Presales human review
```

readiness 阻塞或没有检索证据时提前返回；非法输出不送 verifier。三段均不单独保存方案。pipeline 不删除被拒绝的 claim 来制造“可用的剩余方案”。

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
| 最终业务审批 | authorized human review | generation / score / Qwen 均不能代替 |

Semantic IR 是 generation-only `semantic_v1`；最终 persisted schema 仍是 Solution V2。每个 semantic claim 包含恰好 `text / citations / related_requirement_fields`；relations 使用恰好 `{from,to}`，不把 citation 或 rationale 塞入 edge。closed objects 拒绝额外 keys，非法类型先校验再去重。

当前 Semantic IR 的 Assurance 仅由模型生成 risks、acceptance、out_of_scope 和 phase_acceptance；最终的 assumptions/open_questions 由确定性内容构建，不由该 pass 自行补写。

合同与预算以 [solution_generation_contract.py](../apps/sales/services/solution_generation_contract.py) 为唯一源码真源：Core 46、Implementation 18、Assurance 20、global 84、components 4，6,000 output tokens/pass。ceiling 不是 target count。converter 不裁剪超预算内容。

## 有限重新生成，而不是安全重试

V2 每段第一次 output 被 strict parser/generation contract 拒绝时，最多重新生成一次。新输出完整重新解析，不修补前次 JSON，也不保存部分内容。

该机制不重试 provider error、unsupported precision、unresolved-as-confirmed、Qwen INADMISSIBLE/COMPOUND 或 persistence error。SDK transport retries 是独立 provider 配置；不能与 pass regeneration attempts 混算。

统一 evaluation diagnostics 来自正式拒绝分支，记录 category/path/expected/actual，不再用另一套规则猜测原始输出。业务 API 仍使用稳定安全错误，不返回 provider raw JSON。

## Deterministic admission 与 guard

事实准入校验 approval/status/stale/document readiness/index-run/hash；相互矛盾的 approved 正/负事实不授权正向能力。proposal citation 只能引用允许的 source labels；requirement linkage 必须有效且存在对应上下文。

Qwen 前 guard 拒绝把相关 unresolved 需求断言成 confirmed，或使用相关需求/引用依据中未出现的精确承诺。有限条件表达识别不代表通用自然语言理解；条件式也不豁免 precision 校验。

自然语义相关性、未支持的能力/厂商、冲突与 atomicity 不能全部靠这些 guards 保证，因此仍有独立 Qwen veto 和人工 review。

## Proposal admissibility / atomicity

正式 V2 packet 含 proposal、placement、相关需求、完整已分析客户上下文、被引用的企业 evidence；仅 task/deliverable 加 phase objective，仅 risk mitigation 加 risk condition/impact。这些建议上下文都不能成为新的事实依据。

普通 claim 的 ATOMIC 是“一个可独立批准/拒绝的技术判断”，不是“一句话一个动词”。implementation task 按 coherent work package，deliverable 按同目标可统一验收的成果包，mitigation 按同 risk 的 coherent strategy 判断，均禁止独立技术选型或无依据承诺混入。

V2 需要 `decision=ADMISSIBLE`，并通常需要 `atomicity=ATOMIC`。architecture identity 的 atomicity 不单独 hard veto，但其他合法性和 admissibility 检查照常。V1 旧路径独立保留 `SUPPORTED / INSUFFICIENT / CONTRADICTED` 合同，不用 V2 规则解释历史输出。

single claim/request、per-draft concurrency 2、60s timeout、0 SDK retries。支持 Qwen thinking control 的正式 verifier wrapper 发送 `enable_thinking=false`；不向所有 OpenAI-compatible providers 无条件发送此参数。

出现 provider error 是 provider availability failure，不是 INADMISSIBLE verdict。401 为 auth_error，403 为 permission_denied；可安全保留 provider code，例如 `AllocationQuota.FreeTierOnly`，但不把全部 403 视为额度错误。

## Return-time / transaction-time provenance

外部调用之后重新构建 admission 并要求与调用前一致；持久化短事务里再次验证来源。即使 Qwen 全通过，若事实被重建索引、变 stale 或审批状态改变，仍 fail closed。

SolutionDraftRecord 按 Opportunity 分配不可变版本；provenance 保存 Fact/文档、citation/claim 映射及 index/hash/chunk/excerpt 快照。模型调用在事务外，不能用长锁覆盖网络等待。workflow idempotency replay 返回匹配已有版本，不重复调用 provider 或创建 review。

## 人工审核与工作流

DRAFT → PENDING_REVIEW → APPROVED 或 NEEDS_REVISION。退回分别为 CUSTOMER_INFO_REQUIRED / TECHNICAL_REVISION_REQUIRED。作者不能自审，stale 与 review 状态独立。

LangGraph 负责路由、human interrupt 与 resume，PostgresSaver 仅保留稳定 ID/路由状态；Django service 和业务表仍执行权限、有效性与状态转换。当前没有自动 revision loop。

## 评估与相关源码

质量只对真正持久化的最终 V2 评分。provider availability、generation contract、deterministic admission、Qwen admission、assembly/persistence、quality 分层报告；`NOT_REACHED` 不是某层测得失败，`NOT_EVALUATED` 不是零分。

- [正式 Semantic IR converter](../apps/sales/services/solution_semantic_ir_v2.py)
- [三段 prompt/parser/merge](../apps/sales/services/solution_prompt_v2.py)
- [guard / verifier / bounded scheduler](../apps/sales/services/solution_grounding.py)
- [persistence / stale](../apps/sales/services/solution_persistence.py)
- [review / workflow](../apps/sales/services/solution_review_workflow.py)
- [分层报告口径](benchmark-layered-evaluation.md) / [真实结果](real-provider-benchmark-summary.md)
