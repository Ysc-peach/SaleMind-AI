"""URL routes for Customer APIs."""

from django.urls import path

from .views import CustomerViewSet, OpportunityViewSet
from .requirement_analysis_views import RequirementAnalysisViewSet
from .solution_draft_views import (
    SolutionDraftCollectionViewSet,
    SolutionDraftDetailViewSet,
)
from .solution_workflow_views import (
    SolutionWorkflowCollectionViewSet,
    SolutionWorkflowDetailViewSet,
)
from .audit_views import AuditEventsAPIView
from .workspace_views import (
    ReviewSummaryAPIView,
    ReviewerInboxAPIView,
    SalesWorkspaceAPIView,
)
from .solution_export_views import SolutionExportAPIView
from .follow_up_views import (
    FollowUpTaskViewSet,
    MyFollowUpAPIView,
    OpportunityFollowUpViewSet,
)
from .case_study_views import CaseStudyMatchAPIView, CaseStudyViewSet
from .competitor_views import (
    CompetitorMatrixAPIView,
    CompetitorStatementDecisionViewSet,
    CompetitorStatementViewSet,
    CompetitorViewSet,
)
from .price_book_views import PriceBookAPIView
from .quote_views import OpportunityQuoteViewSet, QuoteLineViewSet


customer_create_view = CustomerViewSet.as_view({"post": "create"})
customer_detail_view = CustomerViewSet.as_view({
    "get": "retrieve",
    "patch": "partial_update",
})
customer_search_view = CustomerViewSet.as_view({"get": "search"})
customer_disable_view = CustomerViewSet.as_view({"post": "disable"})
customer_enable_view = CustomerViewSet.as_view({"post": "enable"})
opportunity_collection_view = OpportunityViewSet.as_view(
    {"get": "list", "post": "create"}
)
opportunity_detail_view = OpportunityViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update"}
)
opportunity_disable_view = OpportunityViewSet.as_view({"post": "disable"})
opportunity_enable_view = OpportunityViewSet.as_view({"post": "enable"})
opportunity_follow_up_view = OpportunityFollowUpViewSet.as_view(
    {"get": "list_tasks", "post": "create_task"}
)
follow_up_detail_view = FollowUpTaskViewSet.as_view({"patch": "partial_update"})
follow_up_complete_view = FollowUpTaskViewSet.as_view({"post": "complete"})
follow_up_reopen_view = FollowUpTaskViewSet.as_view({"post": "reopen"})
my_follow_up_view = MyFollowUpAPIView.as_view()
case_study_collection_view = CaseStudyViewSet.as_view(
    {"get": "list_cases", "post": "create_case"}
)
case_study_detail_view = CaseStudyViewSet.as_view({"patch": "partial_update"})
case_study_archive_view = CaseStudyViewSet.as_view({"post": "archive"})
case_study_restore_view = CaseStudyViewSet.as_view({"post": "restore"})
case_study_match_view = CaseStudyMatchAPIView.as_view()
competitor_collection_view = CompetitorViewSet.as_view(
    {"get": "list_competitors", "post": "create_competitor"}
)
competitor_detail_view = CompetitorViewSet.as_view({"patch": "partial_update"})
competitor_archive_view = CompetitorViewSet.as_view({"post": "archive"})
competitor_restore_view = CompetitorViewSet.as_view({"post": "restore"})
competitor_statement_view = CompetitorStatementViewSet.as_view(
    {"get": "list_statements", "post": "create_statement"}
)
competitor_statement_approve_view = CompetitorStatementDecisionViewSet.as_view(
    {"post": "approve"}
)
competitor_statement_reject_view = CompetitorStatementDecisionViewSet.as_view(
    {"post": "reject"}
)
competitor_matrix_view = CompetitorMatrixAPIView.as_view()
price_book_view = PriceBookAPIView.as_view()
opportunity_quote_view = OpportunityQuoteViewSet.as_view(
    {"get": "retrieve_quote", "patch": "update_quote"}
)
opportunity_quote_lines_view = OpportunityQuoteViewSet.as_view(
    {"post": "add_line"}
)
opportunity_quote_rebind_view = OpportunityQuoteViewSet.as_view(
    {"post": "rebind"}
)
opportunity_quote_discount_approve_view = OpportunityQuoteViewSet.as_view(
    {"post": "approve_discount"}
)
opportunity_quote_discount_reject_view = OpportunityQuoteViewSet.as_view(
    {"post": "reject_discount"}
)
quote_line_detail_view = QuoteLineViewSet.as_view({"patch": "partial_update"})
quote_line_remove_view = QuoteLineViewSet.as_view({"post": "remove"})
solution_draft_collection_view = SolutionDraftCollectionViewSet.as_view(
    {"get": "list_drafts", "post": "create_draft"}
)
solution_draft_detail_view = SolutionDraftDetailViewSet.as_view(
    {"get": "retrieve_draft"}
)
solution_draft_submit_view = SolutionDraftDetailViewSet.as_view(
    {"post": "submit_review"}
)
solution_draft_approve_view = SolutionDraftDetailViewSet.as_view(
    {"post": "approve_review"}
)
solution_draft_request_revision_view = SolutionDraftDetailViewSet.as_view(
    {"post": "request_revision"}
)
solution_draft_review_list_view = SolutionDraftDetailViewSet.as_view(
    {"get": "review_history"}
)
solution_workflow_start_view = SolutionWorkflowCollectionViewSet.as_view(
    {"post": "start"}
)
solution_workflow_detail_view = SolutionWorkflowDetailViewSet.as_view(
    {"get": "retrieve_workflow"}
)
solution_workflow_resume_view = SolutionWorkflowDetailViewSet.as_view(
    {"post": "resume"}
)


urlpatterns = [
    path('solution-drafts/<int:solution_id>/export/', SolutionExportAPIView.as_view(), name='solution-draft-export'),
    path(
        "workspaces/sales/",
        SalesWorkspaceAPIView.as_view(),
        name="sales-workspace",
    ),
    path(
        "reviews/inbox/",
        ReviewerInboxAPIView.as_view(),
        name="reviewer-inbox",
    ),
    path(
        "reviews/summary/",
        ReviewSummaryAPIView.as_view(),
        name="review-summary",
    ),
    path(
        "audit/events/",
        AuditEventsAPIView.as_view(),
        name="audit-events",
    ),
    path(
        "opportunities/<int:opportunity_id>/solution-workflows/",
        solution_workflow_start_view,
        name="solution-workflow-start",
    ),
    path(
        "solution-workflows/<uuid:workflow_id>/resume/",
        solution_workflow_resume_view,
        name="solution-workflow-resume",
    ),
    path(
        "solution-workflows/<uuid:workflow_id>/",
        solution_workflow_detail_view,
        name="solution-workflow-detail",
    ),
    path(
        "solution-drafts/<int:solution_id>/submit/",
        solution_draft_submit_view,
        name="solution-draft-submit",
    ),
    path(
        "solution-drafts/<int:solution_id>/approve/",
        solution_draft_approve_view,
        name="solution-draft-approve",
    ),
    path(
        "solution-drafts/<int:solution_id>/request-revision/",
        solution_draft_request_revision_view,
        name="solution-draft-request-revision",
    ),
    path(
        "solution-drafts/<int:solution_id>/reviews/",
        solution_draft_review_list_view,
        name="solution-draft-review-list",
    ),
    path(
        "opportunities/<int:opportunity_id>/solution-drafts/",
        solution_draft_collection_view,
        name="solution-draft-list",
    ),
    path(
        "solution-drafts/<int:solution_id>/",
        solution_draft_detail_view,
        name="solution-draft-detail",
    ),
    path(
        "opportunities/<int:opportunity_id>/ai/requirement-analyses/",
        RequirementAnalysisViewSet.as_view({"post": "analyze", "get": "history"}),
        name="opportunity-requirement-analysis-list",
    ),
    path(
        "opportunities/<int:opportunity_id>/ai/requirement-analyses/latest/",
        RequirementAnalysisViewSet.as_view({"get": "latest"}),
        name="opportunity-requirement-analysis-latest",
    ),
    path(
        "opportunities/<int:opportunity_id>/ai/requirement-analyses/<int:analysis_id>/",
        RequirementAnalysisViewSet.as_view({"get": "retrieve_analysis"}),
        name="opportunity-requirement-analysis-detail",
    ),
    path("customers/search/", customer_search_view, name="customer-search"),
    path("customers/<int:pk>/", customer_detail_view, name="customer-detail"),
    path(
        "customers/<int:pk>/disable/",
        customer_disable_view,
        name="customer-disable",
    ),
    path("customers/<int:pk>/enable/", customer_enable_view, name="customer-enable"),
    path("customers/", customer_create_view, name="customer-create"),
    path(
        "opportunities/<int:opportunity_id>/follow-ups/",
        opportunity_follow_up_view,
        name="opportunity-follow-up-list",
    ),
    path("follow-ups/mine/", my_follow_up_view, name="follow-up-mine"),
    path(
        "case-studies/",
        case_study_collection_view,
        name="case-study-list",
    ),
    path(
        "case-studies/match/",
        case_study_match_view,
        name="case-study-match",
    ),
    path(
        "price-book/",
        price_book_view,
        name="price-book",
    ),
    path(
        "opportunities/<int:opportunity_id>/quote/",
        opportunity_quote_view,
        name="opportunity-quote",
    ),
    path(
        "opportunities/<int:opportunity_id>/quote/lines/",
        opportunity_quote_lines_view,
        name="opportunity-quote-lines",
    ),
    path(
        "opportunities/<int:opportunity_id>/quote/rebind/",
        opportunity_quote_rebind_view,
        name="opportunity-quote-rebind",
    ),
    path(
        "opportunities/<int:opportunity_id>/quote/discount-approval/",
        opportunity_quote_discount_approve_view,
        name="opportunity-quote-discount-approve",
    ),
    path(
        "opportunities/<int:opportunity_id>/quote/discount-rejection/",
        opportunity_quote_discount_reject_view,
        name="opportunity-quote-discount-reject",
    ),
    path(
        "quote-lines/<int:pk>/",
        quote_line_detail_view,
        name="quote-line-detail",
    ),
    path(
        "quote-lines/<int:pk>/remove/",
        quote_line_remove_view,
        name="quote-line-remove",
    ),
    path(
        "opportunities/<int:opportunity_id>/competitor-matrix/",
        competitor_matrix_view,
        name="opportunity-competitor-matrix",
    ),
    path(
        "competitors/",
        competitor_collection_view,
        name="competitor-list",
    ),
    path(
        "competitors/<int:pk>/",
        competitor_detail_view,
        name="competitor-detail",
    ),
    path(
        "competitors/<int:pk>/archive/",
        competitor_archive_view,
        name="competitor-archive",
    ),
    path(
        "competitors/<int:pk>/restore/",
        competitor_restore_view,
        name="competitor-restore",
    ),
    path(
        "competitors/<int:competitor_id>/statements/",
        competitor_statement_view,
        name="competitor-statement-list",
    ),
    path(
        "competitor-statements/<int:pk>/approve/",
        competitor_statement_approve_view,
        name="competitor-statement-approve",
    ),
    path(
        "competitor-statements/<int:pk>/reject/",
        competitor_statement_reject_view,
        name="competitor-statement-reject",
    ),
    path(
        "case-studies/<int:pk>/",
        case_study_detail_view,
        name="case-study-detail",
    ),
    path(
        "case-studies/<int:pk>/archive/",
        case_study_archive_view,
        name="case-study-archive",
    ),
    path(
        "case-studies/<int:pk>/restore/",
        case_study_restore_view,
        name="case-study-restore",
    ),
    path("follow-ups/<int:pk>/", follow_up_detail_view, name="follow-up-detail"),
    path(
        "follow-ups/<int:pk>/complete/",
        follow_up_complete_view,
        name="follow-up-complete",
    ),
    path(
        "follow-ups/<int:pk>/reopen/",
        follow_up_reopen_view,
        name="follow-up-reopen",
    ),
    path("opportunities/<int:pk>/", opportunity_detail_view, name="opportunity-detail"),
    path(
        "opportunities/<int:pk>/disable/",
        opportunity_disable_view,
        name="opportunity-disable",
    ),
    path(
        "opportunities/<int:pk>/enable/",
        opportunity_enable_view,
        name="opportunity-enable",
    ),
    path("opportunities/", opportunity_collection_view, name="opportunity-list"),
]
