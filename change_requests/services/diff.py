from dataclasses import dataclass

from change_requests.choices import Operation, PrincipalType


@dataclass(frozen=True)
class ChangeItemData:
    operation: Operation
    principal_type: PrincipalType
    principal_name: str
    old_permission: str | None = None
    new_permission: str | None = None


def diff_permissions(
    current: dict[str, str], desired: dict[str, str], principal_type: PrincipalType
) -> list[ChangeItemData]:
    """Return the changes that turn `current` into `desired`.

    Both map a principal (team slug or GitHub username) to a permission or role.
    Additions come first, then changes, then removals, each ordered by principal name.
    Unchanged principals produce nothing.
    """
    added = [
        ChangeItemData(Operation.ADD, principal_type, name, None, desired[name])
        for name in sorted(desired.keys() - current.keys())
    ]
    changed = [
        ChangeItemData(Operation.CHANGE, principal_type, name, current[name], desired[name])
        for name in sorted(desired.keys() & current.keys())
        if current[name] != desired[name]
    ]
    removed = [
        ChangeItemData(Operation.REMOVE, principal_type, name, current[name], None)
        for name in sorted(current.keys() - desired.keys())
    ]
    return added + changed + removed
