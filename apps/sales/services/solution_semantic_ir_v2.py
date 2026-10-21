"""Strict generation-only Semantic IR lowering; no semantic repair or invention."""

import hashlib
import json

from apps.sales.services.solution_errors import (
    SolutionDraftError, SolutionDraftErrorCode, SolutionContractFailure,
)
from apps.sales.services.solution_generation_contract import (
    ARCHITECTURE_KEYS, ASSURANCE_RISK_FIELDS, COMPONENT_KEYS,
    CORE_ARCHITECTURE_OVERVIEW_LIMIT, CORE_CAPABILITY_GROUP_ITEMS_LIMIT,
    CORE_CAPABILITY_GROUP_LIMIT, CORE_COMPONENT_FIELD_LIMITS,
    CORE_DEPLOYMENT_TOPIC_LIMITS, CORE_PROPOSED_SOLUTION_LIMIT, EDGE_KEYS,
    IMPLEMENTATION_MILESTONE_FIELD_LIMITS, IMPLEMENTATION_PHASE_FIELD_LIMITS,
    LOCAL_REF, MANAGED_LINKAGE_PLACEMENTS, MAX_ARCHITECTURE_COMPONENTS,
    MAX_ASSURANCE_ACCEPTANCE, MAX_ASSURANCE_OUT_OF_SCOPE,
    MAX_ASSURANCE_PHASE_ACCEPTANCE, MAX_ASSURANCE_RISKS,
    MAX_IMPLEMENTATION_MILESTONES, MAX_IMPLEMENTATION_PHASES,
    MAX_IMPLEMENTATION_PROPOSALS, PASS_ROOT_KEYS, SEMANTIC_IR_VERSION,
    closed_object, reject_contract, validate_claim_fields, validate_citation_allowlist,
)
from apps.sales.services.solution_prompt_v2 import (
    SolutionV2ContainerKind, _unique_object, _reject_constant,
    parse_atomic_solution_v2_proposals,
)


class ImplementationSharedWorkCardinalityError(SolutionDraftError):
    """Retain the established exception and external regeneration contract."""

    category = "implementation_shared_work_cardinality"

    def __init__(self, actual_count, maximum_count):
        self.actual_count = actual_count
        self.maximum_count = maximum_count
        self.expected = f"at most {maximum_count} tasks and timing claims"
        self.contract_failure = SolutionContractFailure(
            self.category, "$", self.expected, f"{actual_count} tasks and timing claims",
        )
        super().__init__(SolutionDraftErrorCode.INVALID_RESPONSE)


def _array(value, *, path):
    if not isinstance(value, list):
        reject_contract("wrong_type", path, "array", type(value).__name__)
    return value


def _bounded_array(value, maximum, *, path, minimum=0, category="local_cardinality"):
    items = _array(value, path=path)
    if not minimum <= len(items) <= maximum:
        reject_contract(category, path, f"{minimum}..{maximum} items", f"{len(items)} items")
    return items


def _ref(value, *, path):
    if not isinstance(value, str) or LOCAL_REF.fullmatch(value) is None:
        reject_contract("invalid_local_ref", path, "lowercase local ref", type(value).__name__)
    return value


def _edge(value, sources, targets, *, path, category="invalid_local_ref", expected="existing local ref"):
    closed_object(value, EDGE_KEYS, path=path)
    source = _ref(value["from"], path=path + ".from")
    target = _ref(value["to"], path=path + ".to")
    for direction, key, allowed in (("from", source, sources), ("to", target, targets)):
        if key not in allowed:
            reject_contract(category, path + "." + direction, expected, "unknown local ref")
    return source, target


def _unique_ref(value, seen, *, path):
    key = _ref(value, path=path)
    if key in seen:
        reject_contract("duplicate_identifier", path, "unique local ref", "duplicate")
    seen.add(key)
    return key


def _implementation_containers(payload):
    """Validate shared cardinality before constructing any atomic proposal."""
    phases, milestones = [], []
    tasks_and_timing = 0
    for name, maximum, required, limits, destination, shared_fields in (
        ("phases", MAX_IMPLEMENTATION_PHASES, {"ref", "objective", "tasks", "deliverables"},
         IMPLEMENTATION_PHASE_FIELD_LIMITS, phases, {"tasks", "timing"}),
        ("milestones", MAX_IMPLEMENTATION_MILESTONES, {"ref", "outcome", "phase_refs"},
         IMPLEMENTATION_MILESTONE_FIELD_LIMITS, milestones, {"timing"}),
    ):
        for index, item in enumerate(_bounded_array(payload[name], maximum, path="$." + name)):
            path = f"$.{name}[{index}]"
            closed_object(item, required, {"timing"}, path=path)
            fields = {}
            for field, (minimum, field_maximum) in limits.items():
                values = _bounded_array(item.get(field, []), field_maximum,
                                        minimum=minimum, path=path + "." + field)
                fields[field] = values
                if field in shared_fields:
                    tasks_and_timing += len(values)
            destination.append((item, fields, path))
    maximum = MAX_IMPLEMENTATION_PROPOSALS - 2 * len(phases) - len(milestones)
    if tasks_and_timing > maximum:
        raise ImplementationSharedWorkCardinalityError(tasks_and_timing, maximum)
    return phases, milestones


def _convert(content, *, pass_name, allowed_source_labels, max_proposals, external_phases=()):
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, ValueError, RecursionError):
        reject_contract("malformed_json", "$", "complete unique-key JSON", "malformed JSON")
    if pass_name not in PASS_ROOT_KEYS:
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_INPUT)
    required, optional = PASS_ROOT_KEYS[pass_name]
    closed_object(payload, required, optional)
    if payload["ir_version"] != SEMANTIC_IR_VERSION:
        reject_contract("invalid_enum", "$.ir_version", SEMANTIC_IR_VERSION, "unknown version")
    validate_citation_allowlist(allowed_source_labels)
    proposals, relations, proposal_paths, relation_paths = [], [], [], []

    def add(section, kind, key, field, value, *, path):
        # Same formal claim validator as the Atomic IR parser, not a mirror.
        validate_claim_fields(value, allowed_source_labels=allowed_source_labels, path=path)
        if ((section, kind, field) in MANAGED_LINKAGE_PLACEMENTS
                and not value["related_requirement_fields"]):
            # An empty linkage short-circuits the unresolved policy and the
            # unresolved-as-confirmed guard, so the deterministic defence would
            # depend on the model volunteering the field. Reject at the contract.
            reject_contract(
                "invalid_requirement_link",
                path + ".related_requirement_fields",
                "at least one RequirementDimension",
                "empty",
            )
        proposals.append({
            "placement": {"section": section, "container_kind": kind,
                          "container_key": key, "field": field},
            "text": value["text"], "citations": value["citations"],
            "related_requirement_fields": value["related_requirement_fields"],
        })
        proposal_paths.append(path)
        if len(proposals) > max_proposals:
            reject_contract("proposal_budget", path, f"at most {max_proposals} proposal claims",
                            f"{len(proposals)} claims")

    def add_many(section, kind, key, field, values, *, path, maximum=None):
        items = _array(values, path=path) if maximum is None else _bounded_array(values, maximum, path=path)
        for index, value in enumerate(items):
            add(section, kind, key, field, value, path=f"{path}[{index}]")

    def relation(name, source_kind, target_kind, source, target, *, path):
        relations.append({
            "relation_type": name, "source_container_kind": source_kind,
            "source_container_key": source, "target_container_kind": target_kind,
            "target_container_key": target,
        })
        relation_paths.append(path)

    if pass_name == "core":
        add_many("proposed_solution", "root", None, "overview", payload["proposed_solution"],
                 path="$.proposed_solution", maximum=CORE_PROPOSED_SOLUTION_LIMIT)
        groups = set()
        for index, group in enumerate(_bounded_array(payload.get("capability_groups", []),
                                                     CORE_CAPABILITY_GROUP_LIMIT, path="$.capability_groups")):
            path = f"$.capability_groups[{index}]"
            closed_object(group, {"ref", "items"}, path=path)
            key = _unique_ref(group["ref"], groups, path=path + ".ref")
            items = _bounded_array(group["items"], CORE_CAPABILITY_GROUP_ITEMS_LIMIT,
                                   minimum=1, path=path + ".items")
            add_many("proposed_solution", "capability_group", key, "items", items, path=path + ".items")
        architecture = closed_object(payload["architecture"], *ARCHITECTURE_KEYS, path="$.architecture")
        add_many("architecture", "root", None, "overview", architecture.get("overview", []),
                 path="$.architecture.overview", maximum=CORE_ARCHITECTURE_OVERVIEW_LIMIT)
        components = set()
        for index, component in enumerate(_bounded_array(architecture["components"],
                                                          MAX_ARCHITECTURE_COMPONENTS,
                                                          path="$.architecture.components")):
            path = f"$.architecture.components[{index}]"
            closed_object(component, COMPONENT_KEYS, path=path)
            key = _unique_ref(component["ref"], components, path=path + ".ref")
            add("architecture", "architecture_component", key, "identity", component["identity"],
                path=path + ".identity")
            for name, maximum in CORE_COMPONENT_FIELD_LIMITS.items():
                values = _bounded_array(component[name], maximum, minimum=1, path=path + "." + name,
                                        category="component_cardinality")
                add_many("architecture", "architecture_component", key, name, values, path=path + "." + name)
        for field, name, category in (
            ("dependencies", "component_dependency", "dangling_dependency"),
            ("request_flows", "component_request_flow", "dangling_request_flow"),
            ("data_flows", "component_data_flow", "dangling_data_flow"),
        ):
            for index, value in enumerate(_array(architecture.get(field, []), path="$.architecture." + field)):
                path = f"$.architecture.{field}[{index}]"
                source, target = _edge(value, components, components, path=path, category=category,
                                       expected="existing architecture component ref")
                relation(name, "architecture_component", "architecture_component", source, target, path=path)
        topics = closed_object(payload["deployment_and_integration"], (), CORE_DEPLOYMENT_TOPIC_LIMITS,
                               path="$.deployment_and_integration")
        for topic, values in topics.items():
            add_many("deployment_and_integration", "topic_block", topic, "items", values,
                     path="$.deployment_and_integration." + topic, maximum=CORE_DEPLOYMENT_TOPIC_LIMITS[topic])
    elif pass_name == "implementation":
        phase_items, milestone_items = _implementation_containers(payload)
        phases, milestones = set(), set()
        for phase, fields, path in phase_items:
            key = _unique_ref(phase["ref"], phases, path=path + ".ref")
            for name, values in fields.items():
                add_many("implementation_plan", "implementation_phase", key, name, values, path=path + "." + name)
        for milestone, fields, path in milestone_items:
            key = _unique_ref(milestone["ref"], milestones, path=path + ".ref")
            for name, values in fields.items():
                add_many("milestones", "milestone", key, name, values, path=path + "." + name)
            refs = _array(milestone["phase_refs"], path=path + ".phase_refs")
            if not refs:
                reject_contract("cardinality", path + ".phase_refs", "at least one phase ref", "0")
            for index, value in enumerate(refs):
                target = _ref(value, path=f"{path}.phase_refs[{index}]")
                if target not in phases:
                    reject_contract("invalid_local_ref", f"{path}.phase_refs[{index}]", "existing phase ref", "unknown local ref")
                relation("milestone_phase", "milestone", "implementation_phase", key, target,
                         path=f"{path}.phase_refs[{index}]")
        for index, value in enumerate(_array(payload["dependencies"], path="$.dependencies")):
            path = f"$.dependencies[{index}]"
            source, target = _edge(value, phases, phases, path=path, category="dangling_dependency",
                                   expected="existing phase ref")
            relation("phase_dependency", "implementation_phase", "implementation_phase", source, target, path=path)
    else:
        risks, criteria = set(), set()
        for index, risk in enumerate(_bounded_array(payload["risks"], MAX_ASSURANCE_RISKS, path="$.risks")):
            path = f"$.risks[{index}]"
            closed_object(risk, {"ref", *ASSURANCE_RISK_FIELDS}, path=path)
            key = _unique_ref(risk["ref"], risks, path=path + ".ref")
            for name in ASSURANCE_RISK_FIELDS:
                values = _bounded_array(risk[name], 1, minimum=1, path=path + "." + name)
                add_many("risks", "risk", key, name, values, path=path + "." + name)
        for index, criterion in enumerate(_bounded_array(payload["acceptance"], MAX_ASSURANCE_ACCEPTANCE, path="$.acceptance")):
            path = f"$.acceptance[{index}]"
            closed_object(criterion, {"ref", "criterion"}, path=path)
            key = _unique_ref(criterion["ref"], criteria, path=path + ".ref")
            values = _bounded_array(criterion["criterion"], 1, minimum=1, path=path + ".criterion")
            add_many("acceptance_criteria", "acceptance_criterion", key, "criterion", values, path=path + ".criterion")
        scope_keys = set()
        for index, value in enumerate(_bounded_array(payload["out_of_scope"], MAX_ASSURANCE_OUT_OF_SCOPE, path="$.out_of_scope")):
            path = f"$.out_of_scope[{index}]"
            validate_claim_fields(value, allowed_source_labels=allowed_source_labels, path=path)
            digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            key = f"scope_{digest}"
            if key in scope_keys:
                reject_contract("duplicate_identifier", path, "unique scope claim", "duplicate")
            scope_keys.add(key)
            add("out_of_scope", "scope", key, "scope", value, path=path)
        for index, value in enumerate(_bounded_array(payload["phase_acceptance"], MAX_ASSURANCE_PHASE_ACCEPTANCE, path="$.phase_acceptance")):
            path = f"$.phase_acceptance[{index}]"
            source, target = _edge(value, set(external_phases), criteria, path=path, expected="existing phase/acceptance ref")
            relation("phase_acceptance", "implementation_phase", "acceptance_criterion", source, target, path=path)

    result = parse_atomic_solution_v2_proposals(
        json.dumps({"proposals": proposals, "structure_relations": relations}, ensure_ascii=False),
        allowed_source_labels=allowed_source_labels, _max_proposals=max_proposals,
        _external_containers=frozenset((SolutionV2ContainerKind.IMPLEMENTATION_PHASE, key) for key in external_phases),
        _proposal_paths=tuple(proposal_paths), _relation_paths=tuple(relation_paths),
    )
    return result


def convert_semantic_solution_v2_output(content, *, pass_name, allowed_source_labels,
                                        max_proposals, external_phases=()):
    return _convert(content, pass_name=pass_name, allowed_source_labels=allowed_source_labels,
                    max_proposals=max_proposals, external_phases=external_phases)
