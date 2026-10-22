import shutil
from pathlib import Path

import pytest

from catalogue.models import Organisation
from tests.factories import UserFactory

FIXTURE_TERRAFORM_GITHUB = Path(__file__).parent / "fixtures" / "terraform-github"
FIXTURE_WORLD = Path(__file__).parent / "fixtures" / "world"


@pytest.fixture(autouse=True)
def _test_settings(settings):
    # Tests never read the real checkout, and don't need a collectstatic manifest.
    settings.TERRAFORM_GITHUB_PATH = FIXTURE_TERRAFORM_GITHUB
    settings.WORLD_PATH = FIXTURE_WORLD
    # A developer's .env usually turns SSO off; tests start from the real default.
    settings.DISABLE_SSO = False
    settings.APPLY_APPROVED_CHANGES = False
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def organisations(db):
    """An organisation for each directory in the fixture tree."""
    names = ["acme", "bare-org", "empty-org", "legacy"]
    return [Organisation.objects.create(name=name, directory=name) for name in names]


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def writable_config(settings, tmp_path):
    """A throwaway copy of the fixture tree, for tests that write to the YAML."""
    root = tmp_path / "terraform-github"
    shutil.copytree(FIXTURE_TERRAFORM_GITHUB, root)
    settings.TERRAFORM_GITHUB_PATH = root
    return root
