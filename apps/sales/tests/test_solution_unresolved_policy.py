"""Planning candidates preserve frozen facts and require result prerequisites."""

from dataclasses import asdict, replace
import pytest

from apps.sales.services.requirement_analysis import RequirementDimension as D, RequirementStatus as S, RequirementFieldAnalysis
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis
from apps.sales.tests.test_solution_v2_pipeline import analysis_fixture

TARGETS = [
    (("implementation_plan", "implementation_phase", "objective"), "核验部署条件。"),
    (("implementation_plan", "implementation_phase", "tasks"), "核验部署条件。"),
    (("implementation_plan", "implementation_phase", "deliverables"), "形成容量核验记录。"),
    (("implementation_plan", "implementation_phase", "timing"), "经核验确认部署条件满足后开展建设。"),
    (("risks", "risk", "condition"), "若容量不满足"),
    (("risks", "risk", "impact"), "若容量不满足，则试点部署可能受到影响"),
    (("risks", "risk", "mitigation"), "评估服务器容量是否足够。"),
    (("milestones", "milestone", "outcome"), "完成容量核验并记录结果"),
]


def evaluate(text, placement=TARGETS[0][0], *, analysis=None, related=(D.DEPLOYMENT_REQUIREMENT,)):
    from apps.sales.services.solution_unresolved_policy import evaluate_unresolved_v2_policy
    return evaluate_unresolved_v2_policy(analysis=analysis or partial_analysis(), related_fields=related, text=text, placement=placement)


@pytest.mark.parametrize("placement,text", TARGETS)
@pytest.mark.parametrize("status", [S.UNKNOWN, S.UNCLEAR, S.CONFLICT])
def test_all_legal_target_candidates_keep_unresolved_status(placement, text, status):
    analysis = partial_analysis(status)
    before = asdict(analysis)
    assert evaluate(text, placement, analysis=analysis).decision.value == "candidate"
    assert asdict(analysis) == before


@pytest.mark.parametrize("placement,_", TARGETS)
def test_each_target_rejects_existing_result_assertion(placement, _):
    result = evaluate("现有服务器容量已经足够。", placement)
    assert (result.decision.value, result.reason.value) == ("reject", "unconfirmed_assertion")


@pytest.mark.parametrize("placement,_", TARGETS)
def test_unknown_expression_is_not_customer_missing_information(placement, _):
    assert evaluate("处理其它任意未知事项", placement).reason.value == "expression_unclassified"


@pytest.mark.parametrize("related", [(), (D.BUSINESS_GOAL,)])
def test_explicit_nonknown_capacity_cannot_hide_behind_empty_or_known_link(related):
    assert evaluate("评估服务器容量是否足够", related=related).reason.value == "invalid_linkage"


def test_completed_event_does_not_authorize_unresolved_deployment():
    result = evaluate("核验完成后开展建设", TARGETS[3][0])
    assert (result.decision.value, result.reason.value) == ("reject", "unqualified_precondition")


def test_completion_only_timeline_keeps_conditional_schedule_not_capacity_admission():
    analysis = analysis_fixture()
    analysis = replace(analysis, requirements=replace(analysis.requirements, timeline=RequirementFieldAnalysis(S.UNCLEAR, None, "时间尚未确认")))
    assert evaluate("确认完成后再上线", TARGETS[3][0], analysis=analysis, related=(D.TIMELINE,)).decision.value == "candidate"


def test_known_ordinary_technical_claim_uses_original_guards():
    assert evaluate("采用分层处理降低入口耦合。", analysis=analysis_fixture(), related=(D.BUSINESS_GOAL,)) is None


@pytest.mark.parametrize("placement", [
    ("architecture", "architecture_component", "rationale"),
    ("risks", "risk", "trigger"), ("milestones", "milestone", "timing"),
    ("milestones", "milestone", "criterion"),
])
def test_excluded_or_illegal_placements_never_get_policy_admission(placement):
    assert evaluate("核验部署条件", placement) is None


@pytest.mark.parametrize("text,related", [(None, (D.BUSINESS_GOAL,)), ("", ()), ("核验部署条件", ("business_goal",))])
def test_invalid_input_does_not_exploit_all_known_shortcut(text, related):
    assert evaluate(text, related=related).decision.value != "candidate"


def test_parent_inquiry_cannot_hide_independent_assertion():
    assert evaluate("核验部署条件。服务器容量已经足够。").reason.value == "unconfirmed_assertion"


def test_satisfied_prerequisite_must_cover_each_unresolved_result_dependency():
    analysis = partial_analysis()
    analysis = replace(analysis, requirements=replace(analysis.requirements,
        existing_environment=RequirementFieldAnalysis(S.UNCLEAR, None, "环境尚未核验")))
    related = (D.DEPLOYMENT_REQUIREMENT, D.EXISTING_ENVIRONMENT)
    assert evaluate("经核验确认部署条件满足后开展建设", TARGETS[3][0], analysis=analysis, related=related).reason.value == "unqualified_precondition"
    assert evaluate("经核验确认部署条件与环境满足后开展建设", TARGETS[3][0], analysis=analysis, related=related).decision.value == "candidate"
