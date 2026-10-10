from django.core.management.base import BaseCommand

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
            metavar="EMAIL",
            help="Also make this email address an approver for every example portfolio.",
        )

    def handle(self, *args, **options):
        for entry in PORTFOLIOS:
            portfolio, created = Portfolio.objects.get_or_create(
                name=entry["name"], defaults={"description": entry["description"]}
            )
            for name, email in entry["approvers"]:
                portfolio.approvers.get_or_create(email=email, defaults={"name": name})
            if options["approver"]:
                email = options["approver"]
                portfolio.approvers.get_or_create(email=email, defaults={"name": email})
            verb = "Created" if created else "Already present:"
            self.stdout.write(f"{verb} {portfolio.name}")
