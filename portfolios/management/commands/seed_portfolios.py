from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from portfolios.models import Portfolio

# Example data for demos. Names and addresses are made up.
PORTFOLIOS = [
    {
        "name": "Digital Trade",
        "description": "Services that support importers and exporters.",
        "approvers": [
            ("Priya Shah", "priya.shah@example.com"),
            ("Tom Okafor", "tom.okafor@example.com"),
        ],
    },
    {
        "name": "Data Services",
        "description": "Data platforms, pipelines and analytics.",
        "approvers": [
            ("Hannah Lewis", "hannah.lewis@example.com"),
            ("Marek Nowak", "marek.nowak@example.com"),
        ],
    },
    {
        "name": "Platform and Infrastructure",
        "description": "Hosting, CI/CD and shared tooling.",
        "approvers": [
            ("Aisha Khan", "aisha.khan@example.com"),
            ("Daniel Reid", "daniel.reid@example.com"),
            ("Sofia Marin", "sofia.marin@example.com"),
        ],
    },
    {
        "name": "Corporate Services",
        "description": "Internal HR, finance and workplace tools.",
        "approvers": [
            ("Owen Hughes", "owen.hughes@example.com"),
        ],
    },
]


class Command(BaseCommand):
    help = "Create example portfolios and approvers for demos. Safe to run more than once."

    def add_arguments(self, parser):
        parser.add_argument(
            "--approver",
            metavar="USER",
            help=(
                "Also make this existing user an approver for every example portfolio. "
                "Give their email_user_id or their email address."
            ),
        )

    def handle(self, *args, **options):
        approver = self._find_user(options["approver"]) if options["approver"] else None
        for entry in PORTFOLIOS:
            portfolio, created = Portfolio.objects.get_or_create(
                name=entry["name"], defaults={"description": entry["description"]}
            )
            for name, email in entry["approvers"]:
                portfolio.approvers.get_or_create(email=email, defaults={"name": name})
            if approver:
                portfolio.approvers.get_or_create(
                    user=approver,
                    defaults={
                        "name": approver.get_full_name() or approver.email_user_id,
                        "email": approver.email or f"{approver.email_user_id}@example.invalid",
                    },
                )
            verb = "Created" if created else "Already present:"
            self.stdout.write(f"{verb} {portfolio.name}")

    def _find_user(self, identifier):
        User = get_user_model()
        matches = User.objects.filter(
            Q(email_user_id__iexact=identifier) | Q(email__iexact=identifier)
        )
        if len(matches) != 1:
            problem = "No user" if not matches else "More than one user"
            raise CommandError(f"{problem} has the email_user_id or email {identifier!r}.")
        return matches[0]
