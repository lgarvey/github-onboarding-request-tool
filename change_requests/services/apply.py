"""Turning a change request into an edit of the terraform-github YAML."""

from django.utils.text import slugify

from catalogue.services import terraform_writer
from catalogue.services.terraform_writer import ConfigError, Edit
from change_requests.choices import Action, Operation, PrincipalType, TargetType

__all__ = ["ConfigError", "apply", "build_edit"]


def _changes(items, principal_type) -> dict[str, str | None]:
    return {
        item.principal_name: None if item.operation == Operation.REMOVE else item.new_permission
        for item in items
        if item.principal_type == principal_type
    }


def build_edit(change_request) -> Edit:
    """Work out the YAML edit for a request, without saving it. Raises ConfigError."""
    org, name = change_request.organisation, change_request.target_name
    details = change_request.details
    items = list(change_request.items.all())
    teams = _changes(items, PrincipalType.TEAM)
    users = _changes(items, PrincipalType.USER)

    if change_request.target_type == TargetType.TEAM:
        if change_request.action == Action.CREATE:
            return terraform_writer.create_team(
                org,
                name,
                details.get("slug") or slugify(name),
                description=details.get("description", ""),
                parent_team_id=details.get("parent_team_id"),
                members=users,
            )
        return terraform_writer.modify_team(org, name, members=users)

    if change_request.action == Action.CREATE:
        return terraform_writer.create_repository(
            org,
            name,
            description=details.get("description", ""),
            team_permissions=teams,
            user_permissions=users,
        )
    if change_request.action == Action.ARCHIVE:
        return terraform_writer.modify_repository(org, name, archived=True)
    return terraform_writer.modify_repository(
        org, name, team_permissions=teams, user_permissions=users
    )


def apply(change_request) -> Edit:
    """Write a request's change into the YAML and record that it was applied."""
    edit = build_edit(change_request)
    edit.write()
    change_request.mark_applied(edit.diff())
    return edit
