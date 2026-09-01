"""Small deterministic solution fixtures, used only by offline tests."""

import json
from xml.etree import ElementTree

from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.sales.services.requirement_analysis import _parse_analysis
from apps.sales.tests.requirement_fakes import AnalysisFakeLLM


VALUES = {
    "business_goal": "企业知识查询",
    "use_scenario": "员工查阅企业资料",
    "user_scale": "约300人",
    "deployment_requirement": "私有化部署",
    "data_security_requirement": "业务数据不出公网",
    "existing_environment": "Linux服务器",
    "integration_requirement": "OA对接",
    "timeline": "2026年12月上线",
    "budget": "50万元",
    "technical_constraints": "使用PostgreSQL",
}


def analysis_payload(**statuses):
    requirements = {}
    conflicts = []
    for name, value in VALUES.items():
        status = statuses.get(name, "known")
        requirements[name] = {
            "status": status,
            "value": value if status in {"known", "unclear"} else None,
            "evidence": None if status == "unknown" else "受控输入证据（不要用于检索全文）",
        }
        if status == "conflict":
            conflicts.append({"fields": [name], "description": "该维度存在冲突，待确认。"})
    return {"summary": "客户计划建设企业系统。", "requirements": requirements,
            "conflicts": conflicts, "clarifying_questions": []}


def typed_analysis(**statuses):
    return _parse_analysis(json.dumps(analysis_payload(**statuses), ensure_ascii=False))


def analysis_record(**statuses):
    """Hydrated model record without database I/O, for pure service unit tests."""
    from apps.sales.models import OpportunityRequirementAnalysis

    values = {
        "id": 17, "opportunity_id": 12, "created_by_id": 9,
        **analysis_payload(**statuses), "source_context": {"private": "BASIC_INFO_DO_NOT_DUMP"},
        "source_raw_requirement": "RAW_REQUIREMENT_DO_NOT_DUMP", "analysis_version": "v1",
    }
    return OpportunityRequirementAnalysis.from_db("default", list(values), list(values.values()))


def solution_payload():
    return {
        "title": "企业知识服务内部草稿",
        "executive_summary": [{"type": "customer_fact", "text": "客户希望进行企业知识查询。", "citations": []}],
        "solution_sections": [
            {"key": key, "title": title, "statements": [
                {"type": "enterprise_fact", "text": "企业资料确认支持私有化部署。", "citations": ["S1"]},
            ]}
            for key, title in (
                ("overall_approach", "总体方案"), ("deployment", "部署方案"),
                ("data_security", "数据安全"), ("integration", "系统集成"),
                ("implementation", "实施建议"),
            )
        ],
        "assumptions": [],
    }


class SolutionFakeLLM(AnalysisFakeLLM):
    def __init__(self, *, content=None, callback=None, grounding_content=None):
        super().__init__(content=content if content is not None else json.dumps(
            solution_payload(), ensure_ascii=False,
        ), callback=callback)
        self.grounding_content = grounding_content

    def generate(self, messages, *, max_output_tokens=None):
        if len(messages) > 1 and "<grounding_claim_packets>" in messages[1]["content"]:
            DeterministicFakeLLM.generate(self, messages, max_output_tokens=max_output_tokens)
            content = self.grounding_content
            if content is None:
                root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
                payload = json.loads(root.find("grounding_claim_packets").text)
                content = json.dumps({"results": [
                    {"location": item["location"], "relation": "SUPPORTED", "type_fit": "VALID"}
                    for item in payload["claims"]
                ]})
            return LLMGeneration(content=content)
        return super().generate(messages, max_output_tokens=max_output_tokens)
