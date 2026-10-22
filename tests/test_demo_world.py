"""The demo world: its size, that it is stable, and that every planted problem is in it.

The planted problems are listed in `world/demo.py`'s docstring; each has a test here.
"""

from pathlib import Path

import pytest
import yaml
from django.conf import settings as django_settings
from django.core.management import CommandError, call_command

from catalogue.models import Organisation
from catalogue.services import github_teams, terraform_config
from world import demo
from world.services import exclusions, intranet, people, sso_apps, validate

ORGS = [demo.TRADE, demo.DATA]
SCHEMAS = django_settings.BASE_DIR / "terraform-github-sample" / "schemas"


@pytest.fixture
def generated(settings, tmp_path, db):
    world_dir, terraform_dir = tmp_path / "world", tmp_path / "terraform-github"
    demo.write(world_dir, terraform_dir, SCHEMAS)
    settings.WORLD_PATH = world_dir
    settings.TERRAFORM_GITHUB_PATH = terraform_dir
    for org in ORGS:
        Organisation.objects.create(name=org, directory=org)
    return world_dir, terraform_dir


@pytest.fixture
def world(generated):
    """The generated world, read back through the readers."""
    everyone = people.get_people()
    portfolios = intranet.get_portfolios()
    teams = {team.name: team for portfolio in portfolios for team in portfolio.teams}
    team_of = {email: name for name, team in teams.items() for email in team.members}
    return {
        "people": everyone,
        "by_login": {p.github_login: p for p in everyone if p.github_login},
        "portfolios": portfolios,
        "teams": teams,
        "team_of": team_of,
        "repos": {org: terraform_config.get_repositories(org) for org in ORGS},
        "github_teams": {org: terraform_config.get_teams(org) for org in ORGS},
        "applications": {app.slug: app for app in sso_apps.get_applications()},
    }


def raw_teams(terraform_dir: Path, org: str) -> dict:
    """The organisation's teams config as written, for fields the reader does not parse yet."""
    path = terraform_dir / "terraform" / org / "teams" / "config.yaml"
    return yaml.safe_load(path.read_text())[org]


def github_team(world, org, slug):
    return next(team for team in world["github_teams"][org] if team.slug == slug)


def members_of(world, org, slug) -> set[str]:
    return set(github_team(world, org, slug).members)


class TestShape:
    def test_size(self, world):
        assert len(world["portfolios"]) == 4
        assert len(world["teams"]) == 12
        assert len(world["people"]) == 80
        assert sum(len(repos) for repos in world["repos"].values()) == 60
        assert sum(len(teams) for teams in world["github_teams"].values()) == 30

    def test_portfolios_match_the_seeded_ones(self, world):
        # seed_portfolios creates these, so bootstrapping can match them by name.
        assert {p.name for p in world["portfolios"]} == {
            "Digital Trade",
            "Data Services",
            "Platform and Infrastructure",
            "Corporate Services",
        }

    def test_world_is_valid(self, generated):
        result = validate.check()

        assert result.problems == []
        assert result.missing == []

    def test_is_the_same_every_run(self, tmp_path):
        first, second = tmp_path / "first", tmp_path / "second"
        for root in (first, second):
            demo.write(root / "world", root / "terraform", SCHEMAS)

        files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
        assert len(files) > 8
        assert files == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
        for path in files:
            assert (first / path).read_bytes() == (second / path).read_bytes(), path

    def test_checked_in_copies_are_up_to_date(self, generated):
        world_dir, terraform_dir = generated
        base = django_settings.BASE_DIR
        pairs = [
            (world_dir, base / "world-sample"),
            (terraform_dir, base / "terraform-github-demo"),
        ]
        for fresh, checked_in in pairs:
            for path in fresh.rglob("*"):
                if path.is_file():
                    committed = checked_in / path.relative_to(fresh)
                    assert committed.is_file(), f"{committed} is missing"
                    assert committed.read_bytes() == path.read_bytes(), (
                        f"{committed} is out of date: run manage.py generate_demo_world"
                    )

    def test_copies_the_schemas(self, generated):
        _, terraform_dir = generated
        assert (terraform_dir / "schemas" / "terraform-team-schema.yaml").is_file()

    def test_terraform_tree_reads_as_organisations(self, generated):
        call_command("import_organisations")

        assert set(ORGS) <= set(terraform_config.list_organisations())


class TestSafety:
    def test_rewrites_its_own_output(self, tmp_path):
        demo.write(tmp_path / "w", tmp_path / "t", SCHEMAS)
        (tmp_path / "t" / "terraform" / "stale-org").mkdir()

        demo.write(tmp_path / "w", tmp_path / "t", SCHEMAS)

        assert not (tmp_path / "t" / "terraform" / "stale-org").exists()

    def test_refuses_a_directory_it_did_not_write(self, tmp_path):
        (tmp_path / "t").mkdir()
        (tmp_path / "t" / "keep-me.yaml").write_text("real: data\n")

        with pytest.raises(demo.UnsafeTarget, match="did not write"):
            demo.write(tmp_path / "w", tmp_path / "t", SCHEMAS)

        assert (tmp_path / "t" / "keep-me.yaml").read_text() == "real: data\n"

    def test_refuses_a_git_checkout(self, tmp_path):
        (tmp_path / "t" / ".git").mkdir(parents=True)

        with pytest.raises(demo.UnsafeTarget, match="git checkout"):
            demo.write(tmp_path / "w", tmp_path / "t", SCHEMAS)

    def test_command_reports_a_refusal(self, tmp_path):
        (tmp_path / "w").mkdir()
        (tmp_path / "w" / "people.yaml").write_text("people: []\n")

        with pytest.raises(CommandError, match="did not write"):
            call_command(
                "generate_demo_world",
                world_dir=tmp_path / "w",
                terraform_dir=tmp_path / "t",
            )

    def test_command_writes_both_trees(self, tmp_path, capsys):
        call_command("generate_demo_world", world_dir=tmp_path / "w", terraform_dir=tmp_path / "t")

        assert "8 file(s) written." in capsys.readouterr().out
        assert (tmp_path / "w" / "people.yaml").is_file()
        assert (tmp_path / "t" / "terraform" / demo.DATA / "teams" / "config.yaml").is_file()


class TestPlantedProblems:
    def test_1_direct_user_permissions(self, world):
        direct = {
            repo.name
            for repos in world["repos"].values()
            for repo in repos
            if repo.user_permissions
        }

        assert direct == {"trade-api", "finance-ledger", "de-pipelines", "infra-warehouse"}

    def test_2_github_team_members_from_another_team(self, world):
        def outsiders(org, slug, intranet_team):
            return {
                login
                for login in members_of(world, org, slug)
                if login in world["by_login"]
                and world["by_login"][login].active
                and world["team_of"].get(world["by_login"][login].email) != intranet_team
            }

        in_data_sci = outsiders(demo.TRADE, "data-sci", "Data Science")
        assert len(in_data_sci) == 2
        assert {world["team_of"][world["by_login"][login].email] for login in in_data_sci} == {
            "Analytics"
        }
        in_finance = outsiders(demo.TRADE, "finance-systems", "Finance Systems")
        assert [world["team_of"][world["by_login"][login].email] for login in in_finance] == [
            "Data Engineering"
        ]

    def test_3_orphaned_repositories(self, world):
        def owning_teams(repo):
            return [
                team
                for team, permission in repo.team_permissions.items()
                if permission in ("admin", "maintain")
            ]

        all_repos = [repo for repos in world["repos"].values() for repo in repos]
        assert {repo.name for repo in all_repos if not owning_teams(repo)} == {
            "legacy-trade-tool",
            "old-data-scripts",
        }
        shared = next(repo for repo in all_repos if repo.name == "shared-design-system")
        assert len(owning_teams(shared)) == 2

    def test_4_deactivated_people_still_in_github_teams(self, world):
        inactive = {p.github_login for p in world["people"] if not p.active}
        in_teams = {
            login
            for org in ORGS
            for team in world["github_teams"][org]
            for login in team.members
            if login in inactive
        }

        assert len(inactive) == 3
        assert in_teams == inactive
        assert all(p.deactivated_at for p in world["people"] if not p.active)

    def test_4_active_person_without_github_login(self, world):
        unlinked = [p for p in world["people"] if p.active and not p.github_login]

        assert len(unlinked) == 1
        assert world["team_of"][unlinked[0].email] == "HR Systems"

    def test_5_stale_github_teams(self, world, generated):
        _, terraform_dir = generated
        for org, expected in [(demo.TRADE, {"old-migration"}), (demo.DATA, {"hackathon-2023"})]:
            used = {team for repo in world["repos"][org] for team in repo.team_permissions}
            with_org_roles = {
                slug
                for slug, team in raw_teams(terraform_dir, org)["teams"].items()
                if team.get("organisation_role_names")
            }
            unused = {team.slug for team in world["github_teams"][org]} - used - with_org_roles
            assert unused == expected

        legacy = members_of(world, demo.TRADE, "legacy-reporting")
        assert legacy
        assert not any(world["by_login"][login].active for login in legacy)

    def test_6_role_like_and_baseline_teams(self, world, generated):
        _, terraform_dir = generated
        for org in ORGS:
            slugs = {team.slug for team in world["github_teams"][org]}
            assert {slug for slug in slugs if slug.endswith("-admins")}
            assert all(repo.team_permissions.get("cyber") == "pull" for repo in world["repos"][org])
            architects = raw_teams(terraform_dir, org)["teams"]["architects"]
            assert architects["organisation_role_names"] == ["all_repo_read"]

    def test_7_names_differ_between_intranet_and_github(self, world):
        slugs = {team.slug for org in ORGS for team in world["github_teams"][org]}

        assert "Data Science" in world["teams"]
        assert "data-sci" in slugs
        assert "data-science" not in slugs
        assert "Data Infrastructure" in world["teams"]
        assert "data-infra" in slugs

    def test_7_intranet_team_with_no_github_team(self, world):
        slugs = {team.slug for org in ORGS for team in world["github_teams"][org]}

        assert "Workplace Tech" in world["teams"]
        assert not any(slug.startswith("workplace") for slug in slugs)

    def test_8_sso_assignments_that_bypass_roles(self, world):
        datadog = world["applications"]["datadog"]
        by_sso_id = {p.sso_id: p for p in world["people"]}
        datascience_outsiders = {
            world["team_of"].get(by_sso_id[sso_id].email)
            for sso_id, held in datadog.assignments.items()
            if "team-datascience" in held
            and world["team_of"].get(by_sso_id[sso_id].email) != "Data Science"
        }
        leavers_assigned = [
            sso_id for sso_id in datadog.assignments if not by_sso_id[sso_id].active
        ]

        assert datascience_outsiders == {"Analytics"}
        assert len(leavers_assigned) == 1


class TestOtherFeatures:
    def test_login_that_belongs_to_nobody(self, world):
        assert demo.UNKNOWN_LOGIN not in world["by_login"]
        assert demo.UNKNOWN_LOGIN in members_of(world, demo.DATA, "analytics")

    def test_intranet_members_missing_from_their_github_team(self, world):
        trade = world["teams"]["Trade Platform"]
        logins = {
            p.github_login for p in world["people"] if p.email in trade.members and p.github_login
        }

        assert logins - members_of(world, demo.TRADE, "trade-platform")

    def test_nested_team(self, world):
        child = github_team(world, demo.TRADE, "trade-platform-frontend")

        assert github_teams.get_parent_team(demo.TRADE, child).slug == "trade-platform"

    def test_org_owners_and_excluded_bot(self, world, generated):
        _, terraform_dir = generated
        excluded = exclusions.get_exclusions()

        assert demo.BREAKGLASS_LOGIN in raw_teams(terraform_dir, demo.TRADE)["admin_logins"]
        assert excluded.excludes_login(demo.BOT_LOGIN)
        assert demo.BOT_LOGIN in members_of(world, demo.TRADE, "sre")
