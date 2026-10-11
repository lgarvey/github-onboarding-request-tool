from django.contrib import admin

from catalogue.models import Organisation


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "directory")
    search_fields = ("name", "directory")
