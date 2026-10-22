from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from world import demo


class Command(BaseCommand):
    help = (
        "Write a synthetic department to world-sample/ and a matching terraform tree to "
        "terraform-github-demo/. The output is the same on every run. It only overwrites "
        "directories it wrote itself."
    )

    def add_arguments(self, parser):
        parser.add_argument("--world-dir", type=Path, default=settings.BASE_DIR / "world-sample")
        parser.add_argument(
            "--terraform-dir", type=Path, default=settings.BASE_DIR / "terraform-github-demo"
        )

    def handle(self, *args, **options):
        schemas = settings.BASE_DIR / "terraform-github-sample" / "schemas"
        try:
            written = demo.write(options["world_dir"], options["terraform_dir"], schemas)
        except demo.UnsafeTarget as error:
            raise CommandError(str(error)) from error
        for path in written:
            self.stdout.write(f"Wrote {path}")
        self.stdout.write(self.style.SUCCESS(f"{len(written)} file(s) written."))
