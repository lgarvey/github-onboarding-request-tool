from django.conf import settings
from django.db import models

from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType


class ChangeRequest(models.Model):
    """A requested change to exactly one repository or team in one organisation."""

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="change_requests"
    )
    organisation = models.CharField(max_length=255)
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_name = models.CharField(max_length=255)
    action = models.CharField(max_length=20, choices=Action.choices)
    portfolio = models.ForeignKey(
        "portfolios.Portfolio", on_delete=models.PROTECT, related_name="change_requests"
    )
    # Create-time metadata, such as `description` and `parent_team`.
    details = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()} {self.target_type} {self.target_name}"

    def heading(self):
        target = f"{self.target_name} (org: {self.organisation})"
        if self.action == Action.CREATE:
            return f"New {self.target_type}: {target}"
        if self.action == Action.ARCHIVE:
            return f"Archive {self.target_type}: {target}"
        return f"{self.get_target_type_display()}: {target}"

    def summary_lines(self):
        """Human-readable description of the request, one line per list entry."""
        lines = [self.heading()]
        if self.details.get("description"):
            lines.append(f"  Description: {self.details['description']}")
        if self.details.get("parent_team"):
            lines.append(f"  Parent team: {self.details['parent_team']}")
        lines.extend(f"  {item.summary()}" for item in self.items.all())
        lines.append(f"Portfolio: {self.portfolio.name}")
        return lines


class ChangeItem(models.Model):
    """One difference from the current YAML: a principal gaining, losing or changing access."""

    change_request = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="items"
    )
    operation = models.CharField(max_length=20, choices=Operation.choices)
    principal_type = models.CharField(max_length=20, choices=PrincipalType.choices)
    # A team slug or a GitHub username.
    principal_name = models.CharField(max_length=255)
    # A catalogue.choices.RepositoryPermission or TeamRole value. Null means "no access".
    old_permission = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001
    new_permission = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.summary()

    def summary(self):
        principal = f"{self.principal_type} {self.principal_name}"
        if self.operation == Operation.ADD:
            # Team members hold a role; repository collaborators hold a permission.
            joiner = "as" if self.change_request.target_type == TargetType.TEAM else "with"
            return f"Add {principal} {joiner} {self.new_permission}"
        if self.operation == Operation.CHANGE:
            return f"Change {principal}: {self.old_permission} → {self.new_permission}"
        return f"Remove {principal}"
