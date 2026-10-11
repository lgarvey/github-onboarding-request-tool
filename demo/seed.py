"""Demo data for the recording. Run with `python manage.py shell < demo/seed.py`.

Only ever run against the throwaway demo database that demo/record.sh creates.
"""

from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType
from change_requests.models import ChangeRequest
from portfolios.models import Approver, Portfolio
from users.models import User

PASSWORD = "demo-password"  # noqa: S105 - local demo accounts only


def person(first, last, **flags):
    # Everyone is staff because, with SSO off, sign-in goes through the admin login form.
    email = f"{first}.{last}@example.com".lower()
    return User.objects.create_user(
        email, email, PASSWORD, first_name=first, last_name=last, is_staff=True, **flags
    )


call_command("seed_portfolios")
call_command("import_organisations")

sam = person("Sam", "Rivera", is_superuser=True)
jo = person("Jo", "Carter")
priya = person("Priya", "Shah")

Approver.objects.filter(email=priya.email).update(user=priya)
corporate = Portfolio.objects.get(name="Corporate Services")
corporate.approvers.create(user=priya, name="Priya Shah", email=priya.email)
trade = Portfolio.objects.get(name="Digital Trade")
data = Portfolio.objects.get(name="Data Services")

# A little history, so the overview pages are not empty.
now = timezone.now()
applied = ChangeRequest.objects.create(
    requested_by=jo,
    organisation="acme",
    target_type=TargetType.TEAM,
    target_name="platform-sre",
    action=Action.MODIFY,
    portfolio=trade,
    status=Status.APPLIED,
    submitted_at=now - timedelta(days=6),
    decided_by=priya,
    decided_at=now - timedelta(days=5),
    applied_at=now - timedelta(days=5),
)
applied.items.create(
    operation=Operation.ADD,
    principal_type=PrincipalType.USER,
    principal_name="asmith",
    new_permission="member",
)
rejected = ChangeRequest.objects.create(
    requested_by=jo,
    organisation="acme",
    target_type=TargetType.REPOSITORY,
    target_name="data-pipeline",
    action=Action.MODIFY,
    portfolio=data,
    status=Status.REJECTED,
    submitted_at=now - timedelta(days=3),
    decided_by=sam,
    decided_at=now - timedelta(days=2),
    decision_comment="Contractors get access through the contractors team, not individually.",
)
rejected.items.create(
    operation=Operation.ADD,
    principal_type=PrincipalType.USER,
    principal_name="old-contractor",
    new_permission="admin",
)
