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
        return LLMGeneration(json.dumps(payload, ensure_ascii=False))


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
        knowledge = source_labels["knowledge"]
        integration = source_labels["integration"]
        deployment = source_labels["deployment"]

        def proposal(section, kind, key, field, text, source):
            return {
                "placement": {
                    "section": section,
                    "container_kind": kind,
                    "container_key": key,
                    "field": field,
                },
                "text": text,
                "citations": [source],
            }

        focus = self.scenario.solution_focus
        proposals = [
            proposal("proposed_solution", "root", None, "overview", f"建议以{focus}作为本期总体交付方向。", knowledge),
            proposal("proposed_solution", "capability_group", "capability_1", "items", "建议统一提供经过权限控制的知识查询入口。", knowledge),
            proposal("architecture", "root", None, "overview", "建议采用应用服务、知识检索服务和数据服务分层组织。", deployment),
            proposal("architecture", "architecture_component", "component_1", "responsibilities", "建议知识检索组件负责返回带来源的内部知识结果。", knowledge),
            proposal("architecture", "architecture_component", "component_1", "rationale", "建议通过来源引用支持业务人员复核查询结论。", knowledge),
            proposal("architecture", "architecture_component", "component_1", "interfaces", "建议知识检索组件通过受控接口与企业入口集成。", integration),
            proposal("deployment_and_integration", "topic_block", "deployment", "items", "建议应用与数据服务部署在客户受控网络中。", deployment),
            proposal("deployment_and_integration", "topic_block", "integration", "items", "建议通过标准接口连接现有 OA 与统一身份入口。", integration),
            proposal("implementation_plan", "implementation_phase", "phase_1", "objective", "建议第一阶段完成资料范围与接入边界确认。", integration),
            proposal("implementation_plan", "implementation_phase", "phase_1", "tasks", "建议梳理知识来源、用户范围和现有系统接口。", knowledge),
            proposal("implementation_plan", "implementation_phase", "phase_1", "deliverables", "建议交付经双方确认的资料与接口清单。", integration),
            proposal("implementation_plan", "implementation_phase", "phase_2", "objective", "建议第二阶段完成受控环境中的方案验证。", deployment),
            proposal("implementation_plan", "implementation_phase", "phase_2", "tasks", "建议验证知识查询、身份接入和来源追溯链路。", integration),
            proposal("implementation_plan", "implementation_phase", "phase_2", "deliverables", "建议交付可供业务验收的验证结果记录。", knowledge),
            proposal("risks", "risk", "risk_1", "condition", "若企业身份协议与字段映射未确认，统一登录接入存在返工风险。", integration),
            proposal("risks", "risk", "risk_1", "impact", "身份接入返工可能影响联调顺序。", integration),
            proposal("risks", "risk", "risk_1", "mitigation", "建议在接口实现前确认身份协议和字段映射。", integration),
            proposal("risks", "risk", "risk_1", "trigger", "当客户身份接口资料仍未交付时触发该风险。", integration),
            proposal("risks", "risk", "risk_2", "condition", "若知识资料未完成权限分级，查询结果存在越权暴露风险。", knowledge),
            proposal("risks", "risk", "risk_2", "impact", "越权查询可能造成内部资料访问范围扩大。", knowledge),
            proposal("risks", "risk", "risk_2", "mitigation", "建议在导入前完成资料分类和访问角色映射。", knowledge),
            proposal("risks", "risk", "risk_2", "trigger", "当资料缺少可执行的访问范围标记时触发该风险。", knowledge),
            proposal("acceptance_criteria", "acceptance_criterion", "criterion_1", "criterion", "建议验收时确认授权用户能够查询知识并查看对应来源。", knowledge),
            proposal("acceptance_criteria", "acceptance_criterion", "criterion_2", "criterion", "建议验收时确认未授权用户无法访问受限资料。", integration),
            proposal("milestones", "milestone", "milestone_1", "outcome", "建议以完成资料和接口清单确认为首个里程碑结果。", integration),
            proposal("milestones", "milestone", "milestone_2", "outcome", "建议以完成受控环境验证记录为第二个里程碑结果。", deployment),
            proposal("out_of_scope", "scope", "scope_1", "scope", "建议本期范围不包含替换客户现有 OA 系统。", integration),
            proposal("out_of_scope", "scope", "scope_2", "scope", "建议本期范围不包含未经确认的公网数据传输。", deployment),
        ]
        return LLMGeneration(json.dumps({"proposals": proposals}, ensure_ascii=False))


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
