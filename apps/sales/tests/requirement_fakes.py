"""Controlled, offline analysis responses for persistence and execution tests."""

import json
from xml.etree import ElementTree

from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM


def valid_analysis_payload():
    requirements = {
        name: {"status": "unknown", "value": None, "evidence": None}
        for name in (
            "business_goal", "use_scenario", "user_scale", "deployment_requirement",
            "data_security_requirement", "existing_environment", "integration_requirement",
            "timeline", "budget", "technical_constraints",
        )
    }
    requirements["budget"] = {
        "status": "conflict", "value": None,
        "evidence": "系统预算50万元，销售最新录入预算最多30万元。",
    }
    return {
        "summary": "客户计划建设企业系统，预算有待确认。",
        "requirements": requirements,
        "conflicts": [{"fields": ["budget"], "description": "50万元与30万元预算冲突。"}],
        "clarifying_questions": [{"field": "budget", "question": "请确认当前有效预算上限？"}],
    }


class AnalysisFakeLLM(DeterministicFakeLLM):
    provider_name = "analysis-test-provider"
    model_name = "analysis-test-model"

    def __init__(self, *, callback=None, content=None):
        super().__init__()
        self.callback = callback
        self.content = content if content is not None else json.dumps(valid_analysis_payload(), ensure_ascii=False)

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        if self.callback is not None:
            self.callback()
        return LLMGeneration(content=self.content)


def input_from_messages(messages):
    """Decode the actual provider input, not production snapshot helpers."""

    root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
    facts = json.loads(root.find("structured_business_facts").text)
    narratives = json.loads(root.find("untrusted_business_text").text)
    facts["customer"]["basic_info"] = narratives["basic_info"]
    return facts, narratives["raw_requirement"]
