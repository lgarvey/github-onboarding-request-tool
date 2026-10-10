from django.contrib import admin

from portfolios.models import Approver, Portfolio


class ApproverInline(admin.TabularInline):
    model = Approver
    extra = 1
    autocomplete_fields = ["user"]


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)
    inlines = [ApproverInline]


@admin.register(Approver)
class ApproverAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "portfolio", "user")
    list_filter = ("portfolio",)
    search_fields = ("name", "email", "user__email_user_id", "user__email")
    autocomplete_fields = ["user"]
