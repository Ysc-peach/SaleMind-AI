"""Empty linkage may silence the deterministic guard, never the verifier's unresolved context."""

import pytest

from apps.sales.services.solution_prompt_v2 import (
    SolutionV2ContainerKind,
    SolutionV2PlacementField,
    SolutionV2Section,
)
from apps.sales.tests.test_solution_clarification_action_guard import (
    deployment_status,
    partial_analysis,
)
from apps.sales.tests.test_solution_proposal_admissibility_v2 import (
    _AdmissibilityVerifier,
    _proposal,
    _verify,
)


GOVERNED_SCOPES = [
    (
        SolutionV2Section.IMPLEMENTATION_PLAN,
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        SolutionV2PlacementField.OBJECTIVE,
    ),
    (
        SolutionV2Section.RISKS,
        SolutionV2ContainerKind.RISK,
        SolutionV2PlacementField.CONDITION,
    ),
    (
        SolutionV2Section.IMPLEMENTATION_PLAN,
        SolutionV2ContainerKind.MILESTONE,
        SolutionV2PlacementField.OUTCOME,
    ),
]


@pytest.mark.parametrize("section,container_kind,field", GOVERNED_SCOPES)
def test_unlinked_governed_claim_reaches_verifier_with_every_unresolved_dimension(
    section,
    container_kind,
    field,
):
    proposals = _proposal(
        "建立接口访问控制。",
        related=(),
        section=section,
        container_kind=container_kind,
        field=field,
    )
    provider = _AdmissibilityVerifier()

    assert _verify(proposals, provider, analysis=partial_analysis()) is proposals
    packet = provider.packets[0]

    assert packet["related_requirement_fields"] == []
    assert deployment_status(packet) == "unclear"
