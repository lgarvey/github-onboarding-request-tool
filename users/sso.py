from django.conf import settings


def sso_enabled():
    """SSO is on unless the DISABLE_SSO setting (from the environment) says otherwise."""
    return not settings.DISABLE_SSO
