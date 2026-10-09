from django.db import transaction

from change_requests.choices import Operation, Status
from change_requests.models import ChangeItem, ChangeRequest
from change_requests.services.diff import ChangeItemData


def apply_items(current: dict[str, str], items, principal_type) -> dict[str, str]:
    """Return `current` with a draft's items for one principal type applied to it."""
    desired = dict(current)
    for item in items:
        if item.principal_type != principal_type:
            continue
        if item.operation == Operation.REMOVE:
            desired.pop(item.principal_name, None)
        else:
            desired[item.principal_name] = item.new_permission
    return desired


@transaction.atomic
def save_draft(
    *,
    requested_by,
    organisation,
    target_type,
    target_name,
    action,
    portfolio,
    items: list[ChangeItemData],
    details=None,
    draft: ChangeRequest | None = None,
) -> ChangeRequest:
    """Create a draft change request, or replace the contents of an existing draft."""
    change_request = draft or ChangeRequest(requested_by=requested_by)
    change_request.organisation = organisation
    change_request.target_type = target_type
    change_request.target_name = target_name
    change_request.action = action
    change_request.portfolio = portfolio
    change_request.details = details or {}
    change_request.status = Status.DRAFT
    change_request.save()

    change_request.items.all().delete()
    ChangeItem.objects.bulk_create(
        ChangeItem(
            change_request=change_request,
            operation=item.operation,
            principal_type=item.principal_type,
            principal_name=item.principal_name,
            old_permission=item.old_permission,
            new_permission=item.new_permission,
        )
        for item in items
    )
    return change_request
