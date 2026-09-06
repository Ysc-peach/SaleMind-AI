"""URL routes for Customer APIs."""

from django.urls import path

from .views import CustomerViewSet, OpportunityViewSet
from .requirement_analysis_views import RequirementAnalysisViewSet
from .solution_draft_views import (
    SolutionDraftCollectionViewSet,
    SolutionDraftDetailViewSet,
)


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


urlpatterns = [
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
