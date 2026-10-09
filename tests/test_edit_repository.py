import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType
from change_requests.models import ChangeRequest
from tests.factories import ChangeItemFactory, ChangeRequestFactory, PortfolioFactory, UserFactory
from tests.helpers import formset_data

pytestmark = pytest.mark.django_db

URL = "/orgs/acme/repos/trade-api/edit/"

# trade-api in the fixture tree.
CURRENT_TEAMS = [("platform-sre", "admin"), ("data-engineering", "push")]
CURRENT_USERS = [("jbloggs", "maintain"), ("old-contractor", "pull")]


@pytest.fixture
def portfolio():
    return PortfolioFactory(name="Digital Trade")


def post_data(portfolio, teams=CURRENT_TEAMS, users=CURRENT_USERS, team_initial=2, user_initial=2):
    return {
        **formset_data("teams", teams, team_initial),
        **formset_data("users", users, user_initial),
        "portfolio": portfolio.pk if portfolio else "",
    }


def items_of(change_request):
    return [
        (i.operation, i.principal_type, i.principal_name, i.old_permission, i.new_permission)
        for i in change_request.items.all()
    ]


class TestGet:
    def test_requires_login(self, client):
        assert client.get(URL).url == f"/login/?next={URL}"

    @pytest.mark.parametrize(
        "url",
        ["/orgs/nope/repos/trade-api/edit/", "/orgs/acme/repos/nope/edit/"],
    )
    def test_unknown_org_or_repo_is_404(self, auth_client, url):
        assert auth_client.get(url).status_code == 404

    def test_archived_repository_cannot_be_edited(self, auth_client, portfolio):
        url = "/orgs/acme/repos/legacy-importer/edit/"

        for response in (auth_client.get(url), auth_client.post(url, post_data(portfolio))):
            assert response.status_code == 302
            assert response.url == "/orgs/acme/"
        assert "archived and cannot be edited" in str(list(get_messages(response.wsgi_request))[0])
        assert not ChangeRequest.objects.exists()

    def test_form_is_prepopulated_from_yaml(self, auth_client):
        response = auth_client.get(URL)

        assert response.status_code == 200
        teams = [f.initial for f in response.context["team_formset"]]
        users = [f.initial for f in response.context["user_formset"]]
        assert teams == [
            {"principal": "platform-sre", "permission": "admin"},
            {"principal": "data-engineering", "permission": "push"},
        ]
        assert users == [
            {"principal": "jbloggs", "permission": "maintain"},
            {"principal": "old-contractor", "permission": "pull"},
        ]

    def test_team_choices_are_the_organisations_teams(self, auth_client):
        form = auth_client.get(URL).context["team_formset"].empty_form

        assert [value for value, _ in form.fields["principal"].choices] == [
            "",
            "contractors",
            "data-engineering",
            "platform-sre",
            "platform-sre-oncall",
        ]
        assert [value for value, _ in form.fields["permission"].choices] == [
            "",
            "pull",
            "triage",
            "push",
            "maintain",
            "admin",
        ]

    def test_existing_usernames_unknown_to_github_stub_stay_selectable(
        self, auth_client, monkeypatch
    ):
        monkeypatch.setattr("change_requests.views.list_usernames", lambda: ["someone-else"])

        form = auth_client.get(URL).context["user_formset"].empty_form

        assert [value for value, _ in form.fields["principal"].choices] == [
            "",
            "someone-else",
            "jbloggs",
            "old-contractor",
        ]

    def test_page_has_dynamic_row_hooks(self, auth_client, portfolio):
        html = auth_client.get(URL).content.decode()

        assert html.count("data-formset-prefix=") == 2
        assert html.count("<template data-formset-template>") == 2
        assert "teams-__prefix__-principal" in html
        assert "js/formset.js" in html
        assert ">Add team</button>" in html
        assert ">Add user</button>" in html
        assert "Digital Trade" in html

    def test_repository_without_collaborators(self, auth_client):
        response = auth_client.get("/orgs/acme/repos/design-docs/edit/")

        assert response.status_code == 200
        assert len(response.context["team_formset"].forms) == 0


class TestPost:
    def test_creates_draft_with_diff_items(self, auth_client, user, portfolio):
        data = post_data(
            portfolio,
            teams=[*CURRENT_TEAMS, ("contractors", "pull")],
            users=[("jbloggs", "admin"), ("old-contractor", "pull", True)],
        )

        response = auth_client.post(URL, data)

        change_request = ChangeRequest.objects.get()
        assert response.status_code == 302
        assert response.url == f"/requests/{change_request.pk}/confirm/"
        assert change_request.requested_by == user
        assert change_request.organisation == "acme"
        assert change_request.target_type == TargetType.REPOSITORY
        assert change_request.target_name == "trade-api"
        assert change_request.action == Action.MODIFY
        assert change_request.portfolio == portfolio
        assert change_request.status == Status.DRAFT
        assert change_request.submitted_at is None
        assert items_of(change_request) == [
            (Operation.ADD, PrincipalType.TEAM, "contractors", None, "pull"),
            (Operation.CHANGE, PrincipalType.USER, "jbloggs", "maintain", "admin"),
            (Operation.REMOVE, PrincipalType.USER, "old-contractor", "pull", None),
        ]

    def test_blank_added_rows_are_ignored(self, auth_client, portfolio):
        data = post_data(
            portfolio,
            teams=[*CURRENT_TEAMS, ("", "")],
            users=[*CURRENT_USERS, ("asmith", "triage"), ("", "")],
        )

        auth_client.post(URL, data)

        assert items_of(ChangeRequest.objects.get()) == [
            (Operation.ADD, PrincipalType.USER, "asmith", None, "triage"),
        ]

    def test_added_then_deleted_row_is_ignored(self, auth_client, portfolio):
        data = post_data(
            portfolio,
            teams=[*CURRENT_TEAMS, ("contractors", "", True)],
            users=[("jbloggs", "maintain", True), ("old-contractor", "pull")],
        )

        auth_client.post(URL, data)

        assert items_of(ChangeRequest.objects.get()) == [
            (Operation.REMOVE, PrincipalType.USER, "jbloggs", "maintain", None),
        ]

    def test_no_changes_is_an_error(self, auth_client, portfolio):
        response = auth_client.post(URL, post_data(portfolio))

        assert response.status_code == 200
        assert response.context["errors"] == ["No changes made."]
        assert b"No changes made." in response.content
        assert not ChangeRequest.objects.exists()

    def test_remove_and_re_add_with_same_permission_is_no_change(self, auth_client, portfolio):
        data = post_data(
            portfolio,
            users=[
                ("jbloggs", "maintain", True),
                ("old-contractor", "pull"),
                ("jbloggs", "maintain"),
            ],
        )

        response = auth_client.post(URL, data)

        assert response.context["errors"] == ["No changes made."]

    def test_duplicate_principal_is_an_error(self, auth_client, portfolio):
        data = post_data(portfolio, users=[*CURRENT_USERS, ("jbloggs", "admin")])

        response = auth_client.post(URL, data)

        assert response.status_code == 200
        assert response.context["user_formset"].non_form_errors() == [
            "jbloggs is listed more than once."
        ]
        assert b"jbloggs is listed more than once." in response.content
        assert not ChangeRequest.objects.exists()

    @pytest.mark.parametrize(
        "row, field",
        [
            (("asmith", "owner"), "permission"),
            (("asmith", ""), "permission"),
            (("not-a-known-user", "push"), "principal"),
            (("", "push"), "principal"),
        ],
    )
    def test_invalid_row_is_an_error(self, auth_client, portfolio, row, field):
        response = auth_client.post(URL, post_data(portfolio, users=[*CURRENT_USERS, row]))

        assert response.status_code == 200
        assert field in response.context["user_formset"].forms[2].errors
        assert not ChangeRequest.objects.exists()

    def test_unknown_team_is_an_error(self, auth_client, portfolio):
        data = post_data(portfolio, teams=[*CURRENT_TEAMS, ("no-such-team", "pull")])

        response = auth_client.post(URL, data)

        assert "principal" in response.context["team_formset"].forms[2].errors
        assert not ChangeRequest.objects.exists()

    def test_portfolio_is_required(self, auth_client):
        data = post_data(None, users=[("jbloggs", "admin"), ("old-contractor", "pull")])

        response = auth_client.post(URL, data)

        assert response.status_code == 200
        assert "portfolio" in response.context["portfolio_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_submitted_values_are_redisplayed_after_an_error(self, auth_client):
        data = post_data(None, users=[("jbloggs", "admin"), ("old-contractor", "pull")])

        response = auth_client.post(URL, data)

        assert response.context["user_formset"].forms[0]["permission"].value() == "admin"


class TestConfirm:
    @pytest.fixture
    def draft(self, user, portfolio):
        draft = ChangeRequestFactory(requested_by=user, portfolio=portfolio)
        ChangeItemFactory(
            change_request=draft,
            operation=Operation.CHANGE,
            principal_name="jbloggs",
            old_permission="maintain",
            new_permission="admin",
        )
        ChangeItemFactory(
            change_request=draft,
            operation=Operation.ADD,
            principal_type=PrincipalType.TEAM,
            principal_name="contractors",
            new_permission="pull",
        )
        ChangeItemFactory(
            change_request=draft,
            operation=Operation.REMOVE,
            principal_name="old-contractor",
            old_permission="pull",
            new_permission=None,
        )
        return draft

    def url(self, draft):
        return reverse("change_request_confirm", args=[draft.pk])

    def test_shows_summary_and_actions(self, auth_client, draft):
        response = auth_client.get(self.url(draft))
        html = response.content.decode()

        assert response.status_code == 200
        assert response.context["summary_lines"] == [
            "Repository: trade-api (org: acme)",
            "  Change user jbloggs: maintain → admin",
            "  Add team contractors with pull",
            "  Remove user old-contractor",
            "Portfolio: Digital Trade",
        ]
        assert "Change user jbloggs: maintain → admin" in html
        assert "Submit request" in html
        assert f'href="/orgs/acme/repos/trade-api/edit/?draft={draft.pk}"' in html

    def test_submit(self, auth_client, draft):
        response = auth_client.post(self.url(draft))

        draft.refresh_from_db()
        assert response.status_code == 302
        assert draft.status == Status.SUBMITTED
        assert draft.submitted_at is not None
        assert "has been submitted" in str(list(get_messages(response.wsgi_request))[0])

    def test_submitted_request_cannot_be_confirmed_again(self, auth_client, draft):
        auth_client.post(self.url(draft))
        submitted_at = ChangeRequest.objects.get().submitted_at

        assert auth_client.get(self.url(draft)).status_code == 404
        assert auth_client.post(self.url(draft)).status_code == 404
        assert ChangeRequest.objects.get().submitted_at == submitted_at

    def test_other_users_cannot_view_or_submit(self, client, draft):
        client.force_login(UserFactory())

        assert client.get(self.url(draft)).status_code == 404
        assert client.post(self.url(draft)).status_code == 404
        draft.refresh_from_db()
        assert draft.status == Status.DRAFT

    def test_requires_login(self, client, draft):
        assert client.get(self.url(draft)).status_code == 302
        assert client.post(self.url(draft)).status_code == 302
        draft.refresh_from_db()
        assert draft.status == Status.DRAFT

    def test_unknown_request_is_404(self, auth_client):
        assert auth_client.get("/requests/999999/confirm/").status_code == 404

    def test_back_to_edit_is_prepopulated_from_the_draft(self, auth_client, draft):
        response = auth_client.get(f"{URL}?draft={draft.pk}")

        teams = {
            f.initial["principal"]: f.initial["permission"]
            for f in response.context["team_formset"]
        }
        users = {
            f.initial["principal"]: f.initial["permission"]
            for f in response.context["user_formset"]
        }
        assert teams == {"platform-sre": "admin", "data-engineering": "push", "contractors": "pull"}
        assert users == {"jbloggs": "admin"}
        assert response.context["portfolio_form"].initial == {"portfolio": draft.portfolio_id}

    def test_resaving_updates_the_same_draft(self, auth_client, draft):
        other_portfolio = PortfolioFactory()
        data = post_data(
            other_portfolio,
            teams=[*CURRENT_TEAMS, ("contractors", "pull", True)],
            users=[("jbloggs", "admin")],
            team_initial=3,
            user_initial=1,
        )

        response = auth_client.post(f"{URL}?draft={draft.pk}", data)

        assert response.url == self.url(draft)
        assert ChangeRequest.objects.count() == 1
        draft.refresh_from_db()
        assert draft.portfolio == other_portfolio
        assert items_of(draft) == [
            (Operation.CHANGE, PrincipalType.USER, "jbloggs", "maintain", "admin"),
            (Operation.REMOVE, PrincipalType.USER, "old-contractor", "pull", None),
        ]

    def test_undoing_every_change_in_a_draft_is_no_change(self, auth_client, draft):
        response = auth_client.post(
            f"{URL}?draft={draft.pk}", post_data(draft.portfolio, team_initial=3, user_initial=1)
        )

        assert response.context["errors"] == ["No changes made."]
        assert draft.items.count() == 3

    @pytest.mark.parametrize("case", ["other-user", "other-repo", "submitted", "garbage"])
    def test_draft_that_is_not_usable_is_404(self, auth_client, draft, case):
        draft_id = draft.pk
        if case == "other-user":
            draft.requested_by = UserFactory()
        elif case == "other-repo":
            draft.target_name = "design-docs"
        elif case == "submitted":
            draft.status = Status.SUBMITTED
        else:
            draft_id = "abc"
        draft.save()

        assert auth_client.get(f"{URL}?draft={draft_id}").status_code == 404
