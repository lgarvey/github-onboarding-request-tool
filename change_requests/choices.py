from django.db import models


class TargetType(models.TextChoices):
    REPOSITORY = "repository", "Repository"
    TEAM = "team", "Team"


class Action(models.TextChoices):
    CREATE = "create", "Create"
    MODIFY = "modify", "Modify"
    ARCHIVE = "archive", "Archive"


class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"


class Operation(models.TextChoices):
    ADD = "add", "Add"
    REMOVE = "remove", "Remove"
    CHANGE = "change", "Change"


class PrincipalType(models.TextChoices):
    TEAM = "team", "Team"
    USER = "user", "User"
