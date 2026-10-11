from django.core.validators import RegexValidator
from django.db import models

# The directory doubles as the organisation's top-level key in config.yaml, so it follows
# the schemas' pattern for that key. That also keeps it to a single, safe path component.
directory_validator = RegexValidator(
    r"^[a-zA-Z][a-zA-Z0-9_-]*\Z",
    "Use letters, numbers, hyphens and underscores, starting with a letter.",
)
github_name_validator = RegexValidator(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9]))*\Z",
    "Use letters and numbers, with single hyphens between them.",
)


class Organisation(models.Model):
    """A GitHub organisation this app manages, and where its config lives.

    The config is at `terraform/{directory}/repositories/config.yaml` and
    `terraform/{directory}/teams/config.yaml` under TERRAFORM_GITHUB_PATH. The files are
    created the first time a change is written to them.
    """

    name = models.CharField(
        "GitHub organisation",
        max_length=39,
        unique=True,
        validators=[github_name_validator],
        help_text="The organisation's name on GitHub, as in github.com/<name>.",
    )
    directory = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        validators=[directory_validator],
        help_text=(
            "The directory under terraform/ that holds this organisation's config. "
            "Leave blank to use the GitHub name."
        ),
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.directory:
            self.directory = self.name
        super().save(*args, **kwargs)

    def clean(self):
        if not self.directory:
            self.directory = self.name
