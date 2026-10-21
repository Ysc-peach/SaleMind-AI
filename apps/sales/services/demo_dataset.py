"""Offline, idempotent setup and fail-closed cleanup for the product demo."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.files.base import ContentFile
from django.db import models, transaction
from langgraph.types import Command

from apps.accounts.models import UserRole
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
    EnterpriseGroundingFactStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
)
from apps.knowledge.parsers.validation import validate_document_file
from apps.knowledge.services.grounding_fact_approval import approve_grounding_facts
from apps.knowledge.services.grounding_facts import extract_grounding_facts
from apps.knowledge.services.indexing import index_document
from apps.sales.demo_fixtures import (
    DEMO_IDENTITIES,
    DEMO_KNOWLEDGE,
    DEMO_SCENARIOS,
    DemoEmbeddingProvider,
    DemoGroundingExtractionProvider,
    DemoRequirementAnalysisProvider,
    DemoScenario,
    DemoSolutionProposalProvider,
    DemoVerifierProvider,
    demo_workflow_id,
)
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    OpportunityStage,
    OpportunityStatus,
    SolutionDraftProvenance,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)
from apps.sales.services.requirement_analysis_history import (
    analysis_record_to_domain,
    create_opportunity_requirement_analysis,
)
from apps.sales.services.requirement_analysis import (
    REQUIREMENT_ANALYSIS_VERSION,
    _parse_analysis,
    _parse_generated_analysis,
)
from apps.sales.services.solution_persistence import (
    generate_and_persist_solution_draft,
)
from apps.sales.services.solution_review_workflow import (
    SolutionHumanAction,
    SolutionWorkflowOutcome,
    build_solution_review_graph,
)
from apps.sales.services.solution_workflow_checkpoint import (
    open_solution_workflow_checkpointer,
    setup_solution_workflow_checkpoint_schema,
)


class DemoDatasetError(Exception):
    """A safe setup/cleanup failure without fixture data or credentials."""


@dataclass(frozen=True, slots=True)
class DemoDatasetResult:
    users: int
    customers: int
    opportunities: int
    analyses: int
    solutions: int
    reviews: int
    documents: int
    facts: int


@dataclass(slots=True)
class _DemoGraph:
    users: dict[str, object]
    customers: dict[str, Customer]
    opportunities: dict[str, Opportunity]
    analyses: dict[str, OpportunityRequirementAnalysis]
    solutions: dict[str, SolutionDraftRecord]
    reviews: dict[str, SolutionReview]
    documents: dict[str, KnowledgeDocument]
    facts: tuple[EnterpriseGroundingFact, ...]
    provenance: tuple[SolutionDraftProvenance, ...]


_TARGETS = {
    "manufacturing_knowledge": "waiting_for_sales_confirmation",
    "retail_collaboration": "waiting_for_presales_review",
    "enterprise_service_approved": "approved",
    "manufacturing_identity": "customer_info_required",
    "ecommerce_ha_revision": "technical_revision_required",
}
_RETURN_COMMENTS = {
    "manufacturing_identity": "请销售向客户确认 SSO 协议类型及身份字段映射。",
    "ecommerce_ha_revision": "客户信息已充分，请补充故障切换与服务冗余设计。",
}


def seed_demo_dataset(password: str) -> DemoDatasetResult:
    """Create/recover the exact offline demo graph without provider shortcuts."""

    if not isinstance(password, str) or not password:
        raise DemoDatasetError("SALESMIND_DEMO_PASSWORD is required.")
    validate_password(password)
    _collect_demo_graph()
    users = _ensure_users(password)
    documents, facts = _ensure_knowledge(users["admin"])
    customers = {}
    opportunities = {}
    analyses = {}
    solutions = {}
    embedding_provider = DemoEmbeddingProvider()
    verifier_provider = DemoVerifierProvider()

    for scenario in DEMO_SCENARIOS:
        customer = _ensure_customer(scenario, users[scenario.sales_key])
        opportunity = _ensure_opportunity(
            scenario,
            customer,
            users[scenario.sales_key],
            users[scenario.presales_key],
        )
        analysis = _ensure_analysis(scenario, opportunity, users[scenario.sales_key])
        solution = generate_and_persist_solution_draft(
            opportunity,
            analysis,
            created_by=users[scenario.sales_key],
            embedding_provider=embedding_provider,
            llm_provider=DemoSolutionProposalProvider(scenario),
            verifier_provider=verifier_provider,
            idempotency_key=demo_workflow_id(scenario.key),
            schema_version=2,
        )
        _validate_solution(solution, scenario, opportunity, analysis, users)
        customers[scenario.key] = customer
        opportunities[scenario.key] = opportunity
        analyses[scenario.key] = analysis
        solutions[scenario.key] = solution

    setup_solution_workflow_checkpoint_schema()
    with open_solution_workflow_checkpointer() as checkpointer:
        graph = build_solution_review_graph(checkpointer)
        for scenario in DEMO_SCENARIOS:
            _ensure_workflow(
                graph,
                scenario,
                solutions[scenario.key],
                analyses[scenario.key],
                users,
            )

    complete = _collect_demo_graph(require_complete=True)
    return DemoDatasetResult(
        users=len(complete.users),
        customers=len(complete.customers),
        opportunities=len(complete.opportunities),
        analyses=len(complete.analyses),
        solutions=len(complete.solutions),
        reviews=len(complete.reviews),
        documents=len(complete.documents),
        facts=len(complete.facts),
    )


def clear_demo_dataset() -> DemoDatasetResult:
    """Delete only the validated demo ownership graph; never guess by substring."""

    graph = _collect_demo_graph()
    has_business_rows = any(
        (
            graph.users,
            graph.customers,
            graph.opportunities,
            graph.analyses,
            graph.solutions,
            graph.documents,
        )
    )
    if has_business_rows:
        _validate_no_external_references(graph)

    file_refs = tuple(
        (document.source_file.storage, document.source_file.name)
        for document in graph.documents.values()
        if document.source_file.name
    )
    result = DemoDatasetResult(
        users=len(graph.users),
        customers=len(graph.customers),
        opportunities=len(graph.opportunities),
        analyses=len(graph.analyses),
        solutions=len(graph.solutions),
        reviews=len(graph.reviews),
        documents=len(graph.documents),
        facts=len(graph.facts),
    )
    if has_business_rows:
        with transaction.atomic():
            SolutionDraftProvenance.objects.filter(
                pk__in=[item.pk for item in graph.provenance]
            ).delete()
            SolutionReview.objects.filter(
                pk__in=[item.pk for item in graph.reviews.values()]
            ).delete()
            SolutionDraftRecord.objects.filter(
                pk__in=[item.pk for item in graph.solutions.values()]
            ).delete()
            OpportunityRequirementAnalysis.objects.filter(
                pk__in=[item.pk for item in graph.analyses.values()]
            ).delete()
            Opportunity.objects.filter(
                pk__in=[item.pk for item in graph.opportunities.values()]
            ).delete()
            Customer.objects.filter(
                pk__in=[item.pk for item in graph.customers.values()]
            ).delete()
            EnterpriseGroundingFact.objects.filter(
                pk__in=[item.pk for item in graph.facts]
            ).delete()
            KnowledgeDocument.objects.filter(
                pk__in=[item.pk for item in graph.documents.values()]
            ).delete()
            get_user_model().objects.filter(
                pk__in=[item.pk for item in graph.users.values()]
            ).delete()
    workflow_ids = tuple(str(demo_workflow_id(item.key)) for item in DEMO_SCENARIOS)
    with open_solution_workflow_checkpointer() as checkpointer:
        for workflow_id in workflow_ids:
            checkpointer.delete_thread(workflow_id)
    for storage, name in file_refs:
        if storage.exists(name):
            storage.delete(name)
    return result


def _ensure_users(password: str) -> dict[str, object]:
    user_model = get_user_model()
    _preflight_user_identities()
    users = {}
    for fixture in DEMO_IDENTITIES:
        user = user_model.objects.filter(username=fixture.username).first()
        if user is None:
            user = user_model.objects.create_user(
                username=fixture.username,
                email=fixture.email,
                role=fixture.role,
                password=password,
            )
            user.first_name = fixture.first_name
            user.last_name = fixture.last_name
            user.is_staff = fixture.is_staff
            user.is_superuser = False
            user.is_active = True
        else:
            _validate_user(user, fixture)
            user.set_password(password)
        user.save(
            update_fields=[
                "password",
                "first_name",
                "last_name",
                "is_staff",
                "is_superuser",
                "is_active",
            ]
        )
        users[fixture.key] = user
    return users


def _preflight_user_identities() -> None:
    user_model = get_user_model()
    for fixture in DEMO_IDENTITIES:
        username_match = user_model.objects.filter(username=fixture.username).first()
        email_match = user_model.objects.filter(email=fixture.email).first()
        if username_match is not None:
            _validate_user(username_match, fixture)
        if email_match is not None and (
            username_match is None or email_match.pk != username_match.pk
        ):
            raise DemoDatasetError("Demo fixture identity conflict.")


def _validate_user(user, fixture) -> None:
    expected = (
        fixture.username,
        fixture.email,
        fixture.role,
        fixture.first_name,
        fixture.last_name,
        fixture.is_staff,
        False,
        True,
    )
    actual = (
        user.username,
        user.email,
        user.role,
        user.first_name,
        user.last_name,
        user.is_staff,
        user.is_superuser,
        user.is_active,
    )
    if actual != expected:
        raise DemoDatasetError("Demo fixture identity conflict.")


def _ensure_customer(scenario: DemoScenario, sales_user) -> Customer:
    values = {
        "industry": scenario.industry,
        "company_size": scenario.company_size,
        "basic_info": scenario.customer_summary,
        "created_by": sales_user,
    }
    customer, created = Customer.objects.get_or_create(
        name=scenario.customer_name,
        defaults=values,
    )
    if not created and any(getattr(customer, key) != value for key, value in values.items()):
        raise DemoDatasetError("Demo customer fixture conflict.")
    return customer


def _ensure_opportunity(
    scenario: DemoScenario,
    customer: Customer,
    sales_user,
    presales_user,
) -> Opportunity:
    raw_requirement = (
        f"{scenario.customer_summary} 目标：{scenario.business_goal}。"
        f"场景：{scenario.use_scenario}。"
    )
    values = {
        "customer": customer,
        "sales_owner": sales_user,
        "presales_owner": presales_user,
        "raw_requirement": raw_requirement,
        "budget": None,
        "stage": OpportunityStage.SOLUTION,
        "status": OpportunityStatus.ACTIVE,
        "expected_launch_date": None,
        "created_by": sales_user,
    }
    opportunity, created = Opportunity.objects.get_or_create(
        project_name=scenario.project_name,
        defaults=values,
    )
    if not created and any(
        getattr(opportunity, f"{key}_id", None) != value.pk
        if isinstance(value, models.Model)
        else getattr(opportunity, key) != value
        for key, value in values.items()
    ):
        raise DemoDatasetError("Demo opportunity fixture conflict.")
    return opportunity


def _ensure_analysis(scenario: DemoScenario, opportunity: Opportunity, sales_user):
    provider = DemoRequirementAnalysisProvider(scenario)
    matches = OpportunityRequirementAnalysis.objects.filter(
        opportunity=opportunity,
        analysis_version__in=("v1", REQUIREMENT_ANALYSIS_VERSION),
        llm_provider=provider.provider_name,
        llm_model=provider.model_name,
    )
    if matches.count() > 1:
        raise DemoDatasetError("Demo requirement analysis fixture conflict.")
    analysis = matches.first()
    if analysis is None:
        analysis = create_opportunity_requirement_analysis(
            opportunity,
            created_by=sales_user,
            llm_provider=provider,
        )
    if analysis.created_by_id != sales_user.pk:
        raise DemoDatasetError("Demo requirement analysis fixture conflict.")
    if analysis.analysis_version == "v1":
        expected = _parse_analysis(json.dumps(provider.legacy_snapshot_payload()))
    else:
        expected = _parse_generated_analysis(provider.generate_json(()).content)
    if (
        analysis_record_to_domain(analysis) != expected
        or analysis.source_raw_requirement != opportunity.raw_requirement
    ):
        raise DemoDatasetError("Demo requirement analysis fixture conflict.")
    return analysis


def _ensure_knowledge(admin_user):
    embedding_provider = DemoEmbeddingProvider()
    documents = {}
    all_facts = []
    for fixture in DEMO_KNOWLEDGE:
        expected_hash = hashlib.sha256(fixture.content.encode("utf-8")).hexdigest()
        matches = KnowledgeDocument.objects.filter(title=fixture.title)
        if matches.count() > 1:
            raise DemoDatasetError("Demo knowledge fixture conflict.")
        document = matches.first()
        if document is None:
            source = ContentFile(fixture.content.encode("utf-8"), name=fixture.filename)
            validated = validate_document_file(source, fixture.filename)
            source.seek(0)
            document = KnowledgeDocument.objects.create(
                title=fixture.title,
                document_type=fixture.document_type,
                source_file=source,
                original_filename=validated.original_filename,
                mime_type=validated.mime_type,
                file_size=len(validated.data),
                checksum_sha256=hashlib.sha256(validated.data).hexdigest(),
                created_by=admin_user,
            )
        base_expected = (
            fixture.document_type,
            fixture.filename,
            "text/plain",
            len(fixture.content.encode("utf-8")),
            expected_hash,
            admin_user.pk,
        )
        base_actual = (
            document.document_type,
            document.original_filename,
            document.mime_type,
            document.file_size,
            document.checksum_sha256,
            document.created_by_id,
        )
        if base_actual != base_expected:
            raise DemoDatasetError("Demo knowledge fixture conflict.")
        if document.status == KnowledgeDocumentStatus.PENDING:
            if document.grounding_facts.exists() or document.chunks.exists():
                raise DemoDatasetError("Demo knowledge fixture conflict.")
            document = index_document(document.pk, provider=embedding_provider)
        if document.status != KnowledgeDocumentStatus.READY:
            raise DemoDatasetError("Demo knowledge fixture conflict.")
        facts = tuple(document.grounding_facts.order_by("subject_key", "pk"))
        if not facts:
            proposed = extract_grounding_facts(
                document.pk,
                llm_provider=DemoGroundingExtractionProvider(fixture),
            )
            approve_grounding_facts([fact.pk for fact in proposed], actor=admin_user)
            facts = tuple(document.grounding_facts.order_by("subject_key", "pk"))
        expected_index = (
            KnowledgeDocumentStatus.READY,
            embedding_provider.provider_name,
            embedding_provider.model_name,
            embedding_provider.dimensions,
        )
        actual_index = (
            document.status,
            document.embedding_provider,
            document.embedding_model,
            document.embedding_dimensions,
        )
        if actual_index != expected_index:
            raise DemoDatasetError("Demo knowledge fixture conflict.")
        expected_facts = set(fixture.facts)
        if {
            (fact.subject_key, fact.statement) for fact in facts
        } != expected_facts or len(facts) != len(expected_facts):
            raise DemoDatasetError("Demo grounding Fact fixture conflict.")
        if facts and all(
            fact.approval_status == EnterpriseGroundingFactApprovalStatus.PROPOSED
            and not fact.is_stale
            for fact in facts
        ):
            approve_grounding_facts([fact.pk for fact in facts], actor=admin_user)
            facts = tuple(document.grounding_facts.order_by("subject_key", "pk"))
        if any(
            fact.status != EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED
            or fact.approval_status != EnterpriseGroundingFactApprovalStatus.APPROVED
            or fact.approved_by_id != admin_user.pk
            or fact.is_stale
            or fact.source_index_run_id != document.last_index_run_id
            for fact in facts
        ):
            raise DemoDatasetError("Demo grounding Fact fixture conflict.")
        documents[fixture.key] = document
        all_facts.extend(facts)
    return documents, tuple(all_facts)


def _validate_solution(solution, scenario, opportunity, analysis, users) -> None:
    if (
        solution.generation_idempotency_key != demo_workflow_id(scenario.key)
        or solution.opportunity_id != opportunity.pk
        or solution.requirement_analysis_id != analysis.pk
        or solution.created_by_id != users[scenario.sales_key].pk
        or solution.schema_version != 2
        or solution.version != 1
    ):
        raise DemoDatasetError("Demo Solution fixture conflict.")


def _ensure_workflow(graph, scenario, solution, analysis, users) -> None:
    workflow_id = demo_workflow_id(scenario.key)
    config = {"configurable": {"thread_id": str(workflow_id)}}
    snapshot = graph.get_state(config)
    if not snapshot.values:
        graph.update_state(
            config,
            {
                "workflow_run_id": str(workflow_id),
                "opportunity_id": solution.opportunity_id,
                "requirement_analysis_id": analysis.pk,
                "requested_by_id": users[scenario.sales_key].pk,
                "solution_draft_id": solution.pk,
                "solution_version": solution.version,
                "workflow_stage": "waiting_for_sales_confirmation",
                "workflow_outcome": "waiting_for_sales_confirmation",
                "error_code": "",
            },
            as_node="generate_solution",
        )
        graph.invoke(None, config)
        snapshot = graph.get_state(config)
    _validate_checkpoint_identity(snapshot.values, scenario, solution, analysis, users)

    target = _TARGETS[scenario.key]
    if target != "waiting_for_sales_confirmation" and solution.review_status == SolutionReviewStatus.DRAFT:
        graph.invoke(
            Command(
                resume={
                    "actor_id": users[scenario.sales_key].pk,
                    "action": SolutionHumanAction.SUBMIT_FOR_REVIEW.value,
                }
            ),
            config,
        )
        solution.refresh_from_db()

    if target == "approved" and solution.review_status == SolutionReviewStatus.PENDING_REVIEW:
        graph.invoke(
            Command(
                resume={
                    "actor_id": users[scenario.presales_key].pk,
                    "action": SolutionHumanAction.APPROVE.value,
                }
            ),
            config,
        )
        solution.refresh_from_db()
    elif target in {"customer_info_required", "technical_revision_required"} and solution.review_status == SolutionReviewStatus.PENDING_REVIEW:
        reason = (
            SolutionReturnReason.CUSTOMER_INFO_REQUIRED
            if target == "customer_info_required"
            else SolutionReturnReason.TECHNICAL_REVISION_REQUIRED
        )
        graph.invoke(
            Command(
                resume={
                    "actor_id": users[scenario.presales_key].pk,
                    "action": SolutionHumanAction.REQUEST_REVISION.value,
                    "return_reason": reason,
                    "comment": _RETURN_COMMENTS[scenario.key],
                }
            ),
            config,
        )
        solution.refresh_from_db()
    _validate_workflow_target(graph.get_state(config).values, scenario, solution, users)


def _validate_checkpoint_identity(values, scenario, solution, analysis, users):
    expected = {
        "workflow_run_id": str(demo_workflow_id(scenario.key)),
        "opportunity_id": solution.opportunity_id,
        "requirement_analysis_id": analysis.pk,
        "requested_by_id": users[scenario.sales_key].pk,
        "solution_draft_id": solution.pk,
        "solution_version": solution.version,
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise DemoDatasetError("Demo workflow checkpoint conflict.")


def _validate_workflow_target(values, scenario, solution, users):
    target = _TARGETS[scenario.key]
    if values.get("workflow_outcome") != target:
        raise DemoDatasetError("Demo workflow checkpoint conflict.")
    reviews = tuple(solution.reviews.order_by("submitted_at", "pk"))
    if target == "waiting_for_sales_confirmation":
        valid = solution.review_status == SolutionReviewStatus.DRAFT and not reviews
    elif target == "waiting_for_presales_review":
        valid = (
            solution.review_status == SolutionReviewStatus.PENDING_REVIEW
            and len(reviews) == 1
            and reviews[0].status == SolutionReviewDecisionStatus.PENDING
        )
    elif target == "approved":
        valid = (
            solution.review_status == SolutionReviewStatus.APPROVED
            and len(reviews) == 1
            and reviews[0].status == SolutionReviewDecisionStatus.APPROVED
        )
    else:
        expected_reason = (
            SolutionReturnReason.CUSTOMER_INFO_REQUIRED
            if target == "customer_info_required"
            else SolutionReturnReason.TECHNICAL_REVISION_REQUIRED
        )
        valid = (
            solution.review_status == SolutionReviewStatus.NEEDS_REVISION
            and len(reviews) == 1
            and reviews[0].status == SolutionReviewDecisionStatus.RETURNED
            and reviews[0].return_reason == expected_reason
            and reviews[0].comment == _RETURN_COMMENTS[scenario.key]
        )
    if reviews and (
        reviews[0].submitted_by_id != users[scenario.sales_key].pk
        or reviews[0].reviewer_id != users[scenario.presales_key].pk
    ):
        valid = False
    if not valid:
        raise DemoDatasetError("Demo review fixture conflict.")


def _collect_demo_graph(*, require_complete: bool = False) -> _DemoGraph:
    _preflight_user_identities()
    user_model = get_user_model()
    users = {
        fixture.key: user
        for fixture in DEMO_IDENTITIES
        if (user := user_model.objects.filter(username=fixture.username).first()) is not None
    }
    identity_by_key = {item.key: item for item in DEMO_IDENTITIES}
    for key, user in users.items():
        _validate_user(user, identity_by_key[key])

    customers = {}
    opportunities = {}
    analyses = {}
    solutions = {}
    reviews = {}
    scenario_by_key = {item.key: item for item in DEMO_SCENARIOS}
    for scenario in DEMO_SCENARIOS:
        customer_rows = Customer.objects.filter(name=scenario.customer_name)
        if customer_rows.count() > 1:
            raise DemoDatasetError("Demo customer fixture conflict.")
        customer = customer_rows.first()
        if customer is not None:
            expected_owner = users.get(scenario.sales_key)
            if expected_owner is None or customer.created_by_id != expected_owner.pk:
                raise DemoDatasetError("Demo customer fixture conflict.")
            customers[scenario.key] = customer

        opportunity_rows = Opportunity.objects.filter(project_name=scenario.project_name)
        if opportunity_rows.count() > 1:
            raise DemoDatasetError("Demo opportunity fixture conflict.")
        opportunity = opportunity_rows.first()
        if opportunity is not None:
            sales = users.get(scenario.sales_key)
            presales = users.get(scenario.presales_key)
            if (
                customer is None
                or sales is None
                or presales is None
                or opportunity.customer_id != customer.pk
                or opportunity.sales_owner_id != sales.pk
                or opportunity.presales_owner_id != presales.pk
                or opportunity.created_by_id != sales.pk
            ):
                raise DemoDatasetError("Demo opportunity fixture conflict.")
            opportunities[scenario.key] = opportunity

        provider = DemoRequirementAnalysisProvider(scenario)
        analysis_rows = OpportunityRequirementAnalysis.objects.filter(
            opportunity=opportunity,
            llm_provider=provider.provider_name,
            llm_model=provider.model_name,
        ) if opportunity is not None else OpportunityRequirementAnalysis.objects.none()
        if analysis_rows.count() > 1:
            raise DemoDatasetError("Demo requirement analysis fixture conflict.")
        analysis = analysis_rows.first()
        if analysis is not None:
            analyses[scenario.key] = analysis

        solution_rows = SolutionDraftRecord.objects.filter(
            generation_idempotency_key=demo_workflow_id(scenario.key)
        )
        if solution_rows.count() > 1:
            raise DemoDatasetError("Demo Solution fixture conflict.")
        solution = solution_rows.first()
        if solution is not None:
            if opportunity is None or analysis is None:
                raise DemoDatasetError("Demo Solution fixture conflict.")
            solutions[scenario.key] = solution
            solution_reviews = tuple(solution.reviews.order_by("pk"))
            if len(solution_reviews) > 1:
                raise DemoDatasetError("Demo review fixture conflict.")
            if solution_reviews:
                reviews[scenario.key] = solution_reviews[0]

    documents = {}
    facts = []
    knowledge_by_key = {item.key: item for item in DEMO_KNOWLEDGE}
    for fixture in DEMO_KNOWLEDGE:
        rows = KnowledgeDocument.objects.filter(title=fixture.title)
        if rows.count() > 1:
            raise DemoDatasetError("Demo knowledge fixture conflict.")
        document = rows.first()
        if document is not None:
            admin = users.get("admin")
            if admin is None or document.created_by_id != admin.pk:
                raise DemoDatasetError("Demo knowledge fixture conflict.")
            documents[fixture.key] = document
            document_facts = tuple(document.grounding_facts.order_by("pk"))
            identities = {
                (item.subject_key, item.statement) for item in document_facts
            }
            if identities and identities != set(knowledge_by_key[fixture.key].facts):
                raise DemoDatasetError("Demo grounding Fact fixture conflict.")
            facts.extend(document_facts)

    provenance = tuple(
        SolutionDraftProvenance.objects.filter(
            solution_draft_id__in=[item.pk for item in solutions.values()]
        )
    )
    graph = _DemoGraph(
        users,
        customers,
        opportunities,
        analyses,
        solutions,
        reviews,
        documents,
        tuple(facts),
        provenance,
    )
    if require_complete and any(
        len(items) != expected
        for items, expected in (
            (users, len(DEMO_IDENTITIES)),
            (customers, len(DEMO_SCENARIOS)),
            (opportunities, len(DEMO_SCENARIOS)),
            (analyses, len(DEMO_SCENARIOS)),
            (solutions, len(DEMO_SCENARIOS)),
            (documents, len(DEMO_KNOWLEDGE)),
            (facts, sum(len(item.facts) for item in DEMO_KNOWLEDGE)),
        )
    ):
        raise DemoDatasetError("Demo dataset is incomplete.")
    return graph


def _validate_no_external_references(graph: _DemoGraph) -> None:
    user_ids = {item.pk for item in graph.users.values()}
    customer_ids = {item.pk for item in graph.customers.values()}
    opportunity_ids = {item.pk for item in graph.opportunities.values()}
    analysis_ids = {item.pk for item in graph.analyses.values()}
    solution_ids = {item.pk for item in graph.solutions.values()}
    review_ids = {item.pk for item in graph.reviews.values()}
    document_ids = {item.pk for item in graph.documents.values()}
    fact_ids = {item.pk for item in graph.facts}
    provenance_ids = {item.pk for item in graph.provenance}

    conflicts = (
        Customer.objects.filter(created_by_id__in=user_ids).exclude(pk__in=customer_ids).exists()
        or Opportunity.objects.filter(
            models.Q(customer_id__in=customer_ids)
            | models.Q(sales_owner_id__in=user_ids)
            | models.Q(presales_owner_id__in=user_ids)
            | models.Q(created_by_id__in=user_ids)
        ).exclude(pk__in=opportunity_ids).exists()
        or OpportunityRequirementAnalysis.objects.filter(
            models.Q(opportunity_id__in=opportunity_ids)
            | models.Q(created_by_id__in=user_ids)
        ).exclude(pk__in=analysis_ids).exists()
        or SolutionDraftRecord.objects.filter(
            models.Q(opportunity_id__in=opportunity_ids)
            | models.Q(requirement_analysis_id__in=analysis_ids)
            | models.Q(created_by_id__in=user_ids)
        ).exclude(pk__in=solution_ids).exists()
        or SolutionReview.objects.filter(
            models.Q(solution_draft_id__in=solution_ids)
            | models.Q(submitted_by_id__in=user_ids)
            | models.Q(reviewer_id__in=user_ids)
        ).exclude(pk__in=review_ids).exists()
        or KnowledgeDocument.objects.filter(created_by_id__in=user_ids).exclude(
            pk__in=document_ids
        ).exists()
        or EnterpriseGroundingFact.objects.filter(
            models.Q(source_document_id__in=document_ids)
            | models.Q(approved_by_id__in=user_ids)
        ).exclude(pk__in=fact_ids).exists()
        or SolutionDraftProvenance.objects.filter(
            models.Q(source_document_id__in=document_ids)
            | models.Q(enterprise_grounding_fact_id__in=fact_ids)
        ).exclude(pk__in=provenance_ids).exists()
    )
    if conflicts:
        raise DemoDatasetError(
            "Demo-owned data is referenced by non-demo business data; cleanup refused."
        )
    if SolutionDraftProvenance.objects.filter(pk__in=provenance_ids).exclude(
        source_document_id__in=document_ids,
        enterprise_grounding_fact_id__in=fact_ids,
    ).exists():
        raise DemoDatasetError("Demo provenance ownership conflict.")
