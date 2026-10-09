from pathlib import Path

import pytest

from tests.factories import UserFactory

FIXTURE_TERRAFORM_GITHUB = Path(__file__).parent / "fixtures" / "terraform-github"


@pytest.fixture(autouse=True)
def _test_settings(settings):
    # Tests never read the real checkout, and don't need a collectstatic manifest.
    settings.TERRAFORM_GITHUB_PATH = FIXTURE_TERRAFORM_GITHUB
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client
