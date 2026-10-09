import pytest
from django.urls import reverse

from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType
from change_requests.models import ChangeRequest
from tests.factories import ChangeItemFactory, ChangeRequestFactory, PortfolioFactory, UserFactory
from tests.helpers import formset_data

pytestmark = pytest.mark.django_db

URL = "/orgs/acme/teams/platform-sre/edit/"

# platform-sre in the fixture tree.
CURRENT = [("jbloggs", "maintainer"), ("asmith", "member")]


@pytest.fixture
def portfolio():
    return PortfolioFactory(name="Platform")


def post_data(portfolio, members=CURRENT, initial=2):
    return {
        **formset_data("members", members, initial),
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
        "url", ["/orgs/nope/teams/platform-sre/edit/", "/orgs/acme/teams/nope/edit/"]
    )
    def test_unknown_org_or_team_is_404(self, auth_client, url):
        assert auth_client.get(url).status_code == 404

    def test_form_is_prepopulated_from_yaml(self, auth_client):
        response = auth_client.get(URL)

        assert response.status_code == 200
        assert [f.initial for f in response.context["member_formset"]] == [
            {"principal": "jbloggs", "permission": "maintainer"},
            {"principal": "asmith", "permission": "member"},
        ]
        assert b"Edit members: Platform SRE" in response.content

    def test_role_choices(self, auth_client):
        form = auth_client.get(URL).context["member_formset"].empty_form

        assert [value for value, _ in form.fields["permission"].choices] == [
            "",
            "member",
            "maintainer",
        ]

    def test_page_has_dynamic_row_hooks(self, auth_client):
        html = auth_client.get(URL).content.decode()

        assert 'data-formset-prefix="members"' in html
        assert "members-__prefix__-principal" in html
        assert "js/formset.js" in html
        assert ">Add member</button>" in html

    def test_team_without_members(self, auth_client):
        response = auth_client.get("/orgs/acme/teams/contractors/edit/")

        assert response.status_code == 200
        assert len(response.context["member_formset"].forms) == 0

    def test_linked_from_organisation_page(self, auth_client):
        assert f'href="{URL}"'.encode() in auth_client.get("/orgs/acme/").content


class TestPost:
    def test_creates_draft_with_diff_items(self, auth_client, user, portfolio):
        members = [("jbloggs", "member"), ("asmith", "member", True), ("kpatel", "maintainer")]

        response = auth_client.post(URL, post_data(portfolio, members))

        change_request = ChangeRequest.objects.get()
        assert response.url == f"/requests/{change_request.pk}/confirm/"
        assert change_request.requested_by == user
        assert change_request.organisation == "acme"
        assert change_request.target_type == TargetType.TEAM
        assert change_request.target_name == "platform-sre"
        assert change_request.action == Action.MODIFY
        assert change_request.portfolio == portfolio
        assert change_request.status == Status.DRAFT
        assert items_of(change_request) == [
            (Operation.ADD, PrincipalType.USER, "kpatel", None, "maintainer"),
            (Operation.CHANGE, PrincipalType.USER, "jbloggs", "maintainer", "member"),
            (Operation.REMOVE, PrincipalType.USER, "asmith", "member", None),
        ]

    def test_no_changes_is_an_error(self, auth_client, portfolio):
        response = auth_client.post(URL, post_data(portfolio))

        assert response.context["errors"] == ["No changes made."]
        assert not ChangeRequest.objects.exists()

    def test_duplicate_member_is_an_error(self, auth_client, portfolio):
        response = auth_client.post(URL, post_data(portfolio, [*CURRENT, ("asmith", "maintainer")]))

        assert response.context["member_formset"].non_form_errors() == [
            "asmith is listed more than once."
        ]
        assert not ChangeRequest.objects.exists()

    @pytest.mark.parametrize("role", ["admin", "push", ""])
    def test_role_must_be_a_team_role(self, auth_client, portfolio, role):
        response = auth_client.post(URL, post_data(portfolio, [*CURRENT, ("kpatel", role)]))

        assert "permission" in response.context["member_formset"].forms[2].errors
        assert not ChangeRequest.objects.exists()

    def test_portfolio_is_required(self, auth_client):
        response = auth_client.post(URL, post_data(None, [*CURRENT, ("kpatel", "member")]))

        assert "portfolio" in response.context["portfolio_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_first_members_of_an_empty_team(self, auth_client, portfolio):
        data = post_data(portfolio, [("kpatel", "member")], initial=0)

        auth_client.post("/orgs/acme/teams/contractors/edit/", data)

        assert items_of(ChangeRequest.objects.get()) == [
            (Operation.ADD, PrincipalType.USER, "kpatel", None, "member"),
        ]


class TestConfirmAndBackToEdit:
    @pytest.fixture
    def draft(self, user, portfolio):
        draft = ChangeRequestFactory(
            requested_by=user,
            portfolio=portfolio,
            target_type=TargetType.TEAM,
            target_name="platform-sre",
        )
        ChangeItemFactory(change_request=draft, principal_name="kpatel", new_permission="member")
        ChangeItemFactory(
            change_request=draft,
            operation=Operation.REMOVE,
            principal_name="asmith",
            old_permission="member",
            new_permission=None,
        )
        return draft

    def test_confirm_page(self, auth_client, draft):
        response = auth_client.get(reverse("change_request_confirm", args=[draft.pk]))

        assert response.context["summary_lines"] == [
            "Team: platform-sre (org: acme)",
            "  Add user kpatel as member",
            "  Remove user asmith",
            "Portfolio: Platform",
        ]
        assert f'href="{URL}?draft={draft.pk}"'.encode() in response.content

    def test_submit(self, auth_client, draft):
        auth_client.post(reverse("change_request_confirm", args=[draft.pk]))

        draft.refresh_from_db()
        assert draft.status == Status.SUBMITTED
        assert draft.submitted_at is not None

    def test_back_to_edit_is_prepopulated_from_the_draft(self, auth_client, draft):
        response = auth_client.get(f"{URL}?draft={draft.pk}")

        assert [f.initial for f in response.context["member_formset"]] == [
            {"principal": "jbloggs", "permission": "maintainer"},
            {"principal": "kpatel", "permission": "member"},
        ]

    def test_resaving_updates_the_same_draft(self, auth_client, draft):
        members = [("jbloggs", "maintainer"), ("kpatel", "maintainer")]

        response = auth_client.post(f"{URL}?draft={draft.pk}", post_data(draft.portfolio, members))

        assert response.url == f"/requests/{draft.pk}/confirm/"
        assert ChangeRequest.objects.count() == 1
        assert items_of(draft) == [
            (Operation.ADD, PrincipalType.USER, "kpatel", None, "maintainer"),
            (Operation.REMOVE, PrincipalType.USER, "asmith", "member", None),
        ]

    def test_repository_draft_cannot_be_used_on_a_team_form(self, auth_client, user):
        repo_draft = ChangeRequestFactory(requested_by=user, target_name="platform-sre")

        assert auth_client.get(f"{URL}?draft={repo_draft.pk}").status_code == 404

    def test_another_users_draft_is_404(self, client, draft):
        client.force_login(UserFactory())

        assert client.get(f"{URL}?draft={draft.pk}").status_code == 404
