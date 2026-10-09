"""The authbroker_client URLs, exempted from LoginRequiredMiddleware.

The package's own urlconf can't be included directly because its views would be
intercepted by the middleware before the user can sign in.
"""

from authbroker_client.views import AuthCallbackView, AuthView
from django.contrib.auth.decorators import login_not_required
from django.urls import path

app_name = "authbroker_client"

urlpatterns = [
    path("login/", login_not_required(AuthView.as_view()), name="login"),
    path("callback/", login_not_required(AuthCallbackView.as_view()), name="callback"),
]
