# Real-provider benchmark：已确认结果

交付文档日期：2026-10-04。核心功能冻结基线：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。

本页整理已完成运行的安全摘要与人工确认，不在本次文档工作中调用 provider。它不是新一轮 benchmark，也不是五场景通过率承诺。

## 实验范围与可信度

固定场景来自 [Stage 6 fixtures](../apps/sales/demo_fixtures.py)：`manufacturing_knowledge`、`retail_collaboration`、`enterprise_service_approved`、`manufacturing_identity`、`ecommerce_ha_revision`。不为通过率修改客户需求。

这两次成功运行的真实外部调用包括：production BGE-M3 indexing/query embedding、正式 retrieval、三段 DeepSeek generation、Qwen single-claim admissibility；然后经过正式 V2 assembly 与 Solution/Provenance persistence。

准备上下文使用固定非敏感 benchmark 文档、`DemoRequirementAnalysisProvider` 和 `DemoGroundingExtractionProvider`。事实仍由具备正式权限的临时 reviewer 经审批服务批准。这说明评估的是**固定已分析需求/已准备事实下的真实方案生成链**，不是对真实客户原始资料的全自动需求分析或 fact extraction 准确率测量，更不是 LLM 自行批准事实。

每个场景人工发起一次；内部 strict contract 拒绝允许既有 pass-level bounded regeneration。没有手工修 JSON、放宽 parser、删除失败 claim 或跳过 guards/verifier。benchmark 使用 run-owned 数据，评分后清理业务记录；生成成功不代表人工 review APPROVED。

## 两次成功运行：分层汇总

| 指标 | Manufacturing Knowledge | Enterprise Service |
| --- | --- | --- |
| 场景 key | `manufacturing_knowledge` | `enterprise_service_approved` |
| 实际运行 commit | `33157edde3934ef5e17a1764ab2ce695a4916855` | `1141281c07b2f5f92d51151fc9b2f0803814ef60` |
| Provider availability | BGE / DeepSeek / Qwen 均 PASS | BGE / DeepSeek / Qwen 均 PASS |
| Compatible chunks / retrieval results / facts | 3 / 3 / 13 | 3 / 3 / 13 |
| Core attempts / final claims / parser | 1 / 39 / PASS | 2 / 38 / PASS |
| Implementation attempts / claims / parser | 1 / 18 / PASS | 1 / 13 / PASS |
| Assurance attempts / claims / parser | 1 / 20 / PASS | 1 / 20 / PASS |
| Combined / global ceiling | 77 / 84，PASS | 71 / 84，PASS |
| Deterministic admission | PASS | PASS |
| Qwen calls / successful responses / provider errors | 77 / 77 / 0 | 71 / 71 / 0 |
| ADMISSIBLE / INADMISSIBLE | 77 / 0 | 71 / 0 |
| ATOMIC / COMPOUND | 77 / 0 | 71 / 0 |
| First hard veto | 无 | 无 |
| Assembly | PASS | PASS |
| Solution / provenance committed rows | 1 / 371 | 1 / 317 |
| Partial persistence | 0 | 0 |
| Final quality | NOT_EVALUATED | `solution-quality-v2.1`：91/100，PASS |
| E2E wall latency | 95.119s | 98.369s |

制造业 PASS 属于前一个运行 commit，不声称已在冻结基线重新执行。两个样本均成功，不意味着五个场景在同一个 commit 全部成功，也不构成稳定性或延迟分位数结论。

Qwen 两次均使用 `qwen3.8-flash`、DashScope compatible-mode、`enable_thinking=false`、concurrency=2、timeout=60s、retries=0。这些是实验配置，不是 provider 永久可用性的保证。

## Bounded regeneration 的真实恢复

企业服务 Core attempt 1 被正式 parser 拒绝：

```yaml
category: component_cardinality
path: $.architecture.components[1].responsibilities
expected: 1..2 items
actual: 3 items
```

既有机制只重新生成该 pass 一次，attempt 2 完整通过，保留 38 条 claim；后两段各一次通过。没有重跑整个场景，没有修补旧输出，也没有绕过该局部上限。这证明有限恢复路径曾有效，不证明它总能恢复随机结构错误。

## 企业服务质量评分

评分对象为已成功持久化并 round-trip 验证的最终 Solution V2，而不是 DeepSeek raw JSON 或 deterministic demo payload。

| 维度 | 得分 / 满分 |
| --- | ---: |
| 推荐 / 理由 / 约束与取舍 | 16 / 20 |
| 技术架构 | 20 / 20 |
| 部署与集成 | 11 / 15 |
| 实施计划 | 15 / 15 |
| 风险与缓解 | 10 / 10 |
| 验收标准 | 10 / 10 |
| 事实重复控制 | 4 / 5 |
| 章节一致性与可读性 | 5 / 5 |
| 总计 | **91 / 100** |

四项自动 hard gates 均为 true：`facts_not_fabricated`、`no_unsupported_precise_commitment`、`fact_provenance_binding_exact`、`proposals_do_not_conflict`。架构/实施/验收最低门槛也通过。

这些是 [自动 evaluator](../apps/sales/tests/test_solution_quality_v2.py) 在固定 benchmark 上的有限检查，不是对全部自然语言内容无幻觉的证明，更不能替代售前审核。部署/集成与推荐取舍仍有扣分；不把达到总分目标当作方案无缺陷。

历史 87/100 来自旧 rubric。v2.1 修正了最多 4 组件却需至少 5 个才能取最高数量档的冲突，并改为观察显式 dependency/request/data flow。不能将 87→91 宣称为质量提升；详见 [rubric 版本说明](solution-quality-rubric.md)。

## 成本、来源与清理

| Provider 返回的 verifier usage | Manufacturing | Enterprise Service |
| --- | ---: | ---: |
| Input / prompt tokens | 173,143 | 159,689 |
| Output / completion tokens | 2,852 | 2,956 |
| Total tokens | 175,995 | 162,645 |

这是 Qwen 请求合计，不包含 DeepSeek/BGE 用量；未据此估算价格。single-claim 验证会重复共享上下文，token 成本仍是已知限制。

317 条 provenance 是实际写入的 claim/citation/fact 来源绑定，不是 317 条独立企业事实或 317 次独立审核。两次均先确认事务提交，再清理本轮 users/customers/opportunities/documents/chunks/facts/solutions/provenance 等业务数据；run-owned 剩余记录为 0，未创建 workflow checkpoints。benchmark 场景名含 `_approved` 不授予新生成方案 APPROVED 状态。

## 历史失败与结论边界

此前五场景评估出现过 Core/Assurance strict contract failure，以及 Qwen HTTP 403 `PermissionDeniedError` / `AllocationQuota.FreeTierOnly`。不能把外部权限/额度阻断计作业务质量拒绝，也不能只筛选成功样本后宣称五场景通过。

当前证据支持：系统具备真实生成、严格准入、组装与持久化成功路径，且企业服务有一个 91 分最终样本。仍未证明：五场景同基线重复稳定性、高并发吞吐、生产 SLA 或自动人工审批能力。

后续评估需记录固定 commit、场景、provider 配置与 rubric 版本，并继续分开 availability / contract / deterministic admission / Qwen verdict / persistence / quality。本文不提出提高预算、retry-until-pass 或删除 guard 的方案。

相关入口：[分层口径](benchmark-layered-evaluation.md)、[Known Limitations](known-limitations.md)、[real_provider_benchmark.py](../apps/sales/services/real_provider_benchmark.py)。
