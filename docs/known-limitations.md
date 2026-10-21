# Known Limitations

适用核心基线：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。这是求职展示与本地验证项目的交付边界，不以 benchmark 一次成功代替生产能力证明。

## 1. 外部 provider 权限、额度和可用性

DeepSeek、BGE embedding 服务和 Qwen 都有外部账号、模型权限、额度、网络与延迟依赖。历史 Qwen 403 `AllocationQuota.FreeTierOnly` 阻断过真实场景；它不是 proposal 被判 INADMISSIBLE。

当前本地 verifier 配置使用 DeepSeek `deepseek-flash`，不保证余额、权限或服务可用性。401、403、timeout 等按安全 metadata 分类；没有 provider fallback 或针对 403 的自动重试。上游失败仍不得保存部分方案。历史 `qwen3.8-flash` 的真实通过记录不证明新 verifier 的真实通过率；本次切换只做离线工程验证。

生成与验证使用同一 DeepSeek 模型族时，虽然配置与请求分离，仍可能出现相关的模型错误。semantic verifier 保持 veto-only，不能替代 deterministic guards、grounding/provenance 校验或售前人工审批。

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

V2 implementation phase 的 objective/tasks 和 risk 的 mitigation 使用有限、完整子句匹配，
允许“实施前核对可用服务器资源”等明确核对/评估动作继续进入语义审查；这不是自动准入。
混合断言、承诺和伪条件前缀仍被拒绝。识别词表不是通用意图分类器，未覆盖的正常表述仍可能
被误拦截。其他 placement 和 V1 保留原有条件标记规则。风险缓解条目的父级 condition
仅作为不可信语义上下文，不提供事实权限或 guard 豁免。不能靠改快照状态、模型自报意图
或机械加条件前缀提高通过率；precision、semantic veto、atomicity 和来源复核仍独立执行。
运行日志不保留模型原句，不能据此断定某次具体拒绝一定属于上述误拦截。

2026-10-12 本地真实调用：商机 242 / 分析 297 返回 HTTP 422
`solution_draft_not_grounded`。日志定位到 proposal index 33 的 implementation-phase
task，关联 user_scale（known）与 deployment_requirement（unclear），由 scoped unresolved
guard 拒绝，未保存新方案。没有原句证据，尚不能判断是否误拦截；不能把离线回归通过当成
该商机端到端成功。该次调用未改需求/分析、旧方案 150 或审核记录 92。

后续一次受限复现定位到 implementation-phase objective 的核验目标被旧 guard 误拒绝，
尚未进入 semantic verifier。修正将 objective 纳入同一候选识别，并支持有限项目限定语及
实施边界/环境可用性核验，以及有限的实施依赖限定语和环境/部署边界核验；不是把核验结果
预先认定为已确认，也不扩大其他 placement。自由中文的未覆盖变体仍可能误拦截。

生成输入提供有限的待执行核验表达示例，以降低“确认环境可用”等歧义。示例不是技术结论，
不能保证模型服从或真实流程稳定成功；不会自动改写结果，也不豁免严格结构或语义审核。

2026-10-13 为商机 242 / 分析 297 增加上述输入指导后的一次真实正式调用仍未保存方案。
Implementation 首次返回 5 个阶段，超过原合同的 4 个上限；既有第二次生成通过结构校验，
三个 pass 合计 69 条建议。随后第 44 条任务的组合核验表达由 scoped unresolved guard
以 `unresolved_as_confirmed` 拒绝，semantic verifier 调用数为 0，HTTP 422。未改客户需求、
分析 297、旧方案 150 或审核 92。该结果暴露有限动作识别仍不覆盖组合核验表述，不能据此
推断客户条件不足或数据库故障；单独调整输入指导尚未证明该商机端到端成功。

随后针对该表述修正了环境限定语与网络访问边界的闭合对象识别，仍仅在上述三个位置提供
核验候选。环境名称限定为有限 ASCII 标识词，不是通用中文意图识别；其他未覆盖对象或
修饰语仍可能被保守拒绝。组合核验被识别不等于建议准入或 atomicity 通过，仍需全部
语义否决与返回时来源复核，不能由离线通过推断真实生成成功。

相同日期对最终“每个对象均可带环境限定语”版本的一次真实调用，Core 首次超出单个组件
responsibilities 数量上限；既有第二次生成通过，三段合计 64 条建议。首个正式拒绝变为
implementation-phase `timing`，由未改变的 `_asserts_unresolved_as_confirmed` 拒绝，
HTTP 422，semantic verifier 调用数仍为 0，未保存新方案，四条既有业务记录保持不变。
只读诊断还发现其他表述可能被现有有限规则保守拒绝，不能将诊断探针当成全部建议的最终
审核结论。当前修复只解决已复现的两类对象列表限定语问题；跨字段前置条件、核验成果与
风险表述仍需单独设计，不能宣称该商机端到端通过或继续以词库补丁保证成功。

重新索引或审批改变可能使历史方案 stale；系统保留历史来源快照，但不能保证旧方案永远可用。未确认事实不能为提高通过率被编造。

## 7. 演示与真实 benchmark 的外推限制

2026-10-13：新增 V2 统一规划用途策略覆盖 8 个合法组合（phase 4 / risk 3 / milestone outcome）。
候选仍须 precision、semantic veto/atomicity 和返回时 provenance 校验；核验完成不能释放未确认的
部署/容量等结果依赖，不相关的预算满足也不能释放部署条件。表达解析依然有限，不理解任意自然语言。
无法识别的尾句不能取消明确未知对象的关联检查；未知表达仍失败关闭，错误提示技术核对而非盲目补客户资料。
不增加输出字段、预算、重试或模型调用，不自动修改模型原文。本轮商机242/快照297的一次真实调用，
Core31、Implementation13、Assurance20 全部结构校验通过，但第32条建议（index31）的 phase objective
被统一策略的 invalid_requirement_linkage 拒绝，HTTP422 invalid_solution_grounding_input。
semantic verifier 未触及（0次），没有新方案/provenance/审核，原需求与四类历史记录哈希保持不变。
workflow caebd5cf-73aa-5f65-96e4-ce01938429ee 在实际后端 GET 中为 FAILED，不能宣称端到端通过。
普通安全记录仅定位栏目、序号与类别，未保存失败原句与原关联列表，不能据此认定具体缺哪个关联或客户条件不足。
已停止重试；下一次受控定位/修正需要另行获准，不以猜测扩词或宽松准入换成功。

后续经用户单独批准的定位请求 f07828ca-391d-5566-8474-e70c71aefde3，Core29/Implementation17 通过，
Assurance 两次均在 acceptance 条目出现 unknown_key（首个位置 index4，第二次 index2；合法外层键仅
criterion/ref），HTTP422 solution_draft_invalid_response。没有到达原需求关联检查，不能据此还原或认定
前一次关联失败原句。semantic/global/确定性/保存均未触及，无新方案/审核，原记录不变。现有调用预算
已停止；不能用这次结果宣称关联问题已经修复，也不能把格式错误解释为客户缺条件。

随后按用户确认的范围，仅补充 Assurance 提示词中的验收外层、嵌套 claim 与独立阶段关系说明。
严格闭合字段、引用、需求关联、事实准入、语义否决和人工审核均不放宽；不修改失败输出或历史记录。
本次没有新的真实模型请求，不知道前次未知键的准确名称，也不宣称旧关联问题或真实方案生成已通过。
本轮新增 11 项请求指导/真实解析器测试（其中 3 项先失败再通过），相关测试 180 项通过；
完整后端回归 2,654 项、前端 119 项及构建均通过，独立只读检查未发现问题。
这些结果仅验证当前代码与合同一致，不是商机242/快照297的真实生成通过证据。
该轮结束时后端以 `--noreload` 运行，尚未加载提示词调整，需要重启项目后端才生效。

2026-10-14：用户另行明确批准仅一个真实生成请求。启动已停止的项目 Django/Vite，加载最新提示词，
不操作 PostgreSQL 服务/配置。workflow `91ca70d4-b7cb-5c19-8930-96f97b9c6bae` 的 Core29、
Implementation14、Assurance20 最终均通过结构解析，global63 通过；Implementation 首次 tasks/timing
为9，超出当次8的上限，由原有一次结构修正后通过。Assurance 本次未发生此前的 acceptance 额外键错误。
最终在第30条建议（index29、phase objective）被确定性 `invalid_requirement_linkage` 拒绝，HTTP422。
受控观察确认：条目依赖尚不明确的 `deployment_requirement`，但原关联仅为
`existing_environment / integration_requirement`，缺少直接部署关联。仅在内存中补关联的离线探针
仍返回 `expression_unclassified`：现有有限表达语法也不能识别该原句。探针不改写模型输出或数据库。
语义审核/组装/保存均未到达，无新方案/provenance/审核，五组原记录哈希不变。
真实后端 GET 返回 FAILED、无方案或可执行动作。此次授权已用完，不再生成；不能把问题归因于
客户必须补齐条件，也不能仅补关联便声称可生成。下一步需要审视生成指导与有限表达策略的匹配，
另行确认修正范围；事实、引用、状态和人工审核底线仍保持不变。

随后按用户确认的范围补充部署关联生成指导，以及条件与技术接入动作的有界表达识别。
对同一实际快照做只读、内存探针：原漏关联仍为 `invalid_linkage`；补齐部署关联后原句
可成为候选，不再因本次句型不可识别而拒绝。探针不改写任何业务记录或模型输出。
新增技术动作仅覆盖检索入口、上传索引、检索服务的闭合对象组合；其它未知句型仍失败关闭，
不宣称任意实施表述已被支持。核验完成不能代替满足条件；其它未确认前提仍须覆盖。
新增 30 项回归（含两项内存退化探针）通过；相关专项 186 项、完整后端 2,684 项、
前端 119 项测试及构建均通过，独立只读检查未发现问题。
通用 fixture 的未确认集成状态另作为反例保留，不能为使观测句通过而放宽其它前提覆盖。
本轮没有新真实生成请求，已有失败 workflow 不改写。2026-10-14 随后按用户明确要求重启
项目后端，已加载该修改；后端/Admin 与前端均返回 HTTP200，不操作 PostgreSQL。
真实生成仍须另行获准验收，不能因重启或离线测试通过便宣称商机242的生成成功。

`seed_demo` 为离线 deterministic 产品演示，不能作为真实 LLM 质量证据。真实成功 benchmark 使用固定非敏感需求与企业事实 fixture 作为准备上下文，没有衡量任意真实客户文档的分析/事实抽取质量。

已确认制造业与企业服务各一个成功运行，运行 commit 也不同。尚未证明同一基线下五场景的重复稳定性；不隐藏历史 contract/provider failures，不把 `NOT_EVALUATED` 报成零分或通过。

## 8. 尚未扩展的产品范围

没有自动技术 revision loop、自动最终合同/报价承诺或已验证的生产部署。Word/PDF 已审核方案导出有独立实现与校验合同，不代表支持 Word 知识文档原生导入。退回分别交给 Sales 补客户信息、Presales 修技术方案；程序不能代替这些职责。

2026-10-15 的 Admin 资料入口源码扩展接通普通上传与显式待审事实抽取，并以持久化执行记录防重。
它没有新增任务队列、限流或自动审批，仍须先部署新增知识域 schema；本轮不自动在业务库迁移，
不以 fake-provider 测试代替真实抽取质量与生产验证。操作和失败恢复见 [后台资料流程](admin-knowledge-workflow.md)。

业务库中方案已进入 `PENDING_REVIEW`、而 LangGraph 线程仍停在 sales 确认中断时，该线程没有恢复入口：checkpoint 只保存编排路由状态，不是业务真值，也不回填历史。该版本仍可通过 REST 审核路径完成，不存在数据损坏，属可用性死胡同；在出现真实误拦案例前不实现自动推进线程，也不让程序替人补一次业务决定。

对求职展示而言，保留这些限制比机械增加重试、全部扩预算、放宽 verifier 或删 safety guard 更可信。后续若要生产化，应另做容量/延迟/安全/运维设计与验证，不视为当前项目已具备。

## 9. 速率限制是进程内近似，不是全局配额

DRF throttle 的计数保存在 `LocMemCache`，每个进程独立。多 worker 部署下，实际允许速率约为配置值乘以 worker 数；同一账号跨 worker 的请求不会被合并计数，因此不能宣称"全局精确限流"或"租户级公平调度"。

当前用途是降低匿名暴力破解与大额 provider 误用的成本，不是计费配额，也不是容量规划依据。计数身份分两类：匿名桶（`anon`、`login`、`token_refresh`）按客户端地址，认证桶（`user` 与方案生成、需求分析、RAG 问答、知识写入）按用户主键。匿名桶的可信度取决于部署——反代必须用 `$proxy_add_x_forwarded_for`（追加）或 `$remote_addr`（覆盖）传递 `X-Forwarded-For`，且 `DRF_NUM_PROXIES` 必须等于本进程之前的可信反代层数。层数设小会把同一反代后的所有客户端并进一个桶，设大会取到客户端自报的那一段，两种错配都必须在部署时排除。登录与续期使用不同 scope，撞库不会连带阻塞合法续期，但共享出口下的客户端仍会互相牵连。生产设置要求显式配置每个 scope 的速率与 `DRF_NUM_PROXIES`，缺失即启动失败；本地与测试使用 `.env.example` 中的默认值。

若要全局精确，需要接入共享缓存（如 Redis）或边缘层限流，并单独验证一致性与故障降级行为。

详见 [架构](architecture.md)、[真实 benchmark](real-provider-benchmark-summary.md)、[分层评估](benchmark-layered-evaluation.md)。
