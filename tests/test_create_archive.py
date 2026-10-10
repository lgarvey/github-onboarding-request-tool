import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from catalogue.services import github_teams
from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType
from change_requests.forms import TeamDetailsForm
from change_requests.models import ChangeRequest
from tests.factories import ChangeItemFactory, ChangeRequestFactory, PortfolioFactory, UserFactory
from tests.helpers import formset_data

pytestmark = pytest.mark.django_db

NEW_REPO = "/orgs/acme/repos/new/"
NEW_TEAM = "/orgs/acme/teams/new/"
ARCHIVE = "/orgs/acme/repos/trade-api/archive/"


@pytest.fixture
def portfolio():
    return PortfolioFactory(name="Digital Trade")


def items_of(change_request):
    return [
        (i.operation, i.principal_type, i.principal_name, i.old_permission, i.new_permission)
        for i in change_request.items.all()
    ]


def repo_data(portfolio, name="new-service", description="A new service", teams=(), users=()):
    return {
        "name": name,
        "description": description,
        **formset_data("teams", list(teams)),
        **formset_data("users", list(users)),
        "portfolio": portfolio.pk if portfolio else "",
    }


def team_data(portfolio, name="Platform Leads", description="", parent="", members=()):
    return {
        "name": name,
        "description": description,
        "parent": parent,
        **formset_data("members", list(members)),
        "portfolio": portfolio.pk if portfolio else "",
    }


@pytest.mark.parametrize("url", [NEW_REPO, NEW_TEAM, ARCHIVE])
class TestCommon:
    def test_requires_login(self, client, url):
        assert client.get(url).url == f"/login/?next={url}"

    def test_get_renders(self, auth_client, url, portfolio):
        response = auth_client.get(url)

        assert response.status_code == 200
        assert b"Digital Trade" in response.content

    def test_unknown_organisation_is_404(self, auth_client, url):
        assert auth_client.get(url.replace("acme", "nope")).status_code == 404

    def test_linked_from_organisation_page(self, auth_client, url):
        assert f'href="{url}"'.encode() in auth_client.get("/orgs/acme/").content


class TestAddRepository:
    def test_creates_draft_with_add_items(self, auth_client, user, portfolio):
        data = repo_data(
            portfolio,
            teams=[("platform-sre", "admin"), ("data-engineering", "push")],
            users=[("jbloggs", "maintain")],
        )

        response = auth_client.post(NEW_REPO, data)

        change_request = ChangeRequest.objects.get()
        assert response.url == f"/requests/{change_request.pk}/confirm/"
        assert change_request.requested_by == user
        assert change_request.organisation == "acme"
        assert change_request.target_type == TargetType.REPOSITORY
        assert change_request.target_name == "new-service"
        assert change_request.action == Action.CREATE
        assert change_request.details == {"description": "A new service"}
        assert change_request.status == Status.DRAFT
        assert items_of(change_request) == [
            (Operation.ADD, PrincipalType.TEAM, "data-engineering", None, "push"),
            (Operation.ADD, PrincipalType.TEAM, "platform-sre", None, "admin"),
            (Operation.ADD, PrincipalType.USER, "jbloggs", None, "maintain"),
        ]

    def test_summary(self, auth_client, portfolio):
        auth_client.post(NEW_REPO, repo_data(portfolio, teams=[("platform-sre", "admin")]))

        assert ChangeRequest.objects.get().summary_lines() == [
            "New repository: new-service (org: acme)",
            "  Description: A new service",
            "  Add team platform-sre with admin",
            "Portfolio: Digital Trade",
        ]

    def test_collaborators_and_description_are_optional(self, auth_client, portfolio):
        auth_client.post(NEW_REPO, repo_data(portfolio, description=""))

        change_request = ChangeRequest.objects.get()
        assert change_request.details == {"description": ""}
        assert change_request.items.count() == 0

    @pytest.mark.parametrize("name", ["trade-api", "Trade-API", "legacy-importer", ".github"])
    def test_name_must_not_already_exist(self, auth_client, portfolio, name):
        response = auth_client.post(NEW_REPO, repo_data(portfolio, name=name))

        assert response.status_code == 200
        assert response.context["details_form"].errors["name"] == [
            f"A repository called {name} already exists in acme."
        ]
        assert not ChangeRequest.objects.exists()

    def test_same_name_in_another_organisation_is_fine(self, auth_client, portfolio):
        auth_client.post("/orgs/empty-org/repos/new/", repo_data(portfolio, name="trade-api"))

        assert ChangeRequest.objects.get().organisation == "empty-org"

    @pytest.mark.parametrize("name", ["", "has space", "1starts-with-digit", "sla/sh", "-dash"])
    def test_name_must_be_valid(self, auth_client, portfolio, name):
        response = auth_client.post(NEW_REPO, repo_data(portfolio, name=name))

        assert "name" in response.context["details_form"].errors
        assert not ChangeRequest.objects.exists()

    @pytest.mark.parametrize("name", [".dotfiles", "under_score", "a", "Mixed-Case9"])
    def test_valid_names(self, auth_client, portfolio, name):
        auth_client.post(NEW_REPO, repo_data(portfolio, name=name))

        assert ChangeRequest.objects.get().target_name == name

    def test_duplicate_and_invalid_rows_are_errors(self, auth_client, portfolio):
        data = repo_data(
            portfolio,
            teams=[("platform-sre", "admin"), ("platform-sre", "push")],
            users=[("jbloggs", "owner")],
        )

        response = auth_client.post(NEW_REPO, data)

        assert response.context["team_formset"].non_form_errors() == [
            "platform-sre is listed more than once."
        ]
        assert "permission" in response.context["user_formset"].forms[0].errors
        assert not ChangeRequest.objects.exists()

    def test_portfolio_is_required(self, auth_client):
        response = auth_client.post(NEW_REPO, repo_data(None))

        assert "portfolio" in response.context["portfolio_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_back_to_edit(self, auth_client, portfolio):
        auth_client.post(NEW_REPO, repo_data(portfolio, users=[("jbloggs", "maintain")]))
        draft = ChangeRequest.objects.get()
        confirm = auth_client.get(reverse("change_request_confirm", args=[draft.pk]))
        assert f'href="{NEW_REPO}?draft={draft.pk}"'.encode() in confirm.content

        response = auth_client.get(f"{NEW_REPO}?draft={draft.pk}")

        assert response.context["details_form"].initial == {
            "name": "new-service",
            "description": "A new service",
        }
        assert [f.initial for f in response.context["user_formset"]] == [
            {"principal": "jbloggs", "permission": "maintain"}
        ]

        data = repo_data(portfolio, name="renamed", users=[("jbloggs", "admin")])
        data["users-INITIAL_FORMS"] = 1
        auth_client.post(f"{NEW_REPO}?draft={draft.pk}", data)

        draft.refresh_from_db()
        assert ChangeRequest.objects.count() == 1
        assert draft.target_name == "renamed"
        assert items_of(draft) == [(Operation.ADD, PrincipalType.USER, "jbloggs", None, "admin")]

    def test_another_users_draft_is_404(self, auth_client):
        draft = ChangeRequestFactory(action=Action.CREATE, target_name="theirs")

        assert auth_client.get(f"{NEW_REPO}?draft={draft.pk}").status_code == 404


class TestAddTeam:
    def test_creates_draft(self, auth_client, user, portfolio):
        data = team_data(
            portfolio,
            description="Tech leads",
            parent="platform-sre",
            members=[("jbloggs", "maintainer"), ("asmith", "member")],
        )

        response = auth_client.post(NEW_TEAM, data)

        change_request = ChangeRequest.objects.get()
        assert response.url == f"/requests/{change_request.pk}/confirm/"
        assert change_request.requested_by == user
        assert change_request.target_type == TargetType.TEAM
        assert change_request.target_name == "Platform Leads"
        assert change_request.action == Action.CREATE
        assert change_request.details == {
            "description": "Tech leads",
            "slug": "platform-leads",
            "parent_team": "platform-sre",
            "parent_team_id": github_teams.get_team_id("acme", "platform-sre"),
        }
        assert items_of(change_request) == [
            (Operation.ADD, PrincipalType.USER, "asmith", None, "member"),
            (Operation.ADD, PrincipalType.USER, "jbloggs", None, "maintainer"),
        ]
        assert change_request.summary_lines() == [
            "New team: Platform Leads (org: acme)",
            "  Description: Tech leads",
            "  Parent team: platform-sre",
            "  Add user asmith as member",
            "  Add user jbloggs as maintainer",
            "Portfolio: Digital Trade",
        ]

    def test_parent_description_and_members_are_optional(self, auth_client, portfolio):
        auth_client.post(NEW_TEAM, team_data(portfolio))

        change_request = ChangeRequest.objects.get()
        assert change_request.details == {"description": "", "slug": "platform-leads"}
        assert change_request.items.count() == 0

    def test_parent_choices_are_the_organisations_teams(self, auth_client):
        form = auth_client.get(NEW_TEAM).context["details_form"]

        assert [value for value, _ in form.fields["parent"].choices] == [
            "",
            "contractors",
            "data-engineering",
            "platform-sre",
            "platform-sre-oncall",
        ]

    @pytest.mark.parametrize(
        "name", ["Platform SRE", "platform sre", "platform-sre", "CONTRACTORS"]
    )
    def test_name_must_not_already_exist(self, auth_client, portfolio, name):
        response = auth_client.post(NEW_TEAM, team_data(portfolio, name=name))

        assert response.context["details_form"].errors["name"] == [
            f"A team called {name} already exists in acme."
        ]
        assert not ChangeRequest.objects.exists()

    @pytest.mark.parametrize("name", ["", "   ", "!!!"])
    def test_name_must_be_usable(self, auth_client, portfolio, name):
        response = auth_client.post(NEW_TEAM, team_data(portfolio, name=name))

        assert "name" in response.context["details_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_parent_must_be_an_existing_team(self, auth_client, portfolio):
        response = auth_client.post(NEW_TEAM, team_data(portfolio, parent="no-such-team"))

        assert "parent" in response.context["details_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_team_cannot_be_its_own_parent(self):
        # Unreachable through the page, because an existing team's name is rejected first,
        # so check the rule on the form with the name check out of the way.
        form = TeamDetailsForm({"name": "Platform SRE", "parent": "platform-sre"}, org="acme")
        form.clean_name = lambda: form.cleaned_data["name"]

        assert not form.is_valid()
        assert form.errors["parent"] == ["A team cannot be its own parent."]

    def test_role_must_be_a_team_role(self, auth_client, portfolio):
        response = auth_client.post(NEW_TEAM, team_data(portfolio, members=[("jbloggs", "admin")]))

        assert "permission" in response.context["member_formset"].forms[0].errors
        assert not ChangeRequest.objects.exists()

    def test_back_to_edit(self, auth_client, portfolio):
        auth_client.post(NEW_TEAM, team_data(portfolio, parent="platform-sre"))
        draft = ChangeRequest.objects.get()

        response = auth_client.get(draft.get_edit_url())

        assert draft.get_edit_url() == f"{NEW_TEAM}?draft={draft.pk}"
        assert response.context["details_form"].initial == {
            "name": "Platform Leads",
            "description": "",
            "parent": "platform-sre",
        }

        auth_client.post(draft.get_edit_url(), team_data(portfolio))
        draft.refresh_from_db()
        assert ChangeRequest.objects.count() == 1
        assert "parent_team" not in draft.details


class TestArchiveRepository:
    def test_creates_draft_without_items(self, auth_client, user, portfolio):
        response = auth_client.post(ARCHIVE, {"portfolio": portfolio.pk})

        change_request = ChangeRequest.objects.get()
        assert response.url == f"/requests/{change_request.pk}/confirm/"
        assert change_request.requested_by == user
        assert change_request.target_type == TargetType.REPOSITORY
        assert change_request.target_name == "trade-api"
        assert change_request.action == Action.ARCHIVE
        assert change_request.status == Status.DRAFT
        assert change_request.items.count() == 0
        assert change_request.summary_lines() == [
            "Archive repository: trade-api (org: acme)",
            "Portfolio: Digital Trade",
        ]

    def test_portfolio_is_required(self, auth_client):
        response = auth_client.post(ARCHIVE, {"portfolio": ""})

        assert response.status_code == 200
        assert "portfolio" in response.context["portfolio_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_unknown_repository_is_404(self, auth_client):
        assert auth_client.get("/orgs/acme/repos/nope/archive/").status_code == 404

    def test_archived_repository_cannot_be_archived_again(self, auth_client, portfolio):
        url = "/orgs/acme/repos/legacy-importer/archive/"

        for response in (auth_client.get(url), auth_client.post(url, {"portfolio": portfolio.pk})):
            assert response.status_code == 302
            assert response.url == "/orgs/acme/"
        assert "already archived" in str(list(get_messages(response.wsgi_request))[0])
        assert not ChangeRequest.objects.exists()

    def test_confirm_submit_and_back_to_edit(self, auth_client, portfolio):
        auth_client.post(ARCHIVE, {"portfolio": portfolio.pk})
        draft = ChangeRequest.objects.get()
        confirm_url = reverse("change_request_confirm", args=[draft.pk])

        assert f'href="{ARCHIVE}?draft={draft.pk}"'.encode() in auth_client.get(confirm_url).content
        back = auth_client.get(f"{ARCHIVE}?draft={draft.pk}")
        assert back.context["portfolio_form"].initial == {"portfolio": portfolio.pk}

        auth_client.post(confirm_url)
        draft.refresh_from_db()
        assert draft.status == Status.SUBMITTED

    def test_edit_draft_cannot_be_reused_as_archive(self, auth_client, user):
        draft = ChangeRequestFactory(requested_by=user)
        ChangeItemFactory(change_request=draft)

        assert auth_client.get(f"{ARCHIVE}?draft={draft.pk}").status_code == 404

    def test_other_users_cannot_confirm(self, client, auth_client, portfolio):
        auth_client.post(ARCHIVE, {"portfolio": portfolio.pk})
        draft = ChangeRequest.objects.get()
        client.force_login(UserFactory())

        assert client.get(reverse("change_request_confirm", args=[draft.pk])).status_code == 404
