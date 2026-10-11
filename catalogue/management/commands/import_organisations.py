from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from catalogue.models import Organisation
from catalogue.services import terraform_config


class Command(BaseCommand):
    help = (
        "Create an organisation for each directory under terraform/ that does not have one. "
        "Safe to re-run."
    )

    def handle(self, *args, **options):
        known = set(Organisation.objects.values_list("directory", flat=True))
        created = 0
        for directory in terraform_config.list_directories():
            if directory in known:
                continue
            name = terraform_config.github_name(directory) or directory
            organisation = Organisation(name=name, directory=directory)
            try:
                organisation.full_clean()
            except ValidationError as error:
                reasons = "; ".join(error.messages)
                self.stderr.write(self.style.WARNING(f"Skipped {directory}: {reasons}"))
                continue
            organisation.save()
            created += 1
            self.stdout.write(f"Added {name} (terraform/{directory})")
        self.stdout.write(self.style.SUCCESS(f"{created} organisation(s) added."))
