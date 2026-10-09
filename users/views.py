from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from users.sso import sso_enabled


@login_not_required
def login(request):
    """Send the user to Staff SSO, or to the admin login form when SSO is disabled."""
    target = reverse("authbroker_client:login" if sso_enabled() else "admin:login")
    next_url = request.GET.get(REDIRECT_FIELD_NAME)
    if next_url:
        target = f"{target}?{urlencode({REDIRECT_FIELD_NAME: next_url})}"
    return redirect(target)


@login_not_required
def admin_login(request):
    """Replace the admin login form with SSO unless SSO is disabled."""
    if not sso_enabled():
        return admin.site.login(request)

    next_url = request.GET.get(REDIRECT_FIELD_NAME, reverse("admin:index"))
    if request.user.is_authenticated:
        if not request.user.is_staff:
            # Already signed in through SSO; sending them round again would loop.
            raise PermissionDenied
        safe = url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})
        return redirect(next_url if safe else reverse("admin:index"))
    return redirect_to_login(next_url, settings.LOGIN_URL)
