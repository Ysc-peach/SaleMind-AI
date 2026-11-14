"""Semantic-IR pass prompt, kept apart from the closed-parser code."""

import json

from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_errors import SolutionDraftErrorCode
from apps.sales.services.solution_generation_contract import (
    CORE_ARCHITECTURE_OVERVIEW_LIMIT,
    CORE_CAPABILITY_GROUP_ITEMS_LIMIT,
    CORE_CAPABILITY_GROUP_LIMIT,
    CORE_COMPONENT_FIELD_LIMITS,
    CORE_DEPLOYMENT_TOPIC_LIMITS,
    CORE_PROPOSED_SOLUTION_LIMIT,
    IMPLEMENTATION_MILESTONE_FIELD_LIMITS,
    IMPLEMENTATION_PHASE_FIELD_LIMITS,
    IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
    MAX_ARCHITECTURE_COMPONENTS,
    MAX_ASSURANCE_ACCEPTANCE,
    MAX_ASSURANCE_OUT_OF_SCOPE,
    MAX_ASSURANCE_PHASE_ACCEPTANCE,
    MAX_ASSURANCE_RISKS,
    MAX_CORE_PROPOSALS,
    MAX_IMPLEMENTATION_MILESTONES,
    MAX_IMPLEMENTATION_PHASES,
    MAX_IMPLEMENTATION_PROPOSALS,
    SEMANTIC_IR_VERSION,
    validate_citation_allowlist,
)
from apps.sales.services.solution_prompt_v2_helpers import _invalid
from apps.sales.services.solution_prompt_v2_text import _SYSTEM_PROMPT


def _semantic_pass_prompt(
    pass_name: str, runtime_budget: int, *, allowed_source_labels: tuple[str, ...],
) -> str:
    """Keep proposal semantics while replacing repeated placement envelopes."""

    validate_citation_allowlist(allowed_source_labels)
    if not allowed_source_labels:
        _invalid(SolutionDraftErrorCode.INSUFFICIENT_APPROVED_EVIDENCE)
    claim = {"text": "独立应用边界便于隔离业务入口。", "citations": [allowed_source_labels[0]],
             "related_requirement_fields": ["business_goal"]}
    def sample(text: str, *, related_fields: tuple[str, ...] = ("business_goal",)) -> dict:
        return {**claim, "text": text, "related_requirement_fields": list(related_fields)}
    if pass_name == "core":
        example = {
            "ir_version": SEMANTIC_IR_VERSION, "proposed_solution": [sample("设置受控的企业应用入口。")],
            "capability_groups": [{
                "ref": "capability_basis",
                "items": [sample("已批准能力可支撑受控的企业应用入口。")],
            }],
            "architecture": {"overview": [sample("建议将入口与业务处理边界分离。")],
                "components": [{
                "ref": "application", "identity": sample("企业应用入口"),
                "responsibilities": [sample("应用入口接收业务请求。")],
                "rationale": [sample("独立入口便于隔离客户端与内部服务。")],
                "interfaces": [sample("应用入口通过受控接口调用业务服务。")],
            }, {
                "ref": "service", "identity": sample("业务服务"),
                "responsibilities": [sample("业务服务处理应用入口转发的请求。")],
                "rationale": [sample("独立业务边界便于约束内部处理职责。")],
                "interfaces": [sample("业务服务向应用入口返回处理结果。")],
            }], "dependencies": [{"from": "application", "to": "service"}],
                "request_flows": [{"from": "application", "to": "service"}],
                "data_flows": [{"from": "service", "to": "application"}]},
            "deployment_and_integration": {
                "deployment": [sample(
                    "若客户确认目标环境符合本期部署条件，则依照确认后的边界安排部署。",
                    related_fields=("deployment_requirement",),
                )],
                "integration": [], "data_security": [], "environment": [],
            },
        }
        contract = (
            f"Pass 1 — Technical Core：proposals 最多 {MAX_CORE_PROPOSALS} 条，"
            f"组件最多 {MAX_ARCHITECTURE_COMPONENTS} 个；这是上限不是目标。"
            "仅生成 proposed_solution、architecture、deployment_and_integration。"
            "Core 顶层必须有 ir_version、proposed_solution、architecture、deployment_and_integration；"
            "仅可额外有 capability_groups。capability_groups 是 TOP-LEVEL 字段，不属于 architecture，"
            "也不属于任何 component 或 deployment_and_integration。"
            "architecture 必须有 components；只可额外有 overview、dependencies、request_flows、data_flows。"
            "deployment_and_integration 只能包含 deployment、integration、data_security、environment。"
            "capability_groups 的每项必须且只能有 ref、items；items 是 claim 对象列表。"
            "每层 MUST contain only the documented keys。"
            "Do not move fields between levels。Do not add sibling or nested keys。"
            f"局部上限：proposed_solution 最多 {CORE_PROPOSED_SOLUTION_LIMIT} 条；"
            f"architecture.overview 最多 {CORE_ARCHITECTURE_OVERVIEW_LIMIT} 条；"
            f"capability_groups 最多 {CORE_CAPABILITY_GROUP_LIMIT} 组，每组 items 最多 "
            f"{CORE_CAPABILITY_GROUP_ITEMS_LIMIT} 条。"
            "architecture.components 每项恰好一个 identity claim，"
            f"responsibilities 为 1～{CORE_COMPONENT_FIELD_LIMITS['responsibilities']} 条，"
            f"rationale 为 1～{CORE_COMPONENT_FIELD_LIMITS['rationale']} 条，"
            f"interfaces 为 1～{CORE_COMPONENT_FIELD_LIMITS['interfaces']} 条。"
            "architecture.components[].responsibilities：每条 responsibility 只表达一个可独立判断的组件职责。"
            "如果一个组件承担多个独立能力或处理链路，必须拆成多个 responsibility claim。"
            "以下仅示范职责拆分，不要求输出这些能力："
            "BAD responsibility：对文档内容执行知识检索，并处理扫描版 PDF 的 OCR 后内容。"
            "GOOD responsibility claim：负责对文档内容执行知识检索。"
            "GOOD responsibility claim：负责处理扫描版 PDF 的 OCR 后内容。"
            "responsibility 不禁止所有“和/与”句式；只有可以独立成立、独立失败或独立审核的职责才需要拆分。"
            "architecture.components 每项必须且只能包含 ref、identity、responsibilities、rationale、interfaces 五个键；"
            "不得添加 identity_note、description、summary、notes、metadata 或任何其他额外键。"
            "示例中的 architecture.components 即合法五键格式。"
            "ref 是小写结构引用，匹配 [a-z][a-z0-9_]{0,63}；ref 不是展示名称。"
            "dependencies 表示 source 依赖 target；request_flows 表示请求 from 进入 to；"
            "data_flows 表示数据 from 流向 to。三者不可混淆，边端点必须引用本次组件 ref。"
            "dependencies、request_flows、data_flows 中的每个 relation item 只能有 from、to 两个键，"
            "必须恰好是 {\"from\":\"component_a\",\"to\":\"component_b\"} 这样的 JSON 对象；"
            "不得在 relation item 中增加 citations、related_requirement_fields、text、rationale、type、"
            "container_kind、field 或任何其他键。citations、related_requirement_fields 只属于 claim，"
            "绝不属于 relation objects。"
            "两个以上组件至少一条 request_flows；存在真实数据读写时生成 data_flows。"
            "proposed_solution 是总体技术推荐的 atomic claims；architecture.overview 可选；"
            "capability_groups 可选，每项为 ref 与 items。"
            "proposed_solution 数组对应最终 proposed_solution.overview，每条 claim 必须代表一个独立可审核的总体技术推荐。"
            "如果一句 overview 同时包含多个独立技术选型、多个独立系统集成决策，"
            "或多个可以分别批准/拒绝的能力建设，必须拆成多个 overview claim。"
            "以下仅示范拆分方式，不要求输出这些技术选择："
            "BAD overview：建议通过标准接口对接 OA 门户并接入企业 SSO 统一身份。"
            "GOOD overview claim：建议通过标准接口对接现有 OA 门户。"
            "GOOD overview claim：建议接入企业 SSO 实现统一身份管理。"
            "允许同一推荐的目的、条件或紧密配套描述；不按动词数量判断，也不禁止所有“和/与”句式。"
            "允许 overview：建设统一智能服务平台，提升企业知识管理能力。"
            "BAD overview：采用 Kafka、Redis、Kubernetes 完成消息、缓存、高可用部署。"
            "proposed_solution.items（包括 capability_groups[].items）的每个 item 必须只表达一个可独立批准/拒绝的技术判断。"
            "如果一句话包含两个独立能力、技术选择或交付项，必须拆成两个独立 item。"
            "BAD：接口服务能力可支撑 JWT 身份认证与 CSV 批量导出。"
            "GOOD：两个独立 item：接口服务能力可支撑 JWT 身份认证。接口服务能力可支撑 CSV 批量导出。"
            "不禁止所有“和/与”句式；只有可以独立成立、独立失败、独立审批的技术判断才必须拆分。"
            "deployment_and_integration 中 deployment、integration、data_security、environment 的每条 item"
            "只表达一个可独立审核的部署、集成、数据或环境技术判断。"
            "如果一句话同时包含多个可以分别批准/拒绝的技术选型或能力决策，应拆成多条 claim。"
            "以下仅示范拆分方式，不要求输出这些技术选择："
            "BAD deployment_and_integration：建议知识数据服务采用 PostgreSQL，并使用 pgvector 支撑知识检索。"
            "GOOD deployment_and_integration claim：建议知识数据服务采用 PostgreSQL。"
            "GOOD deployment_and_integration claim：建议使用 pgvector 支撑向量检索。"
            "deployment_and_integration 不禁止所有“和/与”句式；"
            "仅拆分可以独立成立、独立失败或独立审核的技术判断。"
            "deployment_and_integration 只允许四个主题列表："
            + "；".join(
                f"{topic} 最多 {limit} 条"
                for topic, limit in CORE_DEPLOYMENT_TOPIC_LIMITS.items()
            ) + "。"
            "单条 proposal 不得合并多个独立技术决策；不生成实施、风险、验收或里程碑。"
        )
    elif pass_name == "implementation":
        example = {
            "ir_version": SEMANTIC_IR_VERSION,
            "phases": [
                {"ref": "discovery", "objective": [sample("确认本期实施边界。")],
                 "tasks": [sample("核对已确认的实施范围。")],
                 "deliverables": [sample("形成实施范围核对记录。")]},
                {"ref": "implement", "objective": [sample("落实已验证的技术方案。")],
                 "tasks": [sample("按已验证方案实施本期功能。")],
                 "deliverables": [sample("形成实施结果记录。")],
                 "timing": [sample("在准备阶段完成后开展实施。")]},
                {"ref": "validate", "objective": [sample("验证本期业务链路。")],
                 "tasks": [sample("验证约定业务场景的执行结果。")],
                 "deliverables": [sample("形成业务场景验证记录。")]}],
            "milestones": [{"ref": "ready", "outcome": [sample("本期业务场景完成验证。")],
                            "phase_refs": ["validate"]}],
            "dependencies": [{"from": "implement", "to": "discovery"},
                             {"from": "validate", "to": "implement"}],
        }
        contract = (
            f"Pass 2 — Implementation Planning：runtime proposal 总预算最多 {runtime_budget} 条，"
            f"implementation_plan 最多 {IMPLEMENTATION_SECTION_PROPOSAL_LIMITS['implementation_plan']} 条，"
            f"milestones 最多 {IMPLEMENTATION_SECTION_PROPOSAL_LIMITS['milestones']} 条；上限不是目标。"
            "只生成 phases 的 objective、tasks、deliverables、可选 timing，"
            "以及 milestones 的 outcome、可选 timing。"
            f"局部上限：phases 最多 {MAX_IMPLEMENTATION_PHASES} 个；"
            f"每个 phase 的 objective 恰好 {IMPLEMENTATION_PHASE_FIELD_LIMITS['objective'][1]} 条，"
            f"tasks 为 {IMPLEMENTATION_PHASE_FIELD_LIMITS['tasks'][0]}～{IMPLEMENTATION_PHASE_FIELD_LIMITS['tasks'][1]} 条，"
            f"deliverables 恰好 {IMPLEMENTATION_PHASE_FIELD_LIMITS['deliverables'][1]} 条，"
            f"timing 为 0～{IMPLEMENTATION_PHASE_FIELD_LIMITS['timing'][1]} 条。"
            "phase tasks + phase timing + milestone timing "
            "必须控制在剩余 Implementation proposal budget 内。"
            "dynamic maximum = MAX_IMPLEMENTATION_PROPOSALS - 2 * phase_count - milestone_count"
            f"（MAX_IMPLEMENTATION_PROPOSALS={MAX_IMPLEMENTATION_PROPOSALS}）；"
            "phase_count 和 milestone_count 是本次实际生成的阶段数和里程碑数。"
            "例如：4 phases + 2 milestones → 最多 8；"
            "4 phases + 1 milestone → 最多 9；"
            "3 phases + 2 milestones → 最多 10。"
            "这是动态剩余额度，不是填满目标；仍须遵守 runtime 总预算和各 section 上限。"
            f"milestones 最多 {MAX_IMPLEMENTATION_MILESTONES} 个；"
            f"每个 milestone 的 outcome 恰好 {IMPLEMENTATION_MILESTONE_FIELD_LIMITS['outcome'][1]} 条，"
            f"timing 为 0～{IMPLEMENTATION_MILESTONE_FIELD_LIMITS['timing'][1]} 条。"
            "dependencies 的 from 阶段依赖 to 阶段；milestone.phase_refs 只引用本次 phases 的 ref。"
            "每个 dependencies 对象恰好只有 from、to 两个必填键，值均为本次 phases 中已定义的 ref；"
            "不要输出 reason、source、target、type 或 relation_type 等额外键。"
            "先按业务需要选择阶段和里程碑数量，再使用 <implementation_budget_options> 中对应行的已计算额度；"
            "shared_work_maximum 是 tasks 与全部 timing 的合计上限，phase_work_maximum 是阶段内 tasks 与 timing 的合计上限，"
            "milestone_timing_maximum 是里程碑 timing 的上限；三项必须同时满足，并遵守每个字段的局部限制。"
            "优先紧凑且业务完整的阶段划分，不默认填满4个阶段和2个里程碑。"
            "timing 可省略；仅在相关需求或证据支持时填写，不为补齐示例添加日期或期限。"
            "示例中的阶段名称和顺序仅展示格式，不能替代对实际项目的实施设计。"
            "ref 是小写结构引用，匹配 [a-z][a-z0-9_]{0,63}。"
            "<validated_technical_core> 已验证，不得重写技术选择或组件；"
            "不生成架构、部署、风险、验收或范围外内容。"
        )
    elif pass_name == "assurance":
        example = {
            "ir_version": SEMANTIC_IR_VERSION,
            "risks": [{"ref": "integration_change", "condition": [sample("若接口契约后续发生变化。")],
                       "impact": [sample("适配器需要返工。")],
                       "mitigation": [sample("实施前验证接口契约。")],
                       "trigger": [sample("若联调时发现接口字段不一致，则触发接口兼容性风险处置。")]}],
            "acceptance": [{"ref": "integration_check", "criterion": [sample("通过适配器调用约定接口，响应中的业务标识应与请求对应。")]}],
            "out_of_scope": [sample("不替换客户现有身份系统。")],
            "phase_acceptance": [{"from": "discovery", "to": "integration_check"}],
        }
        contract = (
            f"Pass 3 — Assurance & Boundaries：runtime proposal 总预算最多 {runtime_budget} 条，"
            f"risks 最多 {MAX_ASSURANCE_RISKS} 个，每个 risk 的 condition、impact、mitigation、trigger 各恰好 1 条；"
            f"acceptance 最多 {MAX_ASSURANCE_ACCEPTANCE} 个，每个 criterion 恰好 1 条；"
            f"out_of_scope 最多 {MAX_ASSURANCE_OUT_OF_SCOPE} 条，"
            f"phase_acceptance 最多 {MAX_ASSURANCE_PHASE_ACCEPTANCE} 条；"
            "phase_acceptance 不计入 proposal 总预算，只表达关系；所有上限都不是生成目标。"
            "只生成 risks 的 condition、impact、mitigation、trigger；"
            "acceptance 的 criterion；out_of_scope。"
            "acceptance 中每个对象恰好只有 ref、criterion 两个必填键。"
            "criterion 是恰好包含 1 个 claim 对象的数组；每个 claim 恰好只有 "
            "text、citations、related_requirement_fields 三个必填键。"
            "验收正文、引用和原始需求关联必须放在 criterion[0] 内，不能提到 acceptance 对象外层；"
            "acceptance 外层不得添加 text、citations、related_requirement_fields、phase_ref 或 phase_refs。"
            "阶段关联只写在顶层 phase_acceptance 数组，每个关系对象恰好只有 from、to 两个必填键。"
            "phase_acceptance 关系不能承载正文、引用或理由，不添加 criterion、citations 或 reason。"
            "acceptance[].criterion 对应最终 acceptance_criteria，按独立验收检查而非阶段成果包组织。"
            "检索相关性与 OCR 可检索性、授权访问与越权阻断、业务结果与引用来源定位，"
            "分别具有独立 PASS/FAIL 结果，应分别验收。"
            "不得使用“端到端集成测试通过”或“阶段验收完成”代替具体检查。"
            "BAD criterion：以交付案例为查询输入执行企业知识查询，返回结果与所查询交付案例相关，且扫描版 PDF 案例经 OCR 后可被检索到。"
            "GOOD criterion：以交付案例为查询输入执行企业知识查询，返回结果应与所查询交付案例相关。"
            "GOOD criterion：扫描版 PDF 案例经 OCR 处理后应能够被企业知识查询检索到。"
            "BAD criterion：授权用户能够获取受限资料，且未授权用户无法获取受限资料。"
            "GOOD criterion：使用具有相应权限的身份查询，能够获取该身份获准访问的受限资料。"
            "GOOD criterion：使用不具有相应权限的身份查询，无法获取受限资料。"
            "risks.condition 描述风险发生条件：如果条件本身有明确客户事实或 grounding fact 支持，可以直接陈述；"
            "如果只是潜在风险场景或尚未证实的问题，必须使用明确条件式表达，"
            "例如若……、如果……、当……发生时、在……未满足的情况下。"
            "禁止把 hypothetical risk 写成当前已存在的客户事实。"
            "以下 BAD 示例在没有事实支持时不可直接断言："
            "BAD：文档级访问控制未覆盖全部知识分类。"
            "GOOD：若角色权限划分未覆盖全部知识分类……"
            "BAD：接口契约发生变化。"
            "GOOD：若接口契约后续发生变化……"
            "BAD：当前权限模型存在遗漏。"
            "GOOD：如果权限模型未覆盖新增知识分类……"
            "条件式表达只说明风险触发条件，不能借此引入没有依据的精确数值、能力或承诺。"
            "risks.trigger 表示未来可观测的风险触发/检测信号，不默认表示客户当前已经出现该问题。"
            "尚未证实的风险信号必须使用条件式或事件式表达，例如："
            "若权限核验发现某类知识文档未映射到任何访问控制维度，则将其视为风险触发信号。"
            "当联调发现接口字段不一致时，触发接口兼容性风险处置。"
            "只有当客户需求或 grounding fact 明确证明问题已经发生时，才允许直接写成既有事实。"
            "条件式表达不能用于包装无依据的数字、能力或承诺。"
            "BAD/AMBIGUOUS trigger：联调时发现接口字段不一致。"
            "GOOD trigger：若联调时发现接口字段不一致，则触发接口兼容性风险处置。"
            "phase_acceptance.from 必须引用 <validated_implementation_plan> 中真实 phase ref，"
            "to 必须引用本次 acceptance.ref。"
            "已确认的 Core/Implementation 不得重写；assumptions 和 open_questions 由程序保留，不生成。"
            "不生成架构、部署、实施或里程碑。"
        )
    else:
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    semantics = _SYSTEM_PROMPT.partition("placement 只用于")[0]
    clarification_guidance = (
        "<clarification_action_style> 仅指导其 targets 中真实核验动作的表达，不是输出字段或事实依据。"
        "若阶段目标、任务或风险措施的真实用途是核验未确认前提，应明确写待执行的核验动作，"
        "例如核验部署条件、评估服务器容量是否满足本期部署需求；不要把待核验的结果写成环境可用或容量足够。"
        "纯核验动作不主张结果已确认；随后依赖核验结果的部署、性能或交付安排仍须体现真实确认前提。"
        "核验完成不等于核验通过或条件满足；条件性建设应明确经核验确认部署条件满足后开展建设。"
        "deliverables 使用计划形成的核验记录；milestones.outcome 使用完成核验并记录结果，不保证条件满足。"
        "risk condition/impact 使用若容量不满足则部署可能受影响的假设，不写成已发生事实。"
        "示例不批准任何能力、状态、引用或建议，实际建议仍须由允许证据支持并通过全部审核。"
        "不得把事实断言或承诺机械改写成核验动作来规避校验，不得改变原始需求关联。"
        "涉及部署条件、服务器容量或承载条件的规划条目，related_requirement_fields 必须包含 deployment_requirement，"
        "不能只用 existing_environment 或 integration_requirement 代替；现有环境配置另保留真实的 existing_environment 关联。"
        "条件性技术接入可以表达为经核验确认部署条件满足后，完成检索入口的接入；"
        "具体技术对象和动作必须由已准入证据支持，按已验证方案等措辞不是批准事实或省略需求关联的依据。"
        "不得将 clarification_action_style 或 targets 等指导键写进输出 JSON。"
        if pass_name in {"implementation", "assurance"} else ""
    )
    return (
        semantics + "\n" + contract + "\n" + clarification_guidance
        + "设计前读取 requirement_design_scope：它只重述当前需求维度状态，不是新的事实或能力审批。"
        "confirmed_fields 中的原始 value/evidence 可作为已确认客户背景，仍必须忠实于其实际内容。"
        "conditional_fields 中 unknown/unclear/conflict 维度不是已确认需求；"
        "如果建议直接依赖其中任一维度，必须在该条 claim 自身说明真实的未确认前提及确认后的安排，"
        "例如若客户确认目标环境满足部署条件，再按确认结果安排部署；不要只在其它条目写一次免责声明。"
        "混合已知背景和未确认容量的维度仍保持原状态，不可自行提取其中一部分并升格为 confirmed。"
        "例如 existing_environment 已确认且 deployment_requirement 尚不明确时，"
        "可以围绕已确认的现有环境提出建议，但不能由此断言其服务器容量足够或部署位置已经确定。"
        "related_requirement_fields 必须保持真实直接关联，不能为了避开边界改关联、清空关联或挂到 business_goal。"
        "不得机械给原句加若、如果、待确认来包装无依据事实、容量、性能、期限或能力；"
        "条件性建议仍需企业证据支持并经过正式语义审核。"
        "只返回紧凑 JSON，不含 Markdown 或 JSON 之外的文字。"
        f"顶层必须使用示例中的 ir_version={SEMANTIC_IR_VERSION} 和本 pass 专用字段，不得输出旧版 proposals 列表。"
        "每条 claim 恰好只有 text、citations、related_requirement_fields。"
        "citations 至少一项且只使用 <allowed_citation_ids> 中逐项列出的准确编号；"
        "编号可能不连续，不得从 S1...Sn 推断、补齐或重编号，不可编造或自动补引用。"
        "其他上下文或已准入事实中出现的 citation 编号不自动获得 proposal 引用许可。"
        "示例使用本次合法编号只为展示格式，不证明示例技术结论；"
        "实际 claim 仍必须由其所引用的、允许使用的企业能力证据支持。"
        "related_requirement_fields 只允许当前分析中确实存在、且直接相关的维度；"
        f"合法 RequirementDimension：{', '.join(item.value for item in RequirementDimension)}。"
        "无直接相关维度时使用 []。所有列表的最大值不是填充目标；优先简洁且不重复的原子判断。"
        "示例仅展示格式，不能照抄示例的技术结论："
        + json.dumps(example, ensure_ascii=False, separators=(",", ":"))
    )
