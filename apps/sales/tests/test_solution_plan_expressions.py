"""Closed planning grammar recognizes intent without granting admission."""

import pytest

from apps.sales.services import solution_clarification_actions as actions


def parse(text):
    from apps.sales.services.solution_plan_expressions import parse_plan_expression
    return parse_plan_expression(text)


@pytest.mark.parametrize("text,kinds,prerequisites", [
    ("核验现有SalesMind AI环境的部署条件、网络访问边界与服务器容量是否满足本期部署需求。", ["inquiry"], ["none"]),
    ("核验本期部署条件与现有SalesMind AI环境的可用服务器容量。", ["inquiry"], ["none"]),
    ("核验沿用环境的部署条件与服务器容量是否满足本期平台部署需求", ["inquiry"], ["none"]),
    ("评估现有服务器容量是否满足本期试点范围的部署需求", ["inquiry"], ["none"]),
    ("在建设阶段前核验部署条件并评估服务器容量是否满足本期部署需求", ["inquiry", "inquiry"], ["none", "none"]),
    ("核验现有 SalesMind AI 环境、PostgreSQL 与 pgvector 配置对本期部署的承载条件。", ["inquiry"], ["none"]),
    ("核验完成后开展建设", ["conditional_work"], ["completed"]),
    ("在环境与容量核验完成后开展建设。", ["conditional_work"], ["completed"]),
    ("经核验确认部署条件满足后开展建设", ["conditional_work"], ["satisfied"]),
    ("若经核验部署条件满足，则配置2台服务器", ["conditional_work"], ["satisfied"]),
    ("确认完成后再上线", ["conditional_work"], ["completed"]),
    ("形成容量核验记录", ["planned_artifact"], ["none"]),
    ("容量核验记录", ["planned_artifact"], ["none"]),
    ("形成环境与容量核验记录。", ["planned_artifact"], ["none"]),
    ("若容量不满足，则试点部署可能受到影响", ["hypothetical_risk"], ["none"]),
    ("若容量不满足", ["hypothetical_risk"], ["none"]),
    ("资料上传索引与检索链路可能无法按期在沿用环境中落地，影响试点启动节奏。", ["hypothetical_risk"], ["none"]),
    ("完成容量核验并记录结果", ["verification_outcome"], ["none"]),
    ("完成环境与容量核验并确认本期部署条件", ["verification_outcome"], ["none"]),
    ("核验部署条件。现有服务器容量已经足够。", ["inquiry", "assertion"], ["none", "none"]),
    ("已完成容量核验", ["assertion"], ["none"]),
    ("核验部署条件并保证按期上线", ["inquiry", "assertion"], ["none", "none"]),
])
def test_full_consumption_clauses_distinguish_actions_results_and_prerequisites(text, kinds, prerequisites):
    result = parse(text)
    assert result is not None
    assert [item.kind.value for item in result] == kinds
    assert [item.prerequisite.value for item in result] == prerequisites


@pytest.mark.parametrize("text", [
    "", "核验所有未列明能力", "核验部署条件并随意扩充某项能力", "不核验部署条件", 
    "若客户同意则保证交付", "若容量不满足则开展建设", "核验部署条件是否满足需求保证上线",
    "形成已足够的容量核验记录", "核验现有容量已经足够环境的部署条件",
    "核验目标One Two Three Four Five环境的部署条件",
    "核验目标" + "A" * 33 + "环境的部署条件",
])
def test_unconsumed_or_false_conditions_do_not_become_safe_clauses(text):
    result = parse(text)
    assert result is None or any(item.kind.value == "assertion" for item in result)


@pytest.mark.parametrize("name,accepted", [("One Two Three Four", True), ("One Two Three Four Five", False), ("A" * 32, True), ("A" * 33, False)])
def test_ascii_word_and_length_bounds_are_preserved(name, accepted):
    result = parse(f"核验目标{name}环境的部署条件")
    assert (result is not None and all(item.kind.value == "inquiry" for item in result)) is accepted


def test_closed_object_parser_is_shared_without_action_or_fact_admission():
    assert actions.clarification_object_sequence("部署条件与现有SalesMind AI环境的服务器容量")
    assert not actions.clarification_object_sequence("部署条件与任意未知能力")


def test_dependency_hints_are_closed_objects_not_model_authority():
    assert "deployment_requirement" in parse("评估服务器容量是否足够")[0].dependencies
    assert "existing_environment" in parse("核验现有环境的数据库配置")[0].dependencies
