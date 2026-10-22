from django.core.management.base import BaseCommand, CommandError

from world.services import validate
from world.services._loader import world_path


class Command(BaseCommand):
    help = (
        "Check every file in the world directory (WORLD_PATH) and list the problems, with the "
        "file and line of each. Exits with status 1 if there are errors. Warnings, such as "
        "people referred to in one file but missing from people.yaml, do not fail it."
    )

    def handle(self, *args, **options):
        self.stdout.write(f"Checking {world_path()}")
        result = validate.check()
        for file in result.missing:
            self.stdout.write(f"{file}: not present, treated as empty")
        for problem in result.errors:
            self.stdout.write(self.style.ERROR(str(problem)))
        for problem in result.warnings:
            self.stdout.write(self.style.WARNING(str(problem)))
        summary = f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)."
        if result.errors:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
