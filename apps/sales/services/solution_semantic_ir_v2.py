"""Strict generation-only Semantic IR to existing atomic V2 proposal IR.

This adapter supplies structural placement metadata, never proposal semantics.
The existing proposal parser remains the authority for claims and relations.
"""

import hashlib
import json

from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.solution_prompt_v2 import (
    CORE_ARCHITECTURE_OVERVIEW_LIMIT,
    CORE_CAPABILITY_GROUP_ITEMS_LIMIT,
    CORE_CAPABILITY_GROUP_LIMIT,
    CORE_COMPONENT_FIELD_LIMITS,
    CORE_DEPLOYMENT_TOPIC_LIMITS,
    CORE_PROPOSED_SOLUTION_LIMIT,
    IMPLEMENTATION_MILESTONE_FIELD_LIMITS,
    IMPLEMENTATION_PHASE_FIELD_LIMITS,
    ASSURANCE_RISK_FIELDS,
    MAX_ASSURANCE_ACCEPTANCE,
    MAX_ASSURANCE_OUT_OF_SCOPE,
    MAX_ASSURANCE_PHASE_ACCEPTANCE,
    MAX_ASSURANCE_RISKS,
    MAX_IMPLEMENTATION_MILESTONES,
    MAX_IMPLEMENTATION_PHASES,
    MAX_IMPLEMENTATION_PROPOSALS,
    MAX_ARCHITECTURE_COMPONENTS,
    SolutionV2ContainerKind,
    _CONTAINER_KEY,
    _invalid,
    _reject_constant,
    _unique_object,
    parse_atomic_solution_v2_proposals,
)


_CLAIM_KEYS = {"text", "citations", "related_requirement_fields"}
_TOPICS = {"deployment", "integration", "data_security", "environment"}


class ImplementationSharedWorkCardinalityError(SolutionDraftError):
    """Safe internal attribution; retain the existing external error/retry contract."""

    category = "implementation_shared_work_cardinality"

    def __init__(self, actual_count, maximum_count):
        self.actual_count = actual_count
        self.maximum_count = maximum_count
        self.expected = f"at most {maximum_count} tasks and timing claims"
        super().__init__(SolutionDraftErrorCode.INVALID_RESPONSE)


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - (set(required) | set(optional)):
        _invalid()


def _array(value):
    if not isinstance(value, list):
        _invalid()
    return value


def _nonempty(value):
    items = _array(value)
    if not items:
        _invalid()
    return items


def _bounded_array(value, maximum):
    items = _array(value)
    if len(items) > maximum:
        _invalid()
    return items


def _ref(value):
    if not isinstance(value, str) or _CONTAINER_KEY.fullmatch(value) is None:
        _invalid()
    return value


def _claim(value):
    _object(value, _CLAIM_KEYS)
    return value


def _edge(value, sources, targets):
    _object(value, {"from", "to"})
    source, target = _ref(value["from"]), _ref(value["to"])
    if source not in sources or target not in targets:
        _invalid()
    return source, target


def _implementation_containers(payload):
    """Validate local/shared cardinality before constructing any atomic proposal."""
    phases = []
    milestones = []
    tasks_and_timing = 0
    for items, maximum, required, limits, destination, shared_fields in (
        (payload["phases"], MAX_IMPLEMENTATION_PHASES,
         {"ref", "objective", "tasks", "deliverables"},
         IMPLEMENTATION_PHASE_FIELD_LIMITS, phases, {"tasks", "timing"}),
        (payload["milestones"], MAX_IMPLEMENTATION_MILESTONES,
         {"ref", "outcome", "phase_refs"},
         IMPLEMENTATION_MILESTONE_FIELD_LIMITS, milestones, {"timing"}),
    ):
        for item in _bounded_array(items, maximum):
            _object(item, required, {"timing"})
            fields = {}
            for name, (minimum, field_maximum) in limits.items():
                values = _bounded_array(item.get(name, []), field_maximum)
                if len(values) < minimum:
                    _invalid()
                fields[name] = values
                if name in shared_fields:
                    tasks_and_timing += len(values)
            destination.append((item, fields))
    maximum_tasks_and_timing = (
        MAX_IMPLEMENTATION_PROPOSALS - 2 * len(phases) - len(milestones)
    )
    if tasks_and_timing > maximum_tasks_and_timing:
        raise ImplementationSharedWorkCardinalityError(
            tasks_and_timing, maximum_tasks_and_timing,
        )
    return phases, milestones


def _convert(content, *, pass_name, allowed_source_labels, max_proposals, external_phases=()):
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, ValueError, RecursionError):
        _invalid()
    proposals = []
    relations = []

    def add(section, kind, key, field, value):
        item = _claim(value)
        proposals.append({
            "placement": {"section": section, "container_kind": kind,
                          "container_key": key, "field": field},
            "text": item["text"], "citations": item["citations"],
            "related_requirement_fields": item["related_requirement_fields"],
        })
        if len(proposals) > max_proposals:
            _invalid()

    def add_many(section, kind, key, field, values, *, maximum=None):
        items = _array(values) if maximum is None else _bounded_array(values, maximum)
        for value in items:
            add(section, kind, key, field, value)

    def relation(relation_type, source_kind, target_kind, source, target):
        relations.append({
            "relation_type": relation_type,
            "source_container_kind": source_kind,
            "source_container_key": source,
            "target_container_kind": target_kind,
            "target_container_key": target,
        })

    if pass_name == "core":
        _object(payload, {"ir_version", "proposed_solution", "architecture", "deployment_and_integration"}, {"capability_groups"})
        add_many("proposed_solution", "root", None, "overview", payload["proposed_solution"],
                 maximum=CORE_PROPOSED_SOLUTION_LIMIT)
        groups = set()
        for group in _bounded_array(payload.get("capability_groups", []), CORE_CAPABILITY_GROUP_LIMIT):
            _object(group, {"ref", "items"})
            key = _ref(group["ref"])
            if key in groups:
                _invalid()
            groups.add(key)
            add_many("proposed_solution", "capability_group", key, "items", _nonempty(group["items"]),
                     maximum=CORE_CAPABILITY_GROUP_ITEMS_LIMIT)
        architecture = payload["architecture"]
        _object(architecture, {"components"}, {"overview", "dependencies", "request_flows", "data_flows"})
        add_many("architecture", "root", None, "overview", architecture.get("overview", []),
                 maximum=CORE_ARCHITECTURE_OVERVIEW_LIMIT)
        components = set()
        for component in _bounded_array(architecture["components"], MAX_ARCHITECTURE_COMPONENTS):
            _object(component, {"ref", "identity", "responsibilities", "rationale", "interfaces"})
            key = _ref(component["ref"])
            if key in components:
                _invalid()
            components.add(key)
            add("architecture", "architecture_component", key, "identity", component["identity"])
            for name in ("responsibilities", "rationale", "interfaces"):
                add_many("architecture", "architecture_component", key, name, component[name],
                         maximum=CORE_COMPONENT_FIELD_LIMITS[name])
        for name, kind in (("dependencies", "component_dependency"),
                           ("request_flows", "component_request_flow"),
                           ("data_flows", "component_data_flow")):
            for value in _array(architecture.get(name, [])):
                source, target = _edge(value, components, components)
                relation(kind, "architecture_component", "architecture_component", source, target)
        topics = payload["deployment_and_integration"]
        if not isinstance(topics, dict) or set(topics) - _TOPICS:
            _invalid()
        for topic, values in topics.items():
            add_many("deployment_and_integration", "topic_block", topic, "items", values,
                     maximum=CORE_DEPLOYMENT_TOPIC_LIMITS[topic])

    elif pass_name == "implementation":
        _object(payload, {"ir_version", "phases", "milestones", "dependencies"})
        phase_items, milestone_items = _implementation_containers(payload)
        phases = set()
        for phase, fields in phase_items:
            key = _ref(phase["ref"])
            if key in phases:
                _invalid()
            phases.add(key)
            for name, items in fields.items():
                add_many("implementation_plan", "implementation_phase", key, name, items)
        milestones = set()
        for milestone, fields in milestone_items:
            key = _ref(milestone["ref"])
            if key in milestones:
                _invalid()
            milestones.add(key)
            for name, items in fields.items():
                add_many("milestones", "milestone", key, name, items)
            for phase_key in _array(milestone["phase_refs"]):
                phase_key = _ref(phase_key)
                if phase_key not in phases:
                    _invalid()
                relation("milestone_phase", "milestone", "implementation_phase", key, phase_key)
        for value in _array(payload["dependencies"]):
            source, target = _edge(value, phases, phases)
            relation("phase_dependency", "implementation_phase", "implementation_phase", source, target)

    elif pass_name == "assurance":
        _object(payload, {"ir_version", "risks", "acceptance", "out_of_scope", "phase_acceptance"})
        risks = set()
        for risk in _bounded_array(payload["risks"], MAX_ASSURANCE_RISKS):
            _object(risk, {"ref", *ASSURANCE_RISK_FIELDS})
            key = _ref(risk["ref"])
            if key in risks:
                _invalid()
            risks.add(key)
            for name in ASSURANCE_RISK_FIELDS:
                items = _bounded_array(risk[name], 1)
                if len(items) != 1:
                    _invalid()
                add_many("risks", "risk", key, name, items)
        criteria = set()
        for criterion in _bounded_array(payload["acceptance"], MAX_ASSURANCE_ACCEPTANCE):
            _object(criterion, {"ref", "criterion"})
            key = _ref(criterion["ref"])
            if key in criteria:
                _invalid()
            criteria.add(key)
            items = _bounded_array(criterion["criterion"], 1)
            if len(items) != 1:
                _invalid()
            add_many("acceptance_criteria", "acceptance_criterion", key, "criterion", items)
        scope_keys = set()
        for value in _bounded_array(payload["out_of_scope"], MAX_ASSURANCE_OUT_OF_SCOPE):
            item = _claim(value)
            digest = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            key = f"scope_{digest}"
            if key in scope_keys:
                _invalid()
            scope_keys.add(key)
            add("out_of_scope", "scope", key, "scope", item)
        for value in _bounded_array(payload["phase_acceptance"], MAX_ASSURANCE_PHASE_ACCEPTANCE):
            source, target = _edge(value, set(external_phases), criteria)
            relation("phase_acceptance", "implementation_phase", "acceptance_criterion", source, target)
    else:
        _invalid()
    if payload["ir_version"] != "semantic_v1":
        _invalid()
    return parse_atomic_solution_v2_proposals(
        json.dumps({"proposals": proposals, "structure_relations": relations}, ensure_ascii=False),
        allowed_source_labels=allowed_source_labels,
        _max_proposals=max_proposals,
        _external_containers=frozenset(
            (SolutionV2ContainerKind.IMPLEMENTATION_PHASE, key)
            for key in external_phases
        ),
    )


def convert_semantic_solution_v2_output(content, *, pass_name, allowed_source_labels,
                                        max_proposals, external_phases=()):
    return _convert(content, pass_name=pass_name,
                    allowed_source_labels=allowed_source_labels,
                    max_proposals=max_proposals, external_phases=external_phases)
