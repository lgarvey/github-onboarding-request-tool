from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email_user_id",)
    list_display = ("email_user_id", "email", "first_name", "last_name", "is_staff")
    search_fields = ("email_user_id", "email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email_user_id", "password")}),
        ("Personal info", {"fields": ("email", "first_name", "last_name")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email_user_id", "email", "usable_password", "password1", "password2"),
            },
        ),
    )
