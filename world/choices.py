from django.db import models


class SSOApplicationKind(models.TextChoices):
    SAML = "saml", "SAML"
    # OAuth applications have no permissions, only whether someone can sign in.
    OAUTH = "oauth", "OAuth"
