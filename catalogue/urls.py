from django.urls import path

from catalogue import views

urlpatterns = [
    path("", views.organisation_list, name="organisation_list"),
    path("orgs/<str:org>/", views.organisation_detail, name="organisation_detail"),
]
