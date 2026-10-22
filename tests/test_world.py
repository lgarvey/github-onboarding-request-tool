from datetime import date
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from tests.conftest import FIXTURE_WORLD
from world.choices import SSOApplicationKind
from world.services import exclusions, intranet, people, sso_apps, validate
from world.services.intranet import IntranetPortfolio, IntranetTeam
from world.services.people import Person

BROKEN_WORLD = Path(__file__).parent / "fixtures" / "broken-world"


@pytest.fixture
def broken_world(settings):
    settings.WORLD_PATH = BROKEN_WORLD


@pytest.fixture
def empty_world(settings, tmp_path):
    settings.WORLD_PATH = tmp_path


class TestPeople:
    def test_parses_people(self):
        assert people.get_people() == [
            Person(
                sso_id="jane.doe-1a2b3c4d@id.example.gov.uk",
                email="jane.doe@example.gov.uk",
                first_name="Jane",
                last_name="Doe",
                github_login="janedoe",
            ),
            Person(
                sso_id="sam.minter-5e6f7a8b@id.example.gov.uk",
                email="sam.minter@example.gov.uk",
                first_name="Sam",
                last_name="Minter",
                active=False,
                deactivated_at=date(2026, 5, 1),
                github_login="sminter",
            ),
            Person(
                sso_id="alex.ng-9c0d1e2f@id.example.gov.uk",
                email="alex.ng@example.gov.uk",
                first_name="Alex",
                last_name="Ng",
            ),
            Person(
                sso_id="pat.kaur-3a4b5c6d@id.example.gov.uk",
                email="pat.kaur@example.gov.uk",
                first_name="Pat",
                last_name="Kaur",
                github_login="PatK",
            ),
        ]

    def test_full_name(self):
        assert people.get_people()[0].full_name == "Jane Doe"

    def test_skips_entries_with_problems(self, broken_world):
        assert [person.sso_id for person in people.get_people()] == ["jane.doe-1@id.example.gov.uk"]

    def test_missing_file_is_empty(self, empty_world):
        assert people.parse() == ([], [])


class TestIntranet:
    def test_parses_portfolios_and_lower_cases_emails(self):
        assert intranet.get_portfolios() == [
            IntranetPortfolio(
                name="Digital Trade",
                teams=(
                    IntranetTeam(
                        name="Data Science",
                        lead="jane.doe@example.gov.uk",
                        members=("jane.doe@example.gov.uk", "alex.ng@example.gov.uk"),
                    ),
                ),
            ),
            IntranetPortfolio(
                name="Data Services",
                teams=(
                    IntranetTeam(
                        name="Analytics",
                        members=("pat.kaur@example.gov.uk", "former.member@example.gov.uk"),
                    ),
                ),
            ),
            IntranetPortfolio(name="Empty Portfolio"),
        ]

    def test_team_names_are_unique_across_portfolios(self, broken_world):
        portfolios = intranet.get_portfolios()

        assert [p.name for p in portfolios] == ["Digital Trade", "Data Services"]
        assert portfolios[0].teams[0].members == ("jane.doe@example.gov.uk",)
        assert portfolios[1].teams == ()

    def test_missing_file_is_empty(self, empty_world):
        assert intranet.get_portfolios() == []


class TestSSOApps:
    def test_parses_applications(self):
        datadog, datahub = sso_apps.get_applications()

        assert datadog.kind == SSOApplicationKind.SAML
        assert datadog.permissions == ("team-datascience", "platform-engineer")
        assert datadog.assignments == {
            "jane.doe-1a2b3c4d@id.example.gov.uk": ("team-datascience",),
            "pat.kaur-3a4b5c6d@id.example.gov.uk": ("team-datascience", "platform-engineer"),
        }
        assert datahub.kind == SSOApplicationKind.OAUTH
        assert datahub.permissions == ()
        assert datahub.assignments["alex.ng-9c0d1e2f@id.example.gov.uk"] == ()

    def test_skips_invalid_applications_and_assignments(self, broken_world):
        (sentry,) = sso_apps.get_applications()

        assert sentry.slug == "sentry"
        assert sentry.assignments == {}

    def test_missing_file_is_empty(self, empty_world):
        assert sso_apps.get_applications() == []


class TestExclusions:
    def test_matches_logins_ignoring_case(self):
        excluded = exclusions.get_exclusions()

        assert excluded.excludes_login("ci-bot")
        assert excluded.excludes_login("BreakGlass-Admin")
        assert not excluded.excludes_login("janedoe")
        assert excluded.sso_ids == frozenset()

    def test_unreadable_file_is_empty(self, broken_world):
        assert exclusions.get_exclusions() == exclusions.Exclusions()

    def test_missing_file_is_empty(self, empty_world):
        assert not exclusions.get_exclusions().excludes_login("anyone")


class TestValidate:
    def test_valid_world_has_only_cross_reference_warnings(self):
        result = validate.check()

        assert result.errors == []
        assert [str(problem) for problem in result.warnings] == [
            "intranet.yaml: warning: former.member@example.gov.uk in team Analytics is not in "
            "people.yaml.",
            "sso_apps.yaml: warning: someone.gone-00000000@id.example.gov.uk on datahub is not "
            "in people.yaml.",
        ]

    def test_reports_file_line_and_message(self, broken_world):
        lines = [(p.file, p.line, p.message) for p in validate.check().errors]

        assert lines == [
            ("people.yaml", 7, "The person has no 'email'."),
            ("people.yaml", 10, "sso_id 'jane.doe-1@id.example.gov.uk' appears more than once."),
            (
                "people.yaml",
                18,
                "'-not-valid' in person bad.login@id.example.gov.uk is not a valid GitHub login.",
            ),
            (
                "people.yaml",
                19,
                "Unknown field 'githublogin' in person. Expected: active, deactivated_at, email, "
                "first_name, github_login, last_name, sso_id.",
            ),
            (
                "people.yaml",
                24,
                "person gone.early@id.example.gov.uk is active but has a deactivated_at.",
            ),
            (
                "people.yaml",
                26,
                "'not-an-email' in person bad.date@id.example.gov.uk is not an email address.",
            ),
            (
                "people.yaml",
                30,
                "'deactivated_at' in person bad.date@id.example.gov.uk should be a date such as "
                "2026-01-31.",
            ),
            ("intranet.yaml", 2, "The portfolio has no 'name'."),
            ("intranet.yaml", 6, "'jane' in team Data Science is not an email address."),
            ("intranet.yaml", 9, "The team 'data science' appears more than once."),
            ("intranet.yaml", 10, "Unknown section 'teams'. Expected 'portfolios'."),
            (
                "sso_apps.yaml",
                4,
                "'kind' in application datadog should be saml or oauth, not 'ldap'.",
            ),
            ("sso_apps.yaml", 8, "application datahub is an OAuth app, so it has no permissions."),
            (
                "sso_apps.yaml",
                14,
                "jane.doe-1@id.example.gov.uk holds owner, which application sentry does not "
                "define.",
            ),
            (
                "exclusions.yaml",
                2,
                "Could not read the file: expected ',' or ']', but got '<stream end>'.",
            ),
        ]

    def test_missing_files_are_listed(self, empty_world):
        result = validate.check()

        assert result.missing == [
            "people.yaml",
            "intranet.yaml",
            "sso_apps.yaml",
            "exclusions.yaml",
        ]
        assert result.problems == []

    @pytest.mark.parametrize(
        "content, message",
        [
            ("- just\n- a list\n", "Expected the file to hold 'people'."),
            ("people: {}\n", "'people' should be a list."),
            ("people:\n  - just text\n", "Each person should be a mapping of fields."),
        ],
    )
    def test_wrong_shapes(self, empty_world, tmp_path, content, message):
        (tmp_path / "people.yaml").write_text(content)

        assert [p.message for p in validate.check().errors] == [message]

    def test_repeated_github_login_ignores_case(self, empty_world, tmp_path):
        (tmp_path / "people.yaml").write_text(
            "people:\n"
            "  - {sso_id: a@id.example.gov.uk, email: a@example.gov.uk, first_name: A,"
            " last_name: A, github_login: Same}\n"
            "  - {sso_id: b@id.example.gov.uk, email: b@example.gov.uk, first_name: B,"
            " last_name: B, github_login: same}\n"
        )

        assert [str(p) for p in validate.check().errors] == [
            "people.yaml:3: error: github_login 'same' appears more than once."
        ]
        assert len(people.get_people()) == 1


class TestValidateWorldCommand:
    def test_valid_world(self, capsys):
        call_command("validate_world")

        out = capsys.readouterr().out
        assert f"Checking {FIXTURE_WORLD}" in out
        assert "0 error(s), 2 warning(s)." in out

    def test_errors_fail_the_command(self, broken_world, capsys):
        with pytest.raises(CommandError, match=r"15 error\(s\), 0 warning\(s\)\."):
            call_command("validate_world")

        assert "people.yaml:7: error: The person has no 'email'." in capsys.readouterr().out

    def test_missing_files_are_reported(self, empty_world, capsys):
        call_command("validate_world")

        assert "people.yaml: not present, treated as empty" in capsys.readouterr().out


def test_uses_fixture_world_not_real_data(settings):
    assert settings.WORLD_PATH == FIXTURE_WORLD
