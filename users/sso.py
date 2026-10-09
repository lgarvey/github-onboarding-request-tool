import waffle

DISABLE_SSO_SWITCH = "DISABLE_SSO"


def sso_enabled():
    """SSO is on unless the DISABLE_SSO switch exists and is active."""
    return not waffle.switch_is_active(DISABLE_SSO_SWITCH)
