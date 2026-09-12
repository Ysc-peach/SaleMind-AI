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
from .workspace_views import ReviewerInboxAPIView, SalesWorkspaceAPIView


customer_create_view = CustomerViewSet.as_view({"post": "create"})
customer_detail_view = CustomerViewSet.as_view({"get": "retrieve"})
customer_search_view = CustomerViewSet.as_view({"get": "search"})
opportunity_collection_view = OpportunityViewSet.as_view(
    {"get": "list", "post": "create"}
)
opportunity_detail_view = OpportunityViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update"}
)
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
    path("customers/", customer_create_view, name="customer-create"),
    path("opportunities/<int:pk>/", opportunity_detail_view, name="opportunity-detail"),
    path("opportunities/", opportunity_collection_view, name="opportunity-list"),
]
