import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from catalogue.models import Organisation
from catalogue.services import terraform_config, terraform_writer
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def config(root, directory, resource):
    return root / "terraform" / directory / resource / "config.yaml"


class TestModel:
    def test_directory_defaults_to_the_github_name(self):
        organisation = Organisation(name="gov-recruitment")
        organisation.full_clean()
        organisation.save()

        assert organisation.directory == "gov-recruitment"
        assert str(organisation) == "gov-recruitment"

    def test_directory_defaults_without_validation(self):
        assert Organisation.objects.create(name="gov-recruitment").directory == "gov-recruitment"

    @pytest.mark.parametrize("directory", ["..", "../acme", "a/b", ".hidden", "with space", "1st"])
    def test_directory_must_be_a_plain_name(self, directory):
        with pytest.raises(ValidationError) as error:
            Organisation(name="fine", directory=directory).full_clean()

        assert "directory" in error.value.message_dict

    @pytest.mark.parametrize("name", ["-lead", "trail-", "dou--ble", "under_score", "a/b"])
    def test_name_must_be_a_github_organisation_name(self, name):
        with pytest.raises(ValidationError) as error:
            Organisation(name=name, directory="fine").full_clean()

        assert "name" in error.value.message_dict

    @pytest.mark.parametrize(
        "clash", [{"name": "acme", "directory": "other"}, {"name": "other", "directory": "acme"}]
    )
    def test_name_and_directory_are_unique(self, clash):
        with pytest.raises(ValidationError):
            Organisation(**clash).full_clean()

    def test_admin_adds_an_organisation(self, client):
        client.force_login(UserFactory(is_staff=True, is_superuser=True))

        response = client.post(
            "/admin/catalogue/organisation/add/", {"name": "gov-recruitment", "directory": ""}
        )

        assert response.status_code == 302
        assert Organisation.objects.get(name="gov-recruitment").directory == "gov-recruitment"
        assert client.get("/admin/catalogue/organisation/?q=gov").status_code == 200


class TestNewOrganisation:
    def test_appears_empty_before_any_config_exists(self, auth_client):
        Organisation.objects.create(name="gov-recruitment")

        assert b'href="/orgs/gov-recruitment/"' in auth_client.get("/").content
        response = auth_client.get("/orgs/gov-recruitment/")
        assert response.status_code == 200
        assert b"This organisation has no repositories." in response.content

    def test_directory_without_an_organisation_is_not_shown(self, auth_client):
        Organisation.objects.filter(name="acme").delete()

        assert auth_client.get("/orgs/acme/").status_code == 404
        assert terraform_config.get_repositories("acme") == []

    def test_first_repository_creates_the_file(self, writable_config):
        Organisation.objects.create(name="gov-recruitment")

        edit = terraform_writer.create_repository("gov-recruitment", "careers-site")
        edit.write()

        assert "b/terraform/gov-recruitment/repositories/config.yaml" in edit.diff()
        text = config(writable_config, "gov-recruitment", "repositories").read_text()
        assert text.startswith(
            "---\ngov-recruitment:\n  slug: gov-recruitment\n  repositories:\n    careers-site:\n"
        )
        names = [r.name for r in terraform_config.get_repositories("gov-recruitment")]
        assert names == ["careers-site"]

    def test_first_team_creates_the_file(self, writable_config):
        Organisation.objects.create(name="gov-recruitment")

        terraform_writer.create_team("gov-recruitment", "Hiring", "hiring").write()

        text = config(writable_config, "gov-recruitment", "teams").read_text()
        assert text.startswith(
            "---\ngov-recruitment:\n  slug: gov-recruitment\n  teams:\n    hiring:\n"
        )
        assert [t.slug for t in terraform_config.get_teams("gov-recruitment")] == ["hiring"]


class TestDirectoryDiffersFromName:
    @pytest.fixture(autouse=True)
    def organisation(self, writable_config):
        return Organisation.objects.create(name="Gov-Recruitment", directory="recruitment")

    def test_new_file_goes_in_the_directory_with_the_github_name_as_slug(self, writable_config):
        terraform_writer.create_repository("Gov-Recruitment", "careers-site").write()

        text = config(writable_config, "recruitment", "repositories").read_text()
        assert text.startswith("---\nrecruitment:\n  slug: Gov-Recruitment\n  repositories:\n")
        assert not (writable_config / "terraform" / "Gov-Recruitment").exists()

    def test_reads_and_edits_through_the_github_name(self, writable_config):
        terraform_writer.create_repository("Gov-Recruitment", "careers-site").write()
        terraform_writer.modify_repository(
            "Gov-Recruitment", "careers-site", user_permissions={"asmith": "push"}
        ).write()

        repository = terraform_config.get_repository("Gov-Recruitment", "careers-site")
        assert repository.user_permissions == {"asmith": "push"}
        assert terraform_config.get_repositories("recruitment") == []

    def test_existing_directory_under_another_name(self):
        Organisation.objects.filter(name="acme").update(name="acme-corp")

        assert terraform_config.get_repository("acme-corp", "trade-api") is not None
        assert terraform_config.get_repositories("acme") == []


class TestImportCommand:
    def test_adds_an_organisation_for_each_directory(self, capsys):
        Organisation.objects.all().delete()

        call_command("import_organisations")
        call_command("import_organisations")

        found = dict(Organisation.objects.values_list("directory", "name"))
        # The GitHub name comes from the file's `slug` where there is one.
        assert found == {
            "acme": "acme",
            "bare-org": "bare-org",
            "empty-org": "empty-org",
            "legacy": "legacy-org",
        }
        assert "Added legacy-org (terraform/legacy)" in capsys.readouterr().out

    def test_leaves_existing_organisations_alone(self):
        Organisation.objects.filter(name="acme").update(name="renamed")

        call_command("import_organisations")

        assert Organisation.objects.get(directory="acme").name == "renamed"
        assert Organisation.objects.count() == 4

    def test_skips_a_directory_it_cannot_use(self, writable_config, capsys):
        (writable_config / "terraform" / "9lives").mkdir()

        call_command("import_organisations")

        assert not Organisation.objects.filter(directory="9lives").exists()
        assert "Skipped 9lives" in capsys.readouterr().err
