import re
from pathlib import Path

import pytest
import yaml

from catalogue.choices import RepositoryPermission, TeamRole
from catalogue.services import github_teams, terraform_config
from catalogue.services.terraform_config import Repository, Team
from tests.conftest import FIXTURE_TERRAFORM_GITHUB

SCHEMAS = Path(__file__).parent.parent / "terraform-github" / "schemas"


class TestOrganisations:
    def test_lists_directories_only_sorted(self):
        assert terraform_config.list_organisations() == ["acme", "bare-org", "empty-org", "legacy"]

    def test_missing_checkout_gives_no_organisations(self, settings, tmp_path):
        settings.TERRAFORM_GITHUB_PATH = tmp_path / "does-not-exist"

        assert terraform_config.list_organisations() == []

    def test_checkout_without_terraform_directory(self, settings, tmp_path):
        settings.TERRAFORM_GITHUB_PATH = tmp_path

        assert terraform_config.list_organisations() == []
        assert terraform_config.get_repositories("acme") == []

    def test_uses_fixture_tree_not_real_checkout(self, settings):
        assert settings.TERRAFORM_GITHUB_PATH == FIXTURE_TERRAFORM_GITHUB


class TestRepositories:
    def test_lists_repositories_sorted_by_name(self):
        names = [r.name for r in terraform_config.get_repositories("acme")]

        assert names == [".github", "design-docs", "legacy-importer", "trade-api"]

    def test_parses_repository(self):
        assert terraform_config.get_repository("acme", "trade-api") == Repository(
            name="trade-api",
            archived=False,
            description="Public API for trade data",
            visibility="internal",
            team_permissions={"platform-sre": "admin", "data-engineering": "push"},
            user_permissions={"jbloggs": "maintain", "old-contractor": "pull"},
        )

    def test_archived_repository_with_null_user_permissions(self):
        repo = terraform_config.get_repository("acme", "legacy-importer")

        assert repo.archived is True
        assert repo.description is None
        assert repo.user_permissions == {}
        assert repo.team_permissions == {"platform-sre": "admin"}

    def test_repository_without_optional_fields(self):
        repo = terraform_config.get_repository("acme", "design-docs")

        assert repo.archived is False
        assert repo.team_permissions == {}
        assert repo.user_permissions == {}

    def test_unknown_repository(self):
        assert terraform_config.get_repository("acme", "nope") is None

    @pytest.mark.parametrize("org", ["empty-org", "bare-org", "unknown-org", "..", "../acme"])
    def test_empty_missing_or_unknown_gives_empty_list(self, org):
        assert terraform_config.get_repositories(org) == []
        assert terraform_config.get_repository(org, "trade-api") is None

    def test_top_level_key_may_differ_from_directory(self):
        assert [r.name for r in terraform_config.get_repositories("legacy")] == ["old-site"]


class TestTeams:
    def test_lists_teams_sorted_by_name(self):
        slugs = [t.slug for t in terraform_config.get_teams("acme")]

        assert slugs == ["contractors", "data-engineering", "platform-sre", "platform-sre-oncall"]

    def test_parses_team(self):
        assert terraform_config.get_team("acme", "platform-sre") == Team(
            name="Platform SRE",
            slug="platform-sre",
            description="Runs the platform",
            privacy="closed",
            parent_team_id=None,
            members={"jbloggs": "maintainer", "asmith": "member"},
        )

    def test_team_without_optional_fields(self):
        team = terraform_config.get_team("acme", "contractors")

        assert team.description is None
        assert team.parent_team_id is None
        assert team.members == {}

    def test_unknown_team(self):
        assert terraform_config.get_team("acme", "nope") is None

    @pytest.mark.parametrize("org", ["empty-org", "bare-org", "unknown-org", "legacy"])
    def test_empty_missing_or_malformed_gives_empty_list(self, org):
        assert terraform_config.get_teams(org) == []
        assert terraform_config.get_team(org, "platform-sre") is None


class TestTeamIds:
    def test_every_team_has_a_stable_id(self):
        ids = github_teams.get_team_ids("acme")

        assert set(ids) == {
            "contractors",
            "data-engineering",
            "platform-sre",
            "platform-sre-oncall",
        }
        assert len(set(ids.values())) == 4
        assert ids == github_teams.get_team_ids("acme")

    def test_get_team_id(self):
        assert github_teams.get_team_id("acme", "platform-sre") == 3152637
        assert github_teams.get_team_id("acme", "nope") is None

    def test_resolves_parent_team(self):
        oncall = terraform_config.get_team("acme", "platform-sre-oncall")

        assert github_teams.get_parent_team("acme", oncall).slug == "platform-sre"

    def test_team_without_parent(self):
        team = terraform_config.get_team("acme", "platform-sre")

        assert github_teams.get_parent_team("acme", team) is None

    def test_parent_id_not_known_to_github(self):
        team = terraform_config.get_team("acme", "data-engineering")

        assert team.parent_team_id == 42
        assert github_teams.get_parent_team("acme", team) is None

    def test_organisation_without_teams(self):
        assert github_teams.get_team_ids("empty-org") == {}


class TestChoices:
    def test_values(self):
        assert set(RepositoryPermission.values) == {"pull", "triage", "push", "maintain", "admin"}
        assert set(TeamRole.values) == {"member", "maintainer"}

    def test_fixture_values_are_valid_choices(self):
        for repo in terraform_config.get_repositories("acme"):
            for level in (repo.team_permissions | repo.user_permissions).values():
                assert level in RepositoryPermission.values
        for team in terraform_config.get_teams("acme"):
            assert set(team.members.values()) <= set(TeamRole.values)

    @pytest.mark.skipif(not SCHEMAS.is_dir(), reason="terraform-github schemas not present")
    def test_choices_match_the_schemas(self):
        def alternatives(pattern):
            return set(re.search(r"\(([^)]*)\)", pattern).group(1).split("|"))

        repo_schema = yaml.safe_load((SCHEMAS / "terraform-repository-schema.yaml").read_text())
        team_schema = yaml.safe_load((SCHEMAS / "terraform-team-schema.yaml").read_text())
        repo_props = next(iter(repo_schema["patternProperties"].values()))["properties"]
        repo_props = next(iter(repo_props["repositories"]["patternProperties"].values()))
        team_props = next(iter(team_schema["patternProperties"].values()))["properties"]
        team_props = next(iter(team_props["teams"]["patternProperties"].values()))

        for key in ("team_permissions", "user_permissions"):
            pattern = next(iter(repo_props["properties"][key]["patternProperties"].values()))
            assert alternatives(pattern["pattern"]) == set(RepositoryPermission.values)
        members = next(iter(team_props["properties"]["members"]["patternProperties"].values()))
        assert alternatives(members["pattern"]) == set(TeamRole.values)
