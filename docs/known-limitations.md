# Known Limitations

适用核心基线：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。这是求职展示与本地验证项目的交付边界，不以 benchmark 一次成功代替生产能力证明。

## 1. 外部 provider 权限、额度和可用性

DeepSeek、BGE embedding 服务和 Qwen 都有外部账号、模型权限、额度、网络与延迟依赖。历史 Qwen 403 `AllocationQuota.FreeTierOnly` 阻断过真实场景；它不是 proposal 被判 INADMISSIBLE。

当前展示配置使用 `qwen3.8-flash`，不保证任意账号或未来时刻均可调用。401、403、timeout 等按安全 metadata 分类；没有 provider fallback 或针对 403 的自动重试。上游失败仍不得保存部分方案。

## 2. LLM 结构输出随机性

JSON mode 不等于严格 schema compliance。模型仍可能多写 key、放错层级、引用不存在的 ref、超过局部数量限制，或混合独立技术判断。

Semantic IR 降低了模型承担的结构负担，closed parser/converter 保证非法输出不会静默入库。每段最多一次 strict-contract regeneration 只能有限恢复，不能保证所有场景成功；不自动修 JSON、删除 claim 或放宽合同。

## 3. 单 claim verifier 的成本

single-claim packet 有利于独立准入判断，但共享需求和 evidence 随每次请求重复。企业服务成功样本用 71 次请求，Qwen 返回合计 159,689 input / 2,956 output tokens。一个样本不是稳定成本或速度承诺。

thinking propagation 已修正、有限 in-flight 调度降低失败后的无效工作，但不消除请求成本。当前没有 batch verifier，也不能因费用跳过 claim 审查。

## 4. 同步链路不是高并发生产系统

当前请求内完成 retrieval、三段 generation、verifier 与 persistence；网络调用在数据库长事务外，但用户仍等待整条同步链路。concurrency=2 只限制一份方案的 verifier 请求，不是跨 worker/租户的全局限流。

LangGraph checkpoint 提供审核中断/恢复和幂等编排，不等于后台任务队列。尚未建立高负载、账号公平调度、生产部署/容灾或 SLA 的验证证据。

## 5. 自动评分与模型 verdict 的边界

`solution-quality-v2.1` 是固定场景的 evaluation-only rubric，观察结构、关系、有限文本模式及事实来源，不代表真正专家评审。91 分不能证明所有技术选型合理、容量足够或风险穷尽。

Qwen 也可能误判支持度或 atomicity。其角色是 veto-only，不会授权事实、修改来源或批准方案。最终技术使用仍需有权限的售前人员 review；生成成功只产生 DRAFT。

## 6. Grounding 的覆盖依赖知识准备

高相关检索结果仍可能不含足够企业能力依据。知识必须先建与当前 provider/model/dimension 匹配的索引，并将事实提议经授权审批。

当前 guard 的条件表达和 precision 识别是有限 deterministic rules，不是全面语言理解。严格 parser 只证明结构合法，不证明文本真实；RAG、guard、Qwen 和人工审核各自提供不同防线。

重新索引或审批改变可能使历史方案 stale；系统保留历史来源快照，但不能保证旧方案永远可用。未确认事实不能为提高通过率被编造。

## 7. 演示与真实 benchmark 的外推限制

`seed_demo` 为离线 deterministic 产品演示，不能作为真实 LLM 质量证据。真实成功 benchmark 使用固定非敏感需求与企业事实 fixture 作为准备上下文，没有衡量任意真实客户文档的分析/事实抽取质量。

已确认制造业与企业服务各一个成功运行，运行 commit 也不同。尚未证明同一基线下五场景的重复稳定性；不隐藏历史 contract/provider failures，不把 `NOT_EVALUATED` 报成零分或通过。

## 8. 尚未扩展的产品范围

没有自动技术 revision loop、自动最终合同/报价承诺、Word 交付生成或已验证的生产部署。退回分别交给 Sales 补客户信息、Presales 修技术方案；程序不能代替这些职责。

对求职展示而言，保留这些限制比机械增加重试、全部扩预算、放宽 verifier 或删 safety guard 更可信。后续若要生产化，应另做容量/延迟/安全/运维设计与验证，不视为当前项目已具备。

详见 [架构](architecture.md)、[真实 benchmark](real-provider-benchmark-summary.md)、[分层评估](benchmark-layered-evaluation.md)。
