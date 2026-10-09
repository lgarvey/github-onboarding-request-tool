"""The project URLs plus an ordinary view, for exercising LoginRequiredMiddleware."""

from django.http import HttpResponse
from django.urls import include, path


def protected(request):
    return HttpResponse("protected")


urlpatterns = [
    path("protected/", protected),
    path("", include("config.urls")),
]
