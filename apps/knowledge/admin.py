"""Minimal Django Admin review surface for proposed grounding facts."""

from django.contrib import admin, messages

from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
from .admin_documents import KnowledgeDocumentAdmin
from apps.knowledge.services.grounding_fact_approval import (
    actor_can_review_grounding_facts,
    approve_grounding_facts,
    reject_grounding_facts,
)

admin.site.register(KnowledgeDocument, KnowledgeDocumentAdmin)


@admin.register(EnterpriseGroundingFact)
class EnterpriseGroundingFactAdmin(admin.ModelAdmin):
    list_display = (
        "subject_key",
        "status",
        "approval_status",
        "source_document",
        "is_stale",
        "created_at",
    )
    list_filter = ("status", "approval_status", "is_stale")
    search_fields = ("subject_key", "statement", "source_excerpt")
    ordering = ("-created_at",)
    readonly_fields = tuple(
        field.name for field in EnterpriseGroundingFact._meta.concrete_fields
    )
    actions = ("approve_selected_facts", "reject_selected_facts")

    def has_module_permission(self, request):
        return actor_can_review_grounding_facts(request.user)

    def has_view_permission(self, request, obj=None):
        return actor_can_review_grounding_facts(request.user)

    def has_change_permission(self, request, obj=None):
        return actor_can_review_grounding_facts(request.user)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="批准选中的 Grounding 事实")
    def approve_selected_facts(self, request, queryset):
        count = approve_grounding_facts(queryset.values_list("pk", flat=True), actor=request.user)
        self.message_user(request, f"已批准 {count} 条事实。", messages.SUCCESS)

    @admin.action(description="拒绝选中的 Grounding 事实")
    def reject_selected_facts(self, request, queryset):
        count = reject_grounding_facts(queryset.values_list("pk", flat=True), actor=request.user)
        self.message_user(request, f"已拒绝 {count} 条事实。", messages.SUCCESS)
