import pytest
from django.contrib.messages import get_messages
from django.utils import timezone

from catalogue.services import github_teams, terraform_config
from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType
from change_requests.services import apply as apply_service
from tests.factories import (
    ApproverFactory,
    ChangeItemFactory,
    ChangeRequestFactory,
    PortfolioFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("writable_config")]

REPOS = "terraform/acme/repositories/config.yaml"


@pytest.fixture
def portfolio():
    return PortfolioFactory(name="Digital Trade")


@pytest.fixture
def approver(user, portfolio):
    ApproverFactory(portfolio=portfolio, user=user)
    return user


@pytest.fixture
def applying(settings):
    settings.APPLY_APPROVED_CHANGES = True


def request_for(portfolio, items=(), **kwargs):
    kwargs.setdefault("status", Status.SUBMITTED)
    kwargs.setdefault("submitted_at", timezone.now())
    change_request = ChangeRequestFactory(portfolio=portfolio, **kwargs)
    for operation, principal_type, name, old, new in items:
        ChangeItemFactory(
            change_request=change_request,
            operation=operation,
            principal_type=principal_type,
            principal_name=name,
            old_permission=old,
            new_permission=new,
        )
    return change_request


EDIT_ITEMS = [
    (Operation.ADD, PrincipalType.TEAM, "contractors", None, "pull"),
    (Operation.CHANGE, PrincipalType.USER, "jbloggs", "maintain", "admin"),
    (Operation.REMOVE, PrincipalType.USER, "old-contractor", "pull", None),
]


class TestApplyService:
    def test_modify_repository(self, portfolio):
        change_request = request_for(portfolio, EDIT_ITEMS)

        apply_service.apply(change_request)

        repo = terraform_config.get_repository("acme", "trade-api")
        assert repo.team_permissions["contractors"] == "pull"
        assert repo.user_permissions == {"jbloggs": "admin"}
        change_request.refresh_from_db()
        assert change_request.status == Status.APPLIED
        assert change_request.applied_at is not None
        assert "+        contractors: pull" in change_request.applied_diff
        assert "-        old-contractor: pull" in change_request.applied_diff

    def test_archive_repository(self, portfolio):
        apply_service.apply(request_for(portfolio, action=Action.ARCHIVE))

        assert terraform_config.get_repository("acme", "trade-api").archived is True

    def test_create_repository(self, portfolio):
        change_request = request_for(
            portfolio,
            [(Operation.ADD, PrincipalType.TEAM, "platform-sre", None, "admin")],
            action=Action.CREATE,
            target_name="new-service",
            details={"description": "A new service"},
        )

        apply_service.apply(change_request)

        repo = terraform_config.get_repository("acme", "new-service")
        assert repo.description == "A new service"
        assert repo.team_permissions == {"platform-sre": "admin"}

    def test_modify_team(self, portfolio):
        change_request = request_for(
            portfolio,
            [
                (Operation.ADD, PrincipalType.USER, "kpatel", None, "member"),
                (Operation.REMOVE, PrincipalType.USER, "asmith", "member", None),
            ],
            target_type=TargetType.TEAM,
            target_name="platform-sre",
        )

        apply_service.apply(change_request)

        assert terraform_config.get_team("acme", "platform-sre").members == {
            "jbloggs": "maintainer",
            "kpatel": "member",
        }

    def test_create_team_with_parent(self, portfolio):
        parent_id = github_teams.get_team_id("acme", "platform-sre")
        change_request = request_for(
            portfolio,
            [(Operation.ADD, PrincipalType.USER, "jbloggs", None, "maintainer")],
            action=Action.CREATE,
            target_type=TargetType.TEAM,
            target_name="Platform Leads",
            details={
                "description": "Tech leads",
                "slug": "platform-leads",
                "parent_team": "platform-sre",
                "parent_team_id": parent_id,
            },
        )

        apply_service.apply(change_request)

        team = terraform_config.get_team("acme", "platform-leads")
        assert team.name == "Platform Leads"
        assert team.description == "Tech leads"
        assert team.members == {"jbloggs": "maintainer"}
        assert github_teams.get_parent_team("acme", team).slug == "platform-sre"

    def test_create_team_without_stored_slug_derives_one(self, portfolio):
        change_request = request_for(
            portfolio, action=Action.CREATE, target_type=TargetType.TEAM, target_name="New Crew"
        )

        apply_service.apply(change_request)

        assert terraform_config.get_team("acme", "new-crew").name == "New Crew"

    def test_stale_request_is_not_marked_applied(self, portfolio):
        change_request = request_for(portfolio, EDIT_ITEMS, target_name="gone")

        with pytest.raises(apply_service.ConfigError):
            apply_service.apply(change_request)

        change_request.refresh_from_db()
        assert change_request.status == Status.SUBMITTED
        assert change_request.applied_at is None

    def test_build_edit_does_not_write(self, portfolio, writable_config):
        before = (writable_config / REPOS).read_text()

        edit = apply_service.build_edit(request_for(portfolio, EDIT_ITEMS))

        assert edit.changed
        assert (writable_config / REPOS).read_text() == before


class TestApproval:
    def url(self, change_request):
        return f"/approvals/{change_request.pk}/"

    def test_page_previews_the_yaml_change(self, auth_client, approver, portfolio):
        change_request = request_for(portfolio, EDIT_ITEMS)

        response = auth_client.get(self.url(change_request))
        html = response.content.decode()

        assert "What approving will change in the YAML" in html
        assert "+        contractors: pull" in response.context["preview_diff"]
        assert "+        contractors: pull" in html
        assert "a/terraform/acme/repositories/config.yaml" in html

    def test_page_warns_when_the_request_no_longer_fits(self, auth_client, approver, portfolio):
        change_request = request_for(portfolio, EDIT_ITEMS, target_name="gone")

        html = auth_client.get(self.url(change_request)).content.decode()

        assert "This request no longer fits the YAML config" in html
        assert "gone is no longer in the config for acme" in html

    def test_page_says_when_there_is_nothing_left_to_change(self, auth_client, approver, portfolio):
        change_request = request_for(
            portfolio, [(Operation.REMOVE, PrincipalType.USER, "nobody", "pull", None)]
        )

        html = auth_client.get(self.url(change_request)).content.decode()

        assert "already matches this request" in html

    def test_approving_writes_the_yaml(
        self, auth_client, approver, portfolio, applying, writable_config
    ):
        change_request = request_for(portfolio, EDIT_ITEMS)

        response = auth_client.post(self.url(change_request), {"decision": "approve"})

        change_request.refresh_from_db()
        assert change_request.status == Status.APPLIED
        assert change_request.decided_by == approver
        assert change_request.applied_at is not None
        assert "contractors: pull" in (writable_config / REPOS).read_text()
        message = str(list(get_messages(response.wsgi_request))[0])
        assert "The YAML config has been updated." in message
        assert auth_client.get("/orgs/acme/repos/trade-api/edit/").status_code == 200

    def test_approving_without_the_setting_leaves_the_yaml_alone(
        self, auth_client, approver, portfolio, writable_config
    ):
        before = (writable_config / REPOS).read_text()
        change_request = request_for(portfolio, EDIT_ITEMS)

        auth_client.post(self.url(change_request), {"decision": "approve"})

        change_request.refresh_from_db()
        assert change_request.status == Status.APPROVED
        assert (writable_config / REPOS).read_text() == before
        assert b"Apply to YAML" not in auth_client.get(self.url(change_request)).content

    def test_rejecting_never_writes(
        self, auth_client, approver, portfolio, applying, writable_config
    ):
        before = (writable_config / REPOS).read_text()
        change_request = request_for(portfolio, EDIT_ITEMS)

        auth_client.post(self.url(change_request), {"decision": "reject", "comment": "No"})

        change_request.refresh_from_db()
        assert change_request.status == Status.REJECTED
        assert (writable_config / REPOS).read_text() == before

    def test_approval_stands_when_the_yaml_cannot_be_updated(
        self, auth_client, approver, portfolio, applying
    ):
        change_request = request_for(
            portfolio, action=Action.CREATE, target_name="trade-api"
        )  # already exists

        response = auth_client.post(self.url(change_request), {"decision": "approve"})

        change_request.refresh_from_db()
        assert change_request.status == Status.APPROVED
        message = str(list(get_messages(response.wsgi_request))[0])
        assert "The YAML was not updated" in message
        assert "trade-api already exists in acme" in message

    def test_approved_request_can_be_applied_later(
        self, auth_client, approver, portfolio, applying
    ):
        change_request = request_for(
            portfolio, EDIT_ITEMS, status=Status.APPROVED, decided_at=timezone.now()
        )

        page = auth_client.get(self.url(change_request)).content.decode()
        response = auth_client.post(f"{self.url(change_request)}apply/")

        change_request.refresh_from_db()
        assert "Apply to YAML" in page
        assert "Change waiting to be made to the YAML" in page
        assert response.url == self.url(change_request)
        assert change_request.status == Status.APPLIED
        assert terraform_config.get_repository("acme", "trade-api").user_permissions == {
            "jbloggs": "admin"
        }

    def test_failed_retry_keeps_the_request_approved(
        self, auth_client, approver, portfolio, applying
    ):
        change_request = request_for(portfolio, target_name="gone", status=Status.APPROVED)

        response = auth_client.post(f"{self.url(change_request)}apply/")

        change_request.refresh_from_db()
        assert change_request.status == Status.APPROVED
        assert "The YAML was not updated" in str(list(get_messages(response.wsgi_request))[0])

    @pytest.mark.parametrize("status", [Status.SUBMITTED, Status.REJECTED, Status.APPLIED])
    def test_only_approved_requests_can_be_applied(
        self, auth_client, approver, portfolio, applying, status
    ):
        change_request = request_for(portfolio, EDIT_ITEMS, status=status)

        assert auth_client.post(f"{self.url(change_request)}apply/").status_code == 404

    def test_apply_needs_the_setting(self, auth_client, approver, portfolio):
        change_request = request_for(portfolio, EDIT_ITEMS, status=Status.APPROVED)

        assert auth_client.post(f"{self.url(change_request)}apply/").status_code == 404

    def test_apply_is_for_the_portfolios_approvers_only(self, auth_client, portfolio, applying):
        change_request = request_for(portfolio, EDIT_ITEMS, status=Status.APPROVED)

        assert auth_client.post(f"{self.url(change_request)}apply/").status_code == 404
        assert auth_client.get(f"{self.url(change_request)}apply/").status_code == 405

    def test_applied_request_shows_the_diff_to_approver_and_requester(
        self, client, approver, portfolio, applying
    ):
        requester = UserFactory()
        change_request = request_for(portfolio, EDIT_ITEMS, requested_by=requester)
        client.force_login(approver)
        client.post(self.url(change_request), {"decision": "approve"})

        approver_page = client.get(self.url(change_request)).content.decode()
        completed = client.get("/approvals/").content.decode()
        client.force_login(requester)
        requester_page = client.get(f"/requests/{change_request.pk}/").content.decode()

        for html in (approver_page, requester_page):
            assert "Change made to the YAML" in html
            assert "+        contractors: pull" in html
            assert "Applied to YAML" in html
            assert "Approved by" in html
        assert "What approving will change" not in approver_page
        assert "text-bg-primary" in completed
