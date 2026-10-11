from django.contrib import admin
from django.utils.html import format_html

from change_requests.models import ChangeItem, ChangeRequest


class ChangeItemInline(admin.TabularInline):
    model = ChangeItem
    fields = ("summary",)
    readonly_fields = ("summary",)
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    """An overview of every request. Read-only: requests change through the app's own pages."""

    list_display = (
        "id",
        "status",
        "organisation",
        "target_type",
        "target_name",
        "action",
        "portfolio",
        "requested_by",
        "submitted_at",
        "decided_by",
        "decided_at",
        "applied_at",
    )
    list_display_links = ("id", "target_name")
    list_filter = ("status", "action", "target_type", "organisation", "portfolio")
    search_fields = (
        "target_name",
        "organisation",
        "requested_by__email",
        "requested_by__email_user_id",
        "decided_by__email",
        "items__principal_name",
    )
    date_hierarchy = "created_at"
    list_select_related = ("portfolio", "requested_by", "decided_by")
    inlines = [ChangeItemInline]
    fieldsets = (
        (None, {"fields": ("status", "organisation", "target_type", "target_name", "action")}),
        ("Request", {"fields": ("requested_by", "portfolio", "details", "created_at")}),
        (
            "Decision",
            {"fields": ("submitted_at", "decided_by", "decided_at", "decision_comment")},
        ),
        ("Applied to YAML", {"fields": ("applied_at", "diff")}),
    )
    readonly_fields = ("diff",)

    @admin.display(description="Applied diff")
    def diff(self, obj):
        return format_html("<pre>{}</pre>", obj.applied_diff) if obj.applied_diff else "-"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
