# SalesMind AI：面试技术复盘

核心功能基线：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。这份复盘只陈述已实现机制和已观察证据，不把项目包装成已验证的高并发生产系统。

## 一分钟介绍

SalesMind AI 是一个 Django + Vue 的企业售前辅助系统。销售录入商机与需求，系统检索企业知识，在已审批事实范围内生成技术方案，售前再做版本级审核。

最重要的设计不是模型能写多少文字，而是把“客户确认的事实”“企业批准的能力”“模型建议”“人工审核决定”分开。最终方案有 central claim registry、显式结构关系和持久来源快照；模型输出失败、安全检查失败或来源失效时，不返回半份貌似可信的方案。

## 1. 最难的问题：把模型输出接进可审计业务链

难点不是单个 API 是否返回 JSON，而是每个层次都可能独立失败：

```text
provider 可用 → JSON 完整 → 合同合法 → 建议有依据 → 语义准入
                                                   ↓
来源仍有效 → V2 组装合法 → 事务提交 → 人工技术批准
```

最初单次 generation 的五场景运行没有一个形成合法 V2：有 token truncation，也有完整 JSON 的合同错误。后来即使三段都合法，仍可能被 deterministic guard 或 Qwen veto。外部 403 又与这些业务失败不同。

我的定位顺序是先确定失败层，再查看该层真实拒绝分支，而不是把全部错误解释成“模型不好”或直接调大 timeout。工程上采用正式 parser 的 category/path/expected/actual、安全 provider metadata、guard reason 和 per-claim verdict，禁止记录密钥、reasoning content 或完整客户文档。

## 2. 为什么没有直接放宽规则

结构合法不代表事实真实，verifier verdict 也不代表有权批准企业能力。放宽 parser、把未知信息写成事实、删除失败 claim 或直接保存部分方案，会让展示更容易成功，却破坏审计边界。

保留的关键约束是：

- Fact extraction 只能产生 PROPOSED，有权限人员才能 approve/reject。
- enterprise admission 只用批准、当前、来源有效的明确事实。
- customer demand 不证明 enterprise capability。
- Qwen veto-only，不能授权事实或批准方案。
- model calls 后和 persistence transaction 内都重新校验来源，防止调用期间知识变 stale。
- Solution + Provenance 同事务提交，失败不能留下部分方案。

有限 pass regeneration 只应对结构合同拒绝，并且最多一次；不能针对业务 veto 重试到通过。

## 3. Semantic IR 为什么产生

原先让 LLM 同时生成文本、placement、container kind、field、relation enum 与引用，许多错误发生在结构合同，而不是技术内容本身。单纯增加 prompt patch 会持续追逐下一种错误。

Minimal Semantic IR 把职责重新分开：模型给 claim 的 `text/citations/related_requirement_fields`、嵌套 component/phase/risk 与局部 ref/edge direction；代码填已知的 placement、kind、field、relation type，并映射稳定 ID。

这不是自动修复模型：converter 不发明理由、citation、需求关联，不猜 flow，不丢超限内容。IR 先 strict validate，再转换成已有 `AtomicSolutionProposalSetV2`；下游 guard、Qwen、V2 schema、persistence 和前端仍保留。

三段划分为 Core（技术设计）、Implementation（实施）、Assurance（风险与验收）。局部上限控制密度，总 ceiling 提供可计算的结构边界，而不是要求模型填满。当前 46/18/20/global 84 来自实际合同校准，不是无限输出空间。

## 4. Atomicity 为什么 placement-aware

“原子”应指一个可独立批准/拒绝的判断，不是一个动词。总体技术建议若同时决定 OA 接口和 SSO，就应拆开；同阶段访问控制工作包内的认证配置和权限核验，却可能共同完成一个实施目标。

当前规则分别理解：

| Placement | ATOMIC 业务含义 | 仍禁止 |
| --- | --- | --- |
| 普通技术 claim | 一个独立技术判断 | 多个可独立批准/否决的选型或能力决策 |
| Implementation task | 同 phase objective 的 coherent work package | 混入独立选型或不同交付目标 |
| Implementation deliverable | 同 phase objective 下可统一验收的成果包 | 无法统一验收的成果集合 |
| Risk mitigation | 同 risk 的 coherent strategy | 独立基础设施选型、无依据承诺 |

verifier 只为相关 placement 增补 phase objective 或 risk condition/impact，不把整个 Core 都塞进 packet。这些上下文仍是建议，不变成事实依据。上述三类仍要求 `ADMISSIBLE + ATOMIC`，没有 COMPOUND 放行路径。

架构 identity 是命名语义，与责任/接口/理由分开；现有设计不因名称的 COMPOUND verdict 单独 hard veto，但仍检查 admissibility。这是明确记录的 placement 差异，不是任意建议绕过审查。

验收则强调“一项能独立执行并判 PASS/FAIL 的检查”；相关性验证和 OCR 可检索性可以分别失败，不能因为属于同一场景就合成一项。

## 5. 可观测性如何找到真正的 provider 问题

曾出现 verifier 配置 `thinking_enabled=False`，实际 request 却未传递关闭参数。历史旧 verifier 模型的四组交替 A/B 里，current mode 的 median 为 17.493s，explicit thinking off 为 1.509s，verdict/atomicity 一致；只记录 reasoning 是否存在，不记录内容。

修复只传播 Qwen capability 支持的参数，不给其他 OpenAI-compatible provider 无条件塞 Qwen-only keys。没有同时改 timeout/retry/concurrency，以免无法判断因果。该小样本不代表所有模型的通用速度保证。

另外，HTTP 403 曾被粗粒度 auth_error 混淆。现在区分 401 AuthenticationError 与 403 PermissionDeniedError，并在 evaluation 中安全保留 status/SDK class/provider code。`AllocationQuota.FreeTierOnly` 说明一次额度/权限边界，不能据此把全部 403 硬编码成 quota_error，或为它自动重试。

这些问题与 Qwen INADMISSIBLE 或 COMPOUND 完全不同：前者连 verdict 都没拿到，后者是建议审查结果。

## 6. Benchmark 为什么拆成分层评估

一个 E2E FAIL 无法说明系统哪里失败，更不能给未形成方案的场景打“低质量”分数。因此报告分开 provider availability、generation contract validity、deterministic admission、Qwen admission、assembly/persistence 和 final solution quality。

外部失败记 BLOCKED_PROVIDER，不计 INADMISSIBLE；未到某层记 NOT_REACHED，未评分记 NOT_EVALUATED。quality 只评分真正形成并持久化的最终 V2，附 rubric 版本和 hard gates。

自动 rubric 曾要求至少 5 components 才能取最高数量档，而正式合同最多 4 个。这是评分工具与产品合同的确定性冲突，v2.1 修正数量档并观察显式 flows；不能把旧 87 分与新 91 分当成技术质量提升比较。

## 7. 能拿什么证据展示，不能宣称什么

已确认制造业与企业服务各一次真实方案链路 PASS。企业服务在冻结基线下 Core 首次多写 responsibility，被现有 bounded regeneration 恢复；最终 71 claims 全为 ADMISSIBLE + ATOMIC，Solution 及 317 条 provenance 提交，v2.1 为 91/100，四项自动 hard gates 全 PASS。

这两次 benchmark 的需求分析与事实抽取准备使用固定 fixture；BGE indexing/retrieval、DeepSeek 三段、Qwen、组装和持久化是真实链路。因此能证明固定上下文下成功路径，不证明任意客户原始资料的全自动事实质量，也不证明五场景稳定通过。

317 是来源绑定行数，不是 317 个独立事实。benchmark 生成的是 DRAFT，case key `_approved` 不是新方案已经过人工审核。运行结束清理了本轮业务数据。

## 8. 求职阶段的取舍

选择模块化单体、PostgreSQL/pgvector、已有 provider SDK 和有限工作流，是为了把时间投入合同、安全边界和可验证的业务闭环，而不是展示更多基础设施。

当前保留的限制包括外部额度/权限、结构随机性、single-claim token 成本和同步链路负载能力。没有通过 provider fallback、batch verifier、无界 retry 或删 guard 换成功率。下一阶段若要生产化，应另做工作队列/容量/运维/安全与重复 benchmark 设计，不能把这些写成当前已实现。

## 面试追问的源码入口

- “谁决定事实可用？”：[solution_admission.py](../apps/sales/services/solution_admission.py) / [grounding approval](../apps/knowledge/services/grounding_fact_approval.py)
- “IR 是否偷偷修模型？”：[contract](../apps/sales/services/solution_generation_contract.py) / [converter](../apps/sales/services/solution_semantic_ir_v2.py)
- “并发失败后是否继续浪费调用？”：[bounded verifier scheduler](../apps/sales/services/solution_grounding.py)
- “Qwen 能否成为业务审批者？”：[admissibility prompt](../apps/sales/services/solution_proposal_admissibility_prompt.py) / [human review](../apps/sales/services/solution_review.py)
- “来源在调用期间变了怎么办？”：[generation revalidation](../apps/sales/services/solution_draft.py) / [transactional persistence](../apps/sales/services/solution_persistence.py)
- “真实证据与限制在哪里？”：[benchmark 总结](real-provider-benchmark-summary.md) / [Known Limitations](known-limitations.md)
