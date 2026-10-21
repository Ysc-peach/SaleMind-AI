"""Readable, deterministic inputs for the SalesMind production demo dataset.

These providers implement the same public contracts as configured providers,
but perform no network I/O.  Business parsing, admission, verification,
persistence, stale, and review services remain the production implementations.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID, uuid5

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.llm.base import LLMGeneration, LLMMessage, LLMProvider
from apps.sales.services.requirement_analysis import RequirementDimension


DEMO_NAMESPACE = UUID("23dc62a1-8f7c-4eca-8d6c-6ed354b7942a")


@dataclass(frozen=True, slots=True)
class DemoIdentity:
    key: str
    username: str
    email: str
    role: str
    first_name: str
    last_name: str
    is_staff: bool = False


@dataclass(frozen=True, slots=True)
class DemoKnowledgeFixture:
    key: str
    title: str
    filename: str
    document_type: str
    content: str
    facts: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class DemoScenario:
    key: str
    customer_name: str
    industry: str
    company_size: str
    customer_summary: str
    project_name: str
    sales_key: str
    presales_key: str
    business_goal: str
    use_scenario: str
    user_scale: str
    deployment_requirement: str
    data_security_requirement: str
    existing_environment: str
    integration_requirement: str
    technical_constraints: str
    solution_focus: str
    target_outcome: str


DEMO_IDENTITIES = (
    DemoIdentity(
        "sales_a",
        "salesmind_demo_sales_a",
        "sales-a@demo.salesmind.invalid",
        "sales",
        "演示销售",
        "A",
    ),
    DemoIdentity(
        "sales_b",
        "salesmind_demo_sales_b",
        "sales-b@demo.salesmind.invalid",
        "sales",
        "演示销售",
        "B",
    ),
    DemoIdentity(
        "presales_a",
        "salesmind_demo_presales_a",
        "presales-a@demo.salesmind.invalid",
        "presales",
        "演示售前",
        "A",
    ),
    DemoIdentity(
        "presales_b",
        "salesmind_demo_presales_b",
        "presales-b@demo.salesmind.invalid",
        "presales",
        "演示售前",
        "B",
    ),
    DemoIdentity(
        "admin",
        "salesmind_demo_admin",
        "admin@demo.salesmind.invalid",
        "admin",
        "演示管理员",
        "",
        True,
    ),
)


DEMO_KNOWLEDGE = (
    DemoKnowledgeFixture(
        key="knowledge_platform",
        title="SalesMind 演示资料：企业知识平台能力",
        filename="salesmind-demo-knowledge-platform.txt",
        document_type="product",
        content=(
            "企业知识平台支持面向内部员工的企业知识查询。\n"
            "企业知识平台支持扫描版 PDF 的 OCR 后知识检索。\n"
            "企业知识平台支持基于已审核模板生成合同草案。\n"
        ),
        facts=(
            ("enterprise_knowledge_query", "企业知识平台支持面向内部员工的企业知识查询。"),
            ("scanned_pdf_ocr", "企业知识平台支持扫描版 PDF 的 OCR 后知识检索。"),
            ("contract_generation", "企业知识平台支持基于已审核模板生成合同草案。"),
        ),
    ),
    DemoKnowledgeFixture(
        key="integration",
        title="SalesMind 演示资料：企业集成与权限能力",
        filename="salesmind-demo-integration.txt",
        document_type="technical",
        content=(
            "集成组件支持通过标准接口对接企业 OA。\n"
            "集成组件支持企业 SSO 统一身份接入。\n"
            "接口服务支持 CSV 批量导出。\n"
            "接口服务支持 JWT 身份认证。\n"
        ),
        facts=(
            ("oa_integration", "集成组件支持通过标准接口对接企业 OA。"),
            ("sso_integration", "集成组件支持企业 SSO 统一身份接入。"),
            ("csv_bulk_export", "接口服务支持 CSV 批量导出。"),
            ("jwt_authentication", "接口服务支持 JWT 身份认证。"),
        ),
    ),
    DemoKnowledgeFixture(
        key="deployment",
        title="SalesMind 演示资料：私有化与高可用部署能力",
        filename="salesmind-demo-deployment.txt",
        document_type="case",
        content=(
            "交付方案支持在客户内网进行私有化部署。\n"
            "私有化部署支持业务数据保留在客户内网。\n"
            "数据服务支持 PostgreSQL。\n"
            "知识检索服务支持 pgvector。\n"
            "应用服务支持 Kubernetes 部署。\n"
            "应用服务支持部署在标准 Linux 服务器环境。\n"
        ),
        facts=(
            ("private_deployment", "交付方案支持在客户内网进行私有化部署。"),
            ("intranet_data_residency", "私有化部署支持业务数据保留在客户内网。"),
            ("postgresql", "数据服务支持 PostgreSQL。"),
            ("pgvector", "知识检索服务支持 pgvector。"),
            ("kubernetes_deployment", "应用服务支持 Kubernetes 部署。"),
            ("server_compatibility", "应用服务支持部署在标准 Linux 服务器环境。"),
        ),
    ),
)


DEMO_SCENARIOS = (
    DemoScenario(
        "manufacturing_knowledge",
        "华辰精工（演示）",
        "制造业",
        "约 1200 人",
        "多工厂技术资料分散，需在客户内网统一检索并保留来源依据。",
        "华辰精工企业知识平台（演示）",
        "sales_a",
        "presales_a",
        "建设可追溯的内部技术知识查询平台",
        "研发与售后人员查询设备手册、工艺规范和历史案例",
        "约 600 名内部用户",
        "客户内网私有化部署",
        "生产与技术资料不得离开客户内网",
        "Linux 服务器与 PostgreSQL 数据库",
        "对接现有 OA 门户",
        "采用 PostgreSQL 并保留文档级访问控制",
        "制造业知识检索与来源追溯",
        "等待销售确认后提交售前审核",
    ),
    DemoScenario(
        "retail_collaboration",
        "云岭新零售（演示）",
        "零售与电商",
        "约 800 人",
        "门店、仓储和电商团队需要统一查询多系统业务资料。",
        "新零售业务协同平台（演示）",
        "sales_a",
        "presales_a",
        "整合门店、库存与商品运营知识",
        "运营人员跨 OA 和业务系统查询商品与流程资料",
        "约 350 名运营用户",
        "企业内网部署",
        "经营数据仅在企业受控网络内处理",
        "Linux 应用服务器与现有 OA",
        "通过标准接口接入 OA 并支持 CSV 批量交换",
        "统一身份认证并记录来源",
        "零售业务数据协同与统一入口",
        "等待已分配售前进行技术审核",
    ),
    DemoScenario(
        "enterprise_service_approved",
        "启明企业服务（演示）",
        "企业服务",
        "约 300 人",
        "顾问需要在交付过程中复用已审核的合同模板和项目知识。",
        "企业服务知识助手（演示）",
        "sales_a",
        "presales_b",
        "建立面向顾问团队的知识与合同草案助手",
        "顾问检索交付案例并基于已审核模板形成合同草案",
        "约 180 名顾问",
        "私有化部署",
        "客户项目资料不得传输至公网",
        "Kubernetes、Linux 与 PostgreSQL",
        "接入企业 SSO 和 OA",
        "使用 PostgreSQL 与 pgvector",
        "企业服务知识复用与合同草案协作",
        "已经完成内部技术审核",
    ),
    DemoScenario(
        "manufacturing_identity",
        "恒川装备（演示）",
        "制造业",
        "约 2000 人",
        "统一员工入口需要接入客户身份平台，具体 SSO 协议待客户确认。",
        "制造业统一身份集成（演示）",
        "sales_b",
        "presales_a",
        "为多工厂员工提供统一知识入口",
        "员工从 OA 进入企业知识平台",
        "约 900 名员工",
        "客户内网私有化部署",
        "账号和知识数据保留在客户内网",
        "Linux 服务器与客户统一身份平台",
        "需要 SSO 统一登录，协议与字段映射尚待客户确认",
        "兼容客户现有 PostgreSQL 环境",
        "制造业统一身份与知识入口",
        "需要销售向客户补充确认 SSO 协议和字段映射",
    ),
    DemoScenario(
        "ecommerce_ha_revision",
        "星河电商（演示）",
        "电子商务",
        "约 1500 人",
        "业务团队需要高峰期稳定访问知识与运营资料，并与现有系统集成。",
        "电商平台高可用改造（演示）",
        "sales_b",
        "presales_b",
        "提升知识服务在业务高峰期的可用性",
        "客服与运营团队持续查询商品、活动和服务知识",
        "约 700 名内部用户",
        "Kubernetes 私有化部署",
        "订单与客户资料不得离开企业网络",
        "Kubernetes、Linux 和 PostgreSQL",
        "通过 OA 入口和 JWT 接入现有平台",
        "数据库使用 PostgreSQL，应用需支持水平扩展",
        "电商知识服务高可用架构",
        "客户事实充分，但高可用技术设计需要调整",
    ),
)


def demo_workflow_id(scenario_key: str) -> UUID:
    """One stable identity shared by workflow thread and generation idempotency."""

    return uuid5(DEMO_NAMESPACE, f"{scenario_key}:solution:v1")


class DemoEmbeddingProvider(EmbeddingProvider):
    """Contract-valid 1024-dimensional embeddings with no external call."""

    @property
    def provider_name(self) -> str:
        return "salesmind_demo_offline"

    @property
    def model_name(self) -> str:
        return "deterministic-1024-v1"

    @property
    def dimensions(self) -> int:
        return 1024

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Demo embedding input must be non-empty text.")
        vector = [0.0] * self.dimensions
        normalized = re.sub(r"\s+", "", text.lower())
        tokens = set(normalized[index : index + 2] for index in range(len(normalized) - 1))
        for token in tokens or {normalized}:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        magnitude = sum(value * value for value in vector) ** 0.5
        return [value / magnitude for value in vector]


class DemoRequirementAnalysisProvider(LLMProvider):
    def __init__(self, scenario: DemoScenario):
        self.scenario = scenario

    @property
    def provider_name(self) -> str:
        return "salesmind_demo_offline"

    @property
    def model_name(self) -> str:
        return f"analysis-{self.scenario.key}-v1"

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        del messages, max_output_tokens
        snapshot = self.legacy_snapshot_payload()
        payload = {key: snapshot[key] for key in ("summary", "requirements", "conflicts")}
        return LLMGeneration(json.dumps(payload, ensure_ascii=False))

    def legacy_snapshot_payload(self) -> dict:
        """Explicit v1 fixture for validating existing, immutable demo records.

        The provider only emits generation facts; historical questions are not
        submitted to the new generation parser or regenerated on reads.
        """
        known = {
            "business_goal": self.scenario.business_goal,
            "use_scenario": self.scenario.use_scenario,
            "user_scale": self.scenario.user_scale,
            "deployment_requirement": self.scenario.deployment_requirement,
            "data_security_requirement": self.scenario.data_security_requirement,
            "existing_environment": self.scenario.existing_environment,
            "integration_requirement": self.scenario.integration_requirement,
            "technical_constraints": self.scenario.technical_constraints,
        }
        requirements = {
            key: {"status": "known", "value": value, "evidence": value}
            for key, value in known.items()
        }
        requirements.update(
            {
                "timeline": {"status": "unknown", "value": None, "evidence": None},
                "budget": {"status": "unknown", "value": None, "evidence": None},
            }
        )
        payload = {
            "summary": (
                f"{self.scenario.customer_name}计划{self.scenario.business_goal}；"
                "实施时间和预算仍待客户确认。"
            ),
            "requirements": requirements,
            "conflicts": [],
            "clarifying_questions": [
                {"field": "timeline", "question": "客户期望何时完成首批业务上线？"},
                {"field": "budget", "question": "本项目可用于软件与实施的预算范围是多少？"},
            ],
        }
        return payload


class DemoGroundingExtractionProvider(LLMProvider):
    def __init__(self, fixture: DemoKnowledgeFixture):
        self.fixture = fixture

    @property
    def provider_name(self) -> str:
        return "salesmind_demo_offline"

    @property
    def model_name(self) -> str:
        return f"grounding-{self.fixture.key}-v1"

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        del max_output_tokens
        payload = _tagged_json(messages, "untrusted_knowledge_chunks")
        chunks = payload["chunks"]
        facts = []
        for subject_key, statement in self.fixture.facts:
            source = next(
                (item for item in chunks if statement in item["content"]),
                None,
            )
            if source is None:
                raise ValueError("Demo grounding excerpt is absent from indexed chunks.")
            facts.append(
                {
                    "subject_key": subject_key,
                    "statement": statement,
                    "status": "confirmed_supported",
                    "source_chunk_id": source["source_chunk_id"],
                    "source_excerpt": statement,
                }
            )
        return LLMGeneration(json.dumps({"facts": facts}, ensure_ascii=False))


def _demo_solution_payload(
    scenario_key: str,
    sources: dict[str, str],
) -> dict[str, list[dict]]:
    """Return one scenario-owned proposal graph in the production provider shape."""

    def p(section, kind, key, field, text, source, *requirements):
        return {
            "placement": {
                "section": section,
                "container_kind": kind,
                "container_key": key,
                "field": field,
            },
            "text": text,
            "citations": [sources[source]],
            "related_requirement_fields": [item.value for item in requirements],
        }

    def relation(relation_type, source_kind, source_key, target_kind, target_key):
        return {
            "relation_type": relation_type,
            "source_container_kind": source_kind,
            "source_container_key": source_key,
            "target_container_kind": target_kind,
            "target_container_key": target_key,
        }

    def relations(
        component_edges,
        request_edges,
        data_edges,
        phase_keys,
        criteria,
        milestone,
    ):
        result = [
            relation(
                "component_dependency",
                "architecture_component",
                source,
                "architecture_component",
                target,
            )
            for source, target in component_edges
        ]
        result.extend(
            relation(
                "component_request_flow",
                "architecture_component",
                source,
                "architecture_component",
                target,
            )
            for source, target in request_edges
        )
        result.extend(
            relation(
                "component_data_flow",
                "architecture_component",
                source,
                "architecture_component",
                target,
            )
            for source, target in data_edges
        )
        result.extend(
            relation(
                "phase_dependency",
                "implementation_phase",
                phase_keys[index],
                "implementation_phase",
                phase_keys[index - 1],
            )
            for index in range(1, len(phase_keys))
        )
        result.extend(
            relation(
                "phase_acceptance",
                "implementation_phase",
                phase_keys[-1],
                "acceptance_criterion",
                criterion,
            )
            for criterion in criteria
        )
        result.append(relation(
            "milestone_phase",
            "milestone",
            milestone,
            "implementation_phase",
            phase_keys[-1],
        ))
        return result

    bg = RequirementDimension.BUSINESS_GOAL
    use = RequirementDimension.USE_SCENARIO
    scale = RequirementDimension.USER_SCALE
    deploy = RequirementDimension.DEPLOYMENT_REQUIREMENT
    security = RequirementDimension.DATA_SECURITY_REQUIREMENT
    environment = RequirementDimension.EXISTING_ENVIRONMENT
    integration = RequirementDimension.INTEGRATION_REQUIREMENT
    constraints = RequirementDimension.TECHNICAL_CONSTRAINTS

    if scenario_key == "manufacturing_knowledge":
        proposals = [
            p("proposed_solution", "root", None, "overview", "建议建设受权限约束且可追溯来源的制造知识查询链路。", "knowledge", bg, use, security),
            p("proposed_solution", "capability_group", "retrieval_tradeoff", "items", "当检索规模显著变化时，应重新评估独立向量检索能力。", "deployment", environment, constraints),
            p("architecture", "root", None, "overview", "建议以企业入口、访问策略、资料摄取和检索存储四个边界组织查询流。", "knowledge", bg, security),
            p("architecture", "architecture_component", "factory_entry", "identity", "制造知识查询入口", "integration", use, integration),
            p("architecture", "architecture_component", "access_policy", "identity", "制造资料访问策略服务", "integration", security, constraints),
            p("architecture", "architecture_component", "knowledge_ingestion", "identity", "制造资料摄取服务", "knowledge", use, constraints),
            p("architecture", "architecture_component", "retrieval_store", "identity", "制造知识检索存储", "knowledge", bg, environment),
            p("architecture", "architecture_component", "factory_entry", "responsibilities", "企业入口负责接收研发与售后人员的知识查询。", "integration", use, integration),
            p("architecture", "architecture_component", "access_policy", "responsibilities", "访问策略组件负责在检索前应用文档级权限。", "integration", security, constraints),
            p("architecture", "architecture_component", "knowledge_ingestion", "responsibilities", "资料摄取组件负责将设备手册和工艺资料转换为可检索内容。", "knowledge", use, constraints),
            p("architecture", "architecture_component", "retrieval_store", "responsibilities", "检索存储组件负责保存知识索引并返回带来源的候选内容。", "knowledge", bg, environment),
            p("architecture", "architecture_component", "access_policy", "rationale", "检索前执行权限过滤可避免受限资料进入回答上下文。", "integration", security),
            p("architecture", "architecture_component", "knowledge_ingestion", "rationale", "独立摄取边界便于控制资料更新与重新索引。", "knowledge", use, constraints),
            p("architecture", "architecture_component", "factory_entry", "rationale", "统一知识入口可让不同岗位沿用一致的身份和查询边界。", "integration", use, security),
            p("architecture", "architecture_component", "retrieval_store", "rationale", "集中保存索引与来源标识便于查询结果保持可追溯。", "knowledge", bg, environment),
            p("architecture", "architecture_component", "access_policy", "interfaces", "访问策略组件接收入口身份并向检索存储传递允许的资料范围。", "integration", integration, security),
            p("architecture", "architecture_component", "knowledge_ingestion", "interfaces", "资料摄取组件向检索存储提交文档内容和来源标识。", "knowledge", use, environment),
            p("architecture", "architecture_component", "factory_entry", "interfaces", "知识入口将身份上下文和查询请求传递给访问策略服务。", "integration", use, integration),
            p("architecture", "architecture_component", "retrieval_store", "interfaces", "检索存储接收受限范围查询并返回候选内容与来源标识。", "knowledge", use, security),
            p("deployment_and_integration", "topic_block", "deployment", "items", "建议将应用服务与数据存储分区部署在客户内网。", "deployment", deploy, security, environment),
            p("deployment_and_integration", "topic_block", "integration", "items", "如果 OA 接口允许传递受控身份，则由企业入口复用该身份上下文。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "permission_discovery", "objective", "先确认资料分级和 OA 身份边界。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "permission_discovery", "tasks", "梳理文档类别、访问角色和入口身份字段。", "knowledge", use, security),
            p("implementation_plan", "implementation_phase", "permission_discovery", "deliverables", "交付经确认的资料权限与接口清单。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "knowledge_preparation", "objective", "建立可持续更新的制造资料索引。", "knowledge", bg, use),
            p("implementation_plan", "implementation_phase", "knowledge_preparation", "tasks", "导入代表性设备资料并验证权限标签和来源标识。", "knowledge", use, security),
            p("implementation_plan", "implementation_phase", "knowledge_preparation", "deliverables", "交付可重复执行的资料摄取与索引结果。", "knowledge", environment, constraints),
            p("implementation_plan", "implementation_phase", "controlled_validation", "objective", "验证授权查询、来源追溯和知识更新闭环。", "knowledge", bg, security),
            p("implementation_plan", "implementation_phase", "controlled_validation", "tasks", "使用不同访问角色执行查询与重新索引场景。", "knowledge", use, security),
            p("implementation_plan", "implementation_phase", "controlled_validation", "deliverables", "交付权限、引用和更新场景的验收记录。", "knowledge", bg, security),
            p("risks", "risk", "permission_mapping", "condition", "若文档权限标签与人员角色映射不一致，受限资料可能进入错误的检索范围。", "integration", security),
            p("risks", "risk", "permission_mapping", "impact", "错误检索范围可能造成内部技术资料越权暴露。", "knowledge", security),
            p("risks", "risk", "permission_mapping", "mitigation", "建议在摄取阶段校验资料标签并在查询阶段再次执行权限过滤。", "knowledge", security, constraints),
            p("risks", "risk", "permission_mapping", "trigger", "权限抽样测试发现同一资料对错误角色可见时触发整改。", "integration", security),
            p("acceptance_criteria", "acceptance_criterion", "authorized_retrieval", "criterion", "授权用户能够检索允许范围内的资料并查看来源。", "knowledge", use, security),
            p("acceptance_criteria", "acceptance_criterion", "restricted_retrieval", "criterion", "未授权用户无法检索受限制造资料。", "integration", security),
            p("milestones", "milestone", "knowledge_validation_ready", "outcome", "权限受控的知识查询链路完成验证。", "knowledge", bg, security),
            p("out_of_scope", "scope", "oa_replacement", "scope", "本期不替换客户现有 OA 门户。", "integration", integration),
        ]
        structure_relations = relations(
            (("factory_entry", "access_policy"), ("access_policy", "retrieval_store"), ("knowledge_ingestion", "retrieval_store")),
            (("factory_entry", "access_policy"), ("access_policy", "retrieval_store")),
            (("knowledge_ingestion", "retrieval_store"), ("retrieval_store", "access_policy")),
            ("permission_discovery", "knowledge_preparation", "controlled_validation"),
            ("authorized_retrieval", "restricted_retrieval"),
            "knowledge_validation_ready",
        )
    elif scenario_key == "retail_collaboration":
        proposals = [
            p("proposed_solution", "root", None, "overview", "建议以统一业务入口和适配层组织门店、库存与商品资料协同。", "integration", bg, use, integration),
            p("proposed_solution", "capability_group", "sync_tradeoff", "items", "统一适配的取舍是增加跨系统字段治理工作。", "integration", integration, constraints),
            p("architecture", "root", None, "overview", "建议由企业入口、身份边界、协同编排和业务适配四个组件形成查询路径。", "integration", bg, integration),
            p("architecture", "architecture_component", "retail_portal", "identity", "门店与运营协同入口", "integration", use, integration),
            p("architecture", "architecture_component", "retail_identity", "identity", "零售身份与权限映射服务", "integration", security, integration),
            p("architecture", "architecture_component", "collaboration_orchestrator", "identity", "零售业务协同编排服务", "integration", bg, use),
            p("architecture", "architecture_component", "business_adapters", "identity", "多系统业务适配服务", "integration", integration, constraints),
            p("architecture", "architecture_component", "retail_portal", "responsibilities", "企业入口负责承接门店与运营人员的业务查询。", "integration", use, integration),
            p("architecture", "architecture_component", "retail_identity", "responsibilities", "身份边界负责将统一身份映射为可访问的业务范围。", "integration", security, integration),
            p("architecture", "architecture_component", "collaboration_orchestrator", "responsibilities", "协同编排组件负责路由商品、库存和流程查询。", "integration", bg, use),
            p("architecture", "architecture_component", "business_adapters", "responsibilities", "业务适配组件负责隔离不同系统的字段与接口差异。", "integration", integration, constraints),
            p("architecture", "architecture_component", "retail_identity", "rationale", "集中身份映射可避免各业务适配器分别解释权限。", "integration", security),
            p("architecture", "architecture_component", "business_adapters", "rationale", "独立适配边界可限制单个系统接口变化的影响范围。", "integration", integration, constraints),
            p("architecture", "architecture_component", "retail_portal", "rationale", "统一协同入口可减少门店与运营人员在多个源系统之间切换。", "integration", use, bg),
            p("architecture", "architecture_component", "collaboration_orchestrator", "rationale", "集中编排业务查询可使业务流程不直接依赖各源系统接口。", "integration", bg, constraints),
            p("architecture", "architecture_component", "retail_identity", "interfaces", "身份边界向协同编排组件提供用户与门店访问范围。", "integration", security, integration),
            p("architecture", "architecture_component", "business_adapters", "interfaces", "业务适配组件通过受控接口返回标准化业务数据投影。", "integration", integration, use),
            p("architecture", "architecture_component", "retail_portal", "interfaces", "协同入口将用户身份和业务查询提交给身份权限映射服务。", "integration", use, security),
            p("architecture", "architecture_component", "collaboration_orchestrator", "interfaces", "协同编排服务接收授权范围并调用业务适配服务取得标准化数据。", "integration", integration, use),
            p("deployment_and_integration", "topic_block", "deployment", "items", "建议将应用服务与业务数据投影分区部署在企业受控网络内。", "deployment", deploy, security),
            p("deployment_and_integration", "topic_block", "integration", "items", "如果目标系统缺少稳定接口，则以受控批量交换作为条件性接入路径。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "interface_inventory", "objective", "先确认各业务系统的数据责任与接口边界。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "interface_inventory", "tasks", "核对商品、库存和门店字段以及权限来源。", "integration", use, security),
            p("implementation_plan", "implementation_phase", "interface_inventory", "deliverables", "交付业务字段映射与接口责任清单。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "adapter_delivery", "objective", "建立隔离系统差异的业务适配链路。", "integration", bg, integration),
            p("implementation_plan", "implementation_phase", "adapter_delivery", "tasks", "实现身份映射、数据转换和异常隔离。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "adapter_delivery", "deliverables", "交付可验证的标准业务数据投影。", "integration", use, integration),
            p("implementation_plan", "implementation_phase", "business_validation", "objective", "验证跨系统查询与数据同步边界。", "integration", bg, use),
            p("implementation_plan", "implementation_phase", "business_validation", "tasks", "执行字段一致性、权限和接口异常场景。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "business_validation", "deliverables", "交付跨系统协同验收记录。", "integration", bg, integration),
            p("risks", "risk", "field_inconsistency", "condition", "若业务系统对同一商品或门店字段定义不一致，统一查询可能产生歧义。", "integration", integration, constraints),
            p("risks", "risk", "field_inconsistency", "impact", "字段歧义可能导致运营人员看到不一致的业务数据。", "integration", use, integration),
            p("risks", "risk", "field_inconsistency", "mitigation", "建议建立字段映射规则并保留来源系统标识。", "integration", integration, constraints),
            p("risks", "risk", "field_inconsistency", "trigger", "跨系统对账发现同一业务对象结果不一致时触发治理。", "integration", integration),
            p("acceptance_criteria", "acceptance_criterion", "cross_system_query", "criterion", "运营用户能够从统一入口查询商品与库存数据并识别来源系统。", "integration", use, integration),
            p("acceptance_criteria", "acceptance_criterion", "permission_projection", "criterion", "验证不同门店角色只能查看其被授权的业务范围。", "integration", security),
            p("milestones", "milestone", "collaboration_validated", "outcome", "跨系统业务协同链路完成验证。", "integration", bg, integration),
            p("out_of_scope", "scope", "source_system_replacement", "scope", "本期不替换门店、库存或商品源系统。", "integration", integration),
        ]
        structure_relations = relations(
            (("retail_portal", "retail_identity"), ("retail_identity", "collaboration_orchestrator"), ("collaboration_orchestrator", "business_adapters")),
            (("retail_portal", "retail_identity"), ("retail_identity", "collaboration_orchestrator"), ("collaboration_orchestrator", "business_adapters")),
            (("business_adapters", "collaboration_orchestrator"),),
            ("interface_inventory", "adapter_delivery", "business_validation"),
            ("cross_system_query", "permission_projection"),
            "collaboration_validated",
        )
    elif scenario_key == "enterprise_service_approved":
        proposals = [
            p("proposed_solution", "root", None, "overview", "建议建设受身份权限约束的知识与合同草案辅助链路。", "knowledge", bg, use, security),
            p("proposed_solution", "capability_group", "template_tradeoff", "items", "采用已审核模板的取舍是限制自由生成范围。", "knowledge", use, constraints),
            p("architecture", "root", None, "overview", "建议由企业入口、身份权限、知识与草案应用、检索存储四个边界组成请求流。", "knowledge", bg, integration),
            p("architecture", "architecture_component", "consultant_entry", "identity", "企业顾问知识入口", "integration", use, integration),
            p("architecture", "architecture_component", "identity_access", "identity", "项目身份与权限服务", "integration", security, integration),
            p("architecture", "architecture_component", "knowledge_contract_app", "identity", "知识与合同草案协作服务", "knowledge", bg, use),
            p("architecture", "architecture_component", "retrieval_storage", "identity", "PostgreSQL/pgvector 知识存储", "knowledge", environment, constraints),
            p("architecture", "architecture_component", "consultant_entry", "responsibilities", "企业入口负责接收顾问的案例查询与合同草案请求。", "integration", use, integration),
            p("architecture", "architecture_component", "identity_access", "responsibilities", "身份权限组件负责在检索前限定顾问可访问的项目资料。", "integration", security, integration),
            p("architecture", "architecture_component", "knowledge_contract_app", "responsibilities", "知识与草案应用负责基于已审核模板形成待人工复核的合同草案。", "knowledge", bg, use),
            p("architecture", "architecture_component", "retrieval_storage", "responsibilities", "检索存储组件负责保存知识索引并返回可引用的项目资料。", "knowledge", environment, constraints),
            p("architecture", "architecture_component", "identity_access", "rationale", "检索前过滤可防止跨项目资料进入生成上下文。", "integration", security),
            p("architecture", "architecture_component", "knowledge_contract_app", "rationale", "已审核模板能够约束草案结构并保留人工审核责任。", "knowledge", use, constraints),
            p("architecture", "architecture_component", "consultant_entry", "rationale", "统一顾问入口可在同一访问边界内承接案例查询与草案协作。", "integration", use, security),
            p("architecture", "architecture_component", "retrieval_storage", "rationale", "复用 PostgreSQL 与 pgvector 可减少新增数据基础设施并保持知识来源集中管理。", "knowledge", environment, constraints),
            p("architecture", "architecture_component", "identity_access", "interfaces", "身份权限组件接收 SSO 身份并向应用传递项目访问范围。", "integration", integration, security),
            p("architecture", "architecture_component", "knowledge_contract_app", "interfaces", "应用通过检索接口取得带来源内容，并通过 OA 交付待审核草案。", "integration", integration, use),
            p("architecture", "architecture_component", "consultant_entry", "interfaces", "顾问入口将 SSO 上下文和知识或草案请求提交给身份权限服务。", "integration", use, integration),
            p("architecture", "architecture_component", "retrieval_storage", "interfaces", "检索存储接收受权限约束的检索请求并返回带来源的项目资料。", "knowledge", use, security),
            p("deployment_and_integration", "topic_block", "deployment", "items", "建议将应用服务与 PostgreSQL 数据存储分区部署在客户受控网络内。", "deployment", deploy, security, environment),
            p("deployment_and_integration", "topic_block", "integration", "items", "如果模型能力需要访问外部服务，则必须在数据不出公网约束下先确认可用边界。", "deployment", security, integration),
            p("implementation_plan", "implementation_phase", "boundary_confirmation", "objective", "先确认 SSO、OA、项目权限和审核模板边界。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "boundary_confirmation", "tasks", "梳理身份字段、项目权限、模板版本和草案审核责任。", "knowledge", use, integration),
            p("implementation_plan", "implementation_phase", "boundary_confirmation", "deliverables", "交付经确认的接口、权限与模板清单。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "knowledge_delivery", "objective", "建立项目知识检索与受控草案生成链路。", "knowledge", bg, use),
            p("implementation_plan", "implementation_phase", "knowledge_delivery", "tasks", "导入审核资料并实现权限过滤、来源引用和模板约束。", "knowledge", use, security),
            p("implementation_plan", "implementation_phase", "knowledge_delivery", "deliverables", "交付可供顾问验证的知识与草案应用。", "knowledge", bg, use),
            p("implementation_plan", "implementation_phase", "controlled_uat", "objective", "验证检索权限、引用来源和人工审核闭环。", "knowledge", bg, security),
            p("implementation_plan", "implementation_phase", "controlled_uat", "tasks", "执行跨项目权限、引用定位和草案审批场景。", "integration", use, security),
            p("implementation_plan", "implementation_phase", "controlled_uat", "deliverables", "交付受控用户验收记录和上线准备结论。", "deployment", deploy, integration),
            p("risks", "risk", "template_boundary", "condition", "若模板版本和适用范围未受控，草案可能使用错误的合同结构。", "knowledge", use, constraints),
            p("risks", "risk", "template_boundary", "impact", "错误模板可能增加顾问复核工作并影响交付一致性。", "knowledge", bg, use),
            p("risks", "risk", "template_boundary", "mitigation", "建议仅允许已审核模板进入草案生成，并保留模板版本来源。", "knowledge", use, constraints),
            p("risks", "risk", "template_boundary", "trigger", "发现草案引用未审核或不适用模板时停止交付。", "knowledge", use, constraints),
            p("acceptance_criteria", "acceptance_criterion", "project_isolation", "criterion", "无项目权限的顾问无法检索受限项目资料。", "integration", security),
            p("acceptance_criteria", "acceptance_criterion", "cited_draft", "criterion", "顾问能够查看草案依据的审核模板和知识来源。", "knowledge", use, constraints),
            p("milestones", "milestone", "controlled_uat_passed", "outcome", "知识检索与合同草案人工审核链路完成用户验收。", "knowledge", bg, use),
            p("out_of_scope", "scope", "final_contract_approval", "scope", "本期不由 AI 自动批准或签署最终合同。", "knowledge", use, constraints),
        ]
        structure_relations = relations(
            (("consultant_entry", "identity_access"), ("knowledge_contract_app", "identity_access"), ("knowledge_contract_app", "retrieval_storage")),
            (("consultant_entry", "identity_access"), ("identity_access", "knowledge_contract_app"), ("knowledge_contract_app", "retrieval_storage")),
            (("retrieval_storage", "knowledge_contract_app"),),
            ("boundary_confirmation", "knowledge_delivery", "controlled_uat"),
            ("project_isolation", "cited_draft"),
            "controlled_uat_passed",
        )
    elif scenario_key == "manufacturing_identity":
        proposals = [
            p("proposed_solution", "root", None, "overview", "建议先形成不依赖具体身份协议的统一知识入口边界。", "integration", bg, use, integration),
            p("proposed_solution", "capability_group", "identity_tradeoff", "items", "在协议确认前推迟身份适配实现的取舍是保留后续接口调整空间。", "integration", integration, constraints),
            p("architecture", "root", None, "overview", "建议由 OA 入口、条件身份适配、知识应用和内网存储四个边界组成。", "integration", bg, integration),
            p("architecture", "architecture_component", "oa_entry", "identity", "多工厂 OA 知识入口", "integration", use, integration),
            p("architecture", "architecture_component", "conditional_identity", "identity", "条件式身份适配服务", "integration", integration, security),
            p("architecture", "architecture_component", "factory_knowledge_app", "identity", "多工厂知识应用服务", "knowledge", bg, use),
            p("architecture", "architecture_component", "identity_store", "identity", "内网知识与权限存储", "deployment", security, environment),
            p("architecture", "architecture_component", "oa_entry", "responsibilities", "OA 入口负责承接多工厂员工的统一访问请求。", "integration", use, integration),
            p("architecture", "architecture_component", "conditional_identity", "responsibilities", "条件身份适配组件负责在协议确认后转换身份和角色信息。", "integration", integration, security),
            p("architecture", "architecture_component", "factory_knowledge_app", "responsibilities", "知识应用负责在授权范围内响应员工查询。", "knowledge", bg, use, security),
            p("architecture", "architecture_component", "identity_store", "responsibilities", "内网存储负责保存知识索引和访问映射。", "deployment", security, environment),
            p("architecture", "architecture_component", "conditional_identity", "rationale", "隔离身份适配可避免未确认协议影响知识应用核心逻辑。", "integration", integration, constraints),
            p("architecture", "architecture_component", "factory_knowledge_app", "rationale", "统一应用边界可在协议确认前先验证知识查询能力。", "knowledge", bg, use),
            p("architecture", "architecture_component", "oa_entry", "rationale", "保留 OA 入口可在身份协议确认前维持用户访问路径稳定。", "integration", use, constraints),
            p("architecture", "architecture_component", "identity_store", "rationale", "知识索引与权限映射保留在内网可避免未确认身份信息越过数据边界。", "deployment", security, constraints),
            p("architecture", "architecture_component", "conditional_identity", "interfaces", "如果客户 IdP 支持 OIDC，则优先通过标准 OIDC 登录链路接入。", "integration", integration, security),
            p("architecture", "architecture_component", "factory_knowledge_app", "interfaces", "知识应用接收经适配的身份范围并调用内网知识存储。", "knowledge", use, security),
            p("architecture", "architecture_component", "oa_entry", "interfaces", "OA 入口将当前登录上下文传递给条件式身份适配服务。", "integration", use, integration),
            p("architecture", "architecture_component", "identity_store", "interfaces", "内网存储向知识应用返回授权范围内的知识内容与权限映射。", "deployment", security, environment),
            p("deployment_and_integration", "topic_block", "deployment", "items", "建议将应用服务与身份映射数据分区部署在客户内网。", "deployment", deploy, security),
            p("deployment_and_integration", "topic_block", "integration", "items", "如果客户身份平台仅支持其他标准协议，则在接口确认后选择对应适配器。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "protocol_discovery", "objective", "先确认身份协议、字段和角色映射。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "protocol_discovery", "tasks", "获取身份接口资料并执行兼容性验证。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "protocol_discovery", "deliverables", "交付已确认的身份协议与字段映射清单。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "knowledge_skeleton", "objective", "建立与具体身份协议解耦的知识入口骨架。", "knowledge", bg, use),
            p("implementation_plan", "implementation_phase", "knowledge_skeleton", "tasks", "实现授权上下文接口和内网知识查询链路。", "knowledge", use, security),
            p("implementation_plan", "implementation_phase", "knowledge_skeleton", "deliverables", "交付可注入模拟身份范围的知识入口。", "knowledge", bg, integration),
            p("implementation_plan", "implementation_phase", "identity_validation", "objective", "在协议确认后验证端到端统一登录。", "integration", integration, security),
            p("implementation_plan", "implementation_phase", "identity_validation", "tasks", "执行登录、角色映射和越权访问场景。", "integration", use, security),
            p("implementation_plan", "implementation_phase", "identity_validation", "deliverables", "交付身份集成与权限验证记录。", "integration", integration, security),
            p("risks", "risk", "protocol_mismatch", "condition", "若客户身份协议与现有统一身份能力不兼容，适配路径需要调整。", "integration", integration, constraints),
            p("risks", "risk", "protocol_mismatch", "impact", "身份适配调整可能改变后续联调顺序。", "integration", integration),
            p("risks", "risk", "protocol_mismatch", "mitigation", "建议在核心集成前完成协议与字段兼容性验证。", "integration", integration, security),
            p("risks", "risk", "protocol_mismatch", "trigger", "接口确认阶段发现协议或必要字段不兼容时触发调整。", "integration", integration, constraints),
            p("acceptance_criteria", "acceptance_criterion", "identity_login", "criterion", "协议确认后，目标身份系统能够完成端到端登录验证。", "integration", integration),
            p("acceptance_criteria", "acceptance_criterion", "role_access", "criterion", "不同角色登录后只能访问其授权知识范围。", "integration", security),
            p("milestones", "milestone", "identity_boundary_validated", "outcome", "身份协议确认并完成权限链路验证。", "integration", integration, security),
            p("out_of_scope", "scope", "identity_provider_replacement", "scope", "本期不替换客户现有统一身份平台。", "integration", integration),
        ]
        structure_relations = relations(
            (("oa_entry", "conditional_identity"), ("factory_knowledge_app", "conditional_identity"), ("factory_knowledge_app", "identity_store")),
            (("oa_entry", "conditional_identity"), ("conditional_identity", "factory_knowledge_app"), ("factory_knowledge_app", "identity_store")),
            (("identity_store", "factory_knowledge_app"),),
            ("protocol_discovery", "knowledge_skeleton", "identity_validation"),
            ("identity_login", "role_access"),
            "identity_boundary_validated",
        )
    elif scenario_key == "ecommerce_ha_revision":
        proposals = [
            p("proposed_solution", "root", None, "overview", "建议以无状态服务、依赖隔离和数据一致性边界改造高峰期知识查询链路。", "deployment", bg, use, constraints),
            p("proposed_solution", "capability_group", "availability_tradeoff", "items", "增强故障隔离的取舍是增加运行观测和恢复演练复杂度。", "deployment", deploy, constraints),
            p("architecture", "root", None, "overview", "建议由请求入口、无状态服务、依赖隔离和数据一致性四个组件形成可恢复请求流。", "deployment", bg, constraints),
            p("architecture", "architecture_component", "commerce_entry", "identity", "电商客服与运营入口", "integration", use, integration),
            p("architecture", "architecture_component", "stateless_service", "identity", "无状态知识查询服务", "deployment", scale, constraints),
            p("architecture", "architecture_component", "dependency_guard", "identity", "外部依赖隔离服务", "integration", integration, constraints),
            p("architecture", "architecture_component", "consistency_store", "identity", "PostgreSQL 业务与索引存储", "deployment", environment, constraints),
            p("architecture", "architecture_component", "commerce_entry", "responsibilities", "请求入口负责认证并路由客服与运营查询。", "integration", use, integration),
            p("architecture", "architecture_component", "stateless_service", "responsibilities", "无状态应用服务负责处理可水平扩展的知识查询。", "deployment", scale, constraints),
            p("architecture", "architecture_component", "dependency_guard", "responsibilities", "依赖隔离组件负责限制外部系统异常在查询链路中的传播。", "integration", integration, constraints),
            p("architecture", "architecture_component", "consistency_store", "responsibilities", "数据一致性组件负责在 PostgreSQL 中维护可恢复的业务与索引状态。", "deployment", environment, constraints),
            p("architecture", "architecture_component", "stateless_service", "rationale", "无状态处理可让应用实例扩展不依赖本地会话。", "deployment", scale, constraints),
            p("architecture", "architecture_component", "dependency_guard", "rationale", "隔离外部依赖可避免单个接口异常直接扩散到全部查询。", "integration", integration, constraints),
            p("architecture", "architecture_component", "commerce_entry", "rationale", "统一入口可向下游服务提供稳定的认证和查询请求边界。", "integration", use, security),
            p("architecture", "architecture_component", "consistency_store", "rationale", "共享持久化状态可支持应用实例替换后的业务与索引恢复。", "deployment", environment, constraints),
            p("architecture", "architecture_component", "stateless_service", "interfaces", "应用服务通过受控接口读取一致性存储并返回来源信息。", "knowledge", use, environment),
            p("architecture", "architecture_component", "dependency_guard", "interfaces", "依赖隔离组件包装 OA 与外部业务接口并返回可处理的失败结果。", "integration", integration, constraints),
            p("architecture", "architecture_component", "commerce_entry", "interfaces", "请求入口将认证上下文和查询请求转交给无状态知识查询服务。", "integration", use, security),
            p("architecture", "architecture_component", "consistency_store", "interfaces", "PostgreSQL 存储向无状态服务提供可恢复的业务与索引状态。", "deployment", environment, constraints),
            p("deployment_and_integration", "topic_block", "deployment", "items", "建议将应用服务与 PostgreSQL 数据存储分区部署在企业受控网络内。", "deployment", deploy, security, environment),
            p("deployment_and_integration", "topic_block", "integration", "items", "如果外部业务接口在高峰期异常，则由依赖隔离边界返回可处理的失败结果。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "failure_inventory", "objective", "先确认关键依赖与故障传播边界。", "integration", integration, constraints),
            p("implementation_plan", "implementation_phase", "failure_inventory", "tasks", "梳理入口、业务接口和数据库异常场景。", "integration", integration, environment),
            p("implementation_plan", "implementation_phase", "failure_inventory", "deliverables", "交付故障场景与恢复责任清单。", "deployment", constraints, integration),
            p("implementation_plan", "implementation_phase", "availability_delivery", "objective", "实现无状态服务、依赖隔离和一致性处理。", "deployment", bg, constraints),
            p("implementation_plan", "implementation_phase", "availability_delivery", "tasks", "实现可重试边界、失败降级和状态恢复路径。", "deployment", integration, constraints),
            p("implementation_plan", "implementation_phase", "availability_delivery", "deliverables", "交付可执行故障测试的高可用候选方案。", "deployment", bg, deploy),
            p("implementation_plan", "implementation_phase", "resilience_validation", "objective", "通过预设故障与恢复场景验证方案。", "deployment", bg, constraints),
            p("implementation_plan", "implementation_phase", "resilience_validation", "tasks", "执行依赖异常、应用恢复和数据一致性测试。", "deployment", integration, environment),
            p("implementation_plan", "implementation_phase", "resilience_validation", "deliverables", "交付故障演练与数据一致性验收记录。", "deployment", constraints, environment),
            p("risks", "risk", "dependency_cascade", "condition", "若外部业务接口异常未被隔离，失败可能沿查询链路传播。", "integration", integration, constraints),
            p("risks", "risk", "dependency_cascade", "impact", "故障传播可能导致客服与运营查询不可用。", "integration", use, bg),
            p("risks", "risk", "dependency_cascade", "mitigation", "建议为外部依赖设置可观测的失败边界和受控恢复路径。", "deployment", integration, constraints),
            p("risks", "risk", "dependency_cascade", "trigger", "故障演练发现单个依赖异常造成未处理错误传播时触发整改。", "deployment", integration, constraints),
            p("acceptance_criteria", "acceptance_criterion", "failure_isolation", "criterion", "验证单个外部依赖异常不会造成未处理错误传播到全部查询。", "integration", integration, constraints),
            p("acceptance_criteria", "acceptance_criterion", "recovery_consistency", "criterion", "预设恢复场景完成后能够验证业务与索引状态一致。", "deployment", environment, constraints),
            p("milestones", "milestone", "resilience_validated", "outcome", "故障隔离、恢复和一致性场景完成验证。", "deployment", bg, constraints),
            p("out_of_scope", "scope", "unsupported_sla", "scope", "本期不承诺未经客户确认的可用性数字。", "deployment", constraints),
        ]
        structure_relations = relations(
            (("commerce_entry", "stateless_service"), ("stateless_service", "dependency_guard"), ("stateless_service", "consistency_store")),
            (("commerce_entry", "stateless_service"), ("stateless_service", "dependency_guard")),
            (("consistency_store", "stateless_service"),),
            ("failure_inventory", "availability_delivery", "resilience_validation"),
            ("failure_isolation", "recovery_consistency"),
            "resilience_validated",
        )
    else:
        raise ValueError("Unknown SalesMind demo scenario.")

    return {
        "proposals": proposals,
        "structure_relations": structure_relations,
    }


class DemoSolutionProposalProvider(LLMProvider):
    def __init__(self, scenario: DemoScenario):
        self.scenario = scenario

    @property
    def provider_name(self) -> str:
        return "salesmind_demo_offline"

    @property
    def model_name(self) -> str:
        return f"solution-{self.scenario.key}-v2"

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        del max_output_tokens
        source_labels = _source_labels(messages)
        payload = _demo_solution_payload(self.scenario.key, source_labels)
        system_prompt = messages[0]["content"] if messages else ""
        if "Pass 1 — Technical Core" in system_prompt:
            allowed_sections = {
                "proposed_solution", "architecture", "deployment_and_integration",
            }
            allowed_relations = {
                "component_dependency", "component_request_flow",
                "component_data_flow",
            }
        elif "Pass 2 — Implementation Planning" in system_prompt:
            allowed_sections = {
                "implementation_plan", "milestones",
            }
            allowed_relations = {
                "phase_dependency", "milestone_phase",
            }
        elif "Pass 3 — Assurance & Boundaries" in system_prompt:
            allowed_sections = {
                "risks", "acceptance_criteria", "out_of_scope",
            }
            allowed_relations = {
                "phase_acceptance",
            }
        else:
            allowed_sections = None
            allowed_relations = None
        if allowed_sections is not None:
            payload = {
                "proposals": [
                    item for item in payload["proposals"]
                    if item["placement"]["section"] in allowed_sections
                ],
                "structure_relations": [
                    item for item in payload["structure_relations"]
                    if item["relation_type"] in allowed_relations
                ],
            }
        return LLMGeneration(json.dumps(payload, ensure_ascii=False))


class DemoVerifierProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "salesmind_demo_offline"

    @property
    def model_name(self) -> str:
        return "proposal-verifier-v1"

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        del max_output_tokens
        if any("<proposal_admissibility_packets>" in item["content"] for item in messages):
            payload = _tagged_json(messages, "proposal_admissibility_packets")
            results = [
                {
                    "location": item["location"],
                    "decision": "ADMISSIBLE",
                    "atomicity": "ATOMIC",
                }
                for item in payload["proposals"]
            ]
            return LLMGeneration(json.dumps({"results": results}, ensure_ascii=False))
        payload = _tagged_json(messages, "grounding_claim_packets")
        results = [
            {
                "location": item["location"],
                "relation": "SUPPORTED",
                "atomicity": "ATOMIC",
            }
            for item in payload["claims"]
        ]
        return LLMGeneration(json.dumps({"results": results}, ensure_ascii=False))


def _tagged_json(messages: Sequence[LLMMessage], tag: str) -> dict:
    content = next(
        (message["content"] for message in messages if f"<{tag}>" in message["content"]),
        None,
    )
    if content is None:
        raise ValueError(f"Demo provider did not receive {tag} input.")
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", content, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"Demo provider received malformed {tag} input.")
    return json.loads(html.unescape(match.group(1)))


def _source_labels(messages: Sequence[LLMMessage]) -> dict[str, str]:
    content = next(
        message["content"]
        for message in messages
        if "<allowed_enterprise_capabilities>" in message["content"]
    )
    result = {}
    for match in re.finditer(
        r'<source id="(S[1-9][0-9]*)">\s*文档：([^\n]+)',
        content,
    ):
        label, title = match.groups()
        if "知识平台能力" in title:
            result["knowledge"] = label
        elif "集成与权限能力" in title:
            result["integration"] = label
        elif "私有化与高可用" in title:
            result["deployment"] = label
    if set(result) != {"knowledge", "integration", "deployment"}:
        raise ValueError("Demo solution provider did not receive all approved sources.")
    return result
