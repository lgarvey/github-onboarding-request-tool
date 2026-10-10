from django.urls import path

from change_requests import views

urlpatterns = [
    path("orgs/<str:org>/repos/new/", views.repository_create, name="repository_create"),
    path("orgs/<str:org>/repos/<str:repo>/edit/", views.repository_edit, name="repository_edit"),
    path(
        "orgs/<str:org>/repos/<str:repo>/archive/",
        views.repository_archive,
        name="repository_archive",
    ),
    path("orgs/<str:org>/teams/new/", views.team_create, name="team_create"),
    path("orgs/<str:org>/teams/<str:slug>/edit/", views.team_edit, name="team_edit"),
    path(
        "requests/<int:pk>/confirm/",
        views.change_request_confirm,
        name="change_request_confirm",
    ),
]
