"""Permission and role values, as allowed by the terraform-github schemas.

These are the only definitions; models, forms and services all import from here.
"""

from django.db import models


class RepositoryPermission(models.TextChoices):
    PULL = "pull", "Pull"
    TRIAGE = "triage", "Triage"
    PUSH = "push", "Push"
    MAINTAIN = "maintain", "Maintain"
    ADMIN = "admin", "Admin"


class TeamRole(models.TextChoices):
    MEMBER = "member", "Member"
    MAINTAINER = "maintainer", "Maintainer"
