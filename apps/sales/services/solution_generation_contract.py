"""Shared generation-only cardinalities and closed shape definitions.

These describe the existing Semantic IR, not a new persisted schema. Rejection
helpers emit evidence at the executing validator; evaluation never re-validates.
"""

import re
from typing import NoReturn

from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_errors import (
    SolutionContractError, SolutionContractFailure, SolutionDraftError, SolutionDraftErrorCode,
)


MAX_ARCHITECTURE_COMPONENTS = 4
CORE_PROPOSED_SOLUTION_LIMIT = 5
CORE_ARCHITECTURE_OVERVIEW_LIMIT = 2
CORE_COMPONENT_FIELD_LIMITS = {"responsibilities": 2, "rationale": 1, "interfaces": 2}
CORE_DEPLOYMENT_TOPIC_LIMITS = {"deployment": 4, "integration": 3, "data_security": 2, "environment": 2}
CORE_CAPABILITY_GROUP_LIMIT = 2
CORE_CAPABILITY_GROUP_ITEMS_LIMIT = 2
MAX_CORE_PROPOSALS = (
    CORE_PROPOSED_SOLUTION_LIMIT + CORE_ARCHITECTURE_OVERVIEW_LIMIT
    + MAX_ARCHITECTURE_COMPONENTS * (1 + sum(CORE_COMPONENT_FIELD_LIMITS.values()))
    + sum(CORE_DEPLOYMENT_TOPIC_LIMITS.values())
    + CORE_CAPABILITY_GROUP_LIMIT * CORE_CAPABILITY_GROUP_ITEMS_LIMIT
)
MAX_IMPLEMENTATION_PROPOSALS = 18
MAX_ASSURANCE_PROPOSALS = 20
MAX_ASSURANCE_RISKS = 3
ASSURANCE_RISK_FIELDS = ("condition", "impact", "mitigation", "trigger")
MAX_ASSURANCE_ACCEPTANCE = 6
MAX_ASSURANCE_OUT_OF_SCOPE = 2
MAX_ASSURANCE_PHASE_ACCEPTANCE = 6
MAX_SOLUTION_V2_PROPOSALS = MAX_CORE_PROPOSALS + MAX_IMPLEMENTATION_PROPOSALS + MAX_ASSURANCE_PROPOSALS
MAX_IMPLEMENTATION_PHASES = 4
IMPLEMENTATION_PHASE_FIELD_LIMITS = {"objective": (1, 1), "tasks": (1, 2), "deliverables": (1, 1), "timing": (0, 1)}
MAX_IMPLEMENTATION_MILESTONES = 2
IMPLEMENTATION_MILESTONE_FIELD_LIMITS = {"outcome": (1, 1), "timing": (0, 1)}
IMPLEMENTATION_SECTION_PROPOSAL_LIMITS = {
    "implementation_plan": 16,
    "milestones": MAX_IMPLEMENTATION_MILESTONES * sum(value[1] for value in IMPLEMENTATION_MILESTONE_FIELD_LIMITS.values()),
}
ASSURANCE_SECTION_PROPOSAL_LIMITS = {
    "risks": MAX_ASSURANCE_RISKS * len(ASSURANCE_RISK_FIELDS),
    "acceptance_criteria": MAX_ASSURANCE_ACCEPTANCE,
    "assumptions": 2, "open_questions": 2, "out_of_scope": MAX_ASSURANCE_OUT_OF_SCOPE,
}
SEMANTIC_IR_VERSION = "semantic_v1"
CLAIM_KEYS = frozenset({"text", "citations", "related_requirement_fields"})
# Placements whose claims are judged by the unresolved policy. They must cite at
# least one requirement dimension, otherwise an empty linkage would silently
# bypass the deterministic unresolved-as-confirmed guard. Kept in the contract
# layer so the Semantic IR parser rejects it before any policy or guard runs.
MANAGED_LINKAGE_PLACEMENTS = frozenset({
    ("implementation_plan", "implementation_phase", "objective"),
    ("implementation_plan", "implementation_phase", "tasks"),
    ("implementation_plan", "implementation_phase", "deliverables"),
    ("implementation_plan", "implementation_phase", "timing"),
    ("risks", "risk", "condition"),
    ("risks", "risk", "impact"),
    ("risks", "risk", "mitigation"),
    ("milestones", "milestone", "outcome"),
})
COMPONENT_KEYS = frozenset({"ref", "identity", "responsibilities", "rationale", "interfaces"})
EDGE_KEYS = frozenset({"from", "to"})
PASS_ROOT_KEYS = {
    "core": (frozenset({"ir_version", "proposed_solution", "architecture", "deployment_and_integration"}), frozenset({"capability_groups"})),
    "implementation": (frozenset({"ir_version", "phases", "milestones", "dependencies"}), frozenset()),
    "assurance": (frozenset({"ir_version", "risks", "acceptance", "out_of_scope", "phase_acceptance"}), frozenset()),
}
SEMANTIC_ROOT_KEYS = frozenset(key for required, optional in PASS_ROOT_KEYS.values()
                               for key in required | optional if key != "ir_version")
ARCHITECTURE_KEYS = (frozenset({"components"}), frozenset({"overview", "dependencies", "request_flows", "data_flows"}))
LOCAL_REF = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SAFE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SAFE_CITATION = re.compile(r"S[1-9][0-9]*\Z")
_SOURCE_TOKEN = re.compile(r"(?<![A-Za-z0-9_])S[0-9]+(?![A-Za-z0-9_])")


def key_path(path: str, key: object) -> str:
    return path + "." + (key if isinstance(key, str) and _SAFE_KEY.fullmatch(key) else "<key>")


def reject_contract(category: str, path: str, expected: str, actual: str, **metadata) -> NoReturn:
    raise SolutionContractError(SolutionContractFailure(category, path, expected, actual, **metadata))


def closed_object(value, required, optional=(), *, path="$"):
    if not isinstance(value, dict):
        reject_contract("wrong_type", path, "object", type(value).__name__)
    missing = set(required) - value.keys()
    if missing:
        reject_contract("missing_required_key", key_path(path, sorted(missing)[0]), "required key present", "missing",
                        allowed_keys=tuple(sorted(set(required) | set(optional))))
    unknown = value.keys() - (set(required) | set(optional))
    if unknown:
        reject_contract("unknown_key", key_path(path, sorted(unknown)[0]), "allowed key", "unknown key",
                        allowed_keys=tuple(sorted(set(required) | set(optional))))
    return value


def validate_citation_allowlist(labels):
    if (not isinstance(labels, tuple)
        or any(not isinstance(label, str) for label in labels)
        or len(set(labels)) != len(labels)):
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_INPUT)


def validate_claim_fields(value, *, allowed_source_labels, path="$", require_linkage=True):
    """The one claim validator used by Semantic and legacy Atomic IR parsers."""
    closed_object(value, CLAIM_KEYS if require_linkage else {"text", "citations"},
                  () if require_linkage else {"related_requirement_fields"}, path=path)
    text = value["text"]
    if not isinstance(text, str) or not text.strip():
        reject_contract("wrong_type", path + ".text", "non-empty text", type(text).__name__)
    text = text.strip()
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        reject_contract("wrong_type", path + ".text", "UTF-8 encodable text", "invalid Unicode")
    if _SOURCE_TOKEN.search(text):
        reject_contract("other_contract_failure", path + ".text", "claim text without inline citation tokens", "inline citation token")
    citations = value["citations"]
    subtype = None
    offending = ()
    # Validate element types before hashing anything supplied by a model.
    if not isinstance(citations, list) or any(not isinstance(label, str) for label in citations):
        subtype = "wrong_type"
        offending = tuple(label for label in citations if not isinstance(label, str)) if isinstance(citations, list) else ()
    elif not citations:
        subtype = "empty"
    elif len(set(citations)) != len(citations):
        subtype = "duplicate"
        offending = tuple(label for i, label in enumerate(citations) if label in citations[:i])
    elif any(label not in allowed_source_labels for label in citations):
        offending = tuple(label for label in citations if label not in allowed_source_labels)
        subtype = "not_in_allowlist" if all(_SAFE_CITATION.fullmatch(label) for label in offending) else "malformed"
    if subtype is not None:
        def safe_id(label):
            if not isinstance(label, str):
                return f"<{type(label).__name__}>"
            return label if _SAFE_CITATION.fullmatch(label) else "<redacted>"
        reject_contract("invalid_citation", path + ".citations", "non-empty unique allowed citation IDs", subtype,
                        citation_subtype=subtype,
                        allowed_ids=tuple(safe_id(label) for label in allowed_source_labels),
                        offending_ids=tuple(safe_id(label) for label in offending))
    fields = value.get("related_requirement_fields", [])
    if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
        reject_contract("invalid_requirement_link", path + ".related_requirement_fields", "unique RequirementDimension values", "wrong_type")
    if len(set(fields)) != len(fields):
        reject_contract("invalid_requirement_link", path + ".related_requirement_fields", "unique RequirementDimension values", "duplicate")
    try:
        related = tuple(RequirementDimension(field) for field in fields)
    except ValueError:
        reject_contract("invalid_requirement_link", path + ".related_requirement_fields", "unique RequirementDimension values", "invalid_enum")
    return text, tuple(citations), related
