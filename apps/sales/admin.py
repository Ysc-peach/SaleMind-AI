"""Admin for governed commercial reference data.

The sales domain exposes its operations through the API, but a price edit is a
rare, deliberate commercial act. Keeping it in the same admin where knowledge
documents and grounding facts are governed means one place to look, and one
audit trail (admin log) for "who changed this number".
"""

from django.contrib import admin

from .models import PriceBookEntry


@admin.register(PriceBookEntry)
class PriceBookEntryAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "name",
        "unit",
        "unit_price",
        "currency",
        "effective_from",
        "is_active",
    )
    list_filter = ("is_active", "currency", "category")
    search_fields = ("sku", "name", "category")
    ordering = ("sku", "-effective_from")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        # Quotes reference these rows. A wrong price is corrected by adding a
        # newer row (or clearing 启用), never by deleting what a quote was built
        # on.
        return False

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
