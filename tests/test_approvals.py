from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.utils import timezone

from change_requests.choices import Operation, Status
from portfolios.models import Portfolio, portfolios_approved_by
from tests.factories import (
    ApproverFactory,
    ChangeItemFactory,
    ChangeRequestFactory,
    PortfolioFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

LIST = "/approvals/"


@pytest.fixture
def portfolio():
    return PortfolioFactory(name="Digital Trade")


@pytest.fixture
def approver(user, portfolio):
    """The signed-in user, linked to an approver entry for the portfolio."""
    ApproverFactory(portfolio=portfolio, user=user)
    return user


def submitted(portfolio, **kwargs):
    kwargs.setdefault("submitted_at", timezone.now())
    kwargs.setdefault("status", Status.SUBMITTED)
    return ChangeRequestFactory(portfolio=portfolio, **kwargs)


def decided(portfolio, status=Status.APPROVED, **kwargs):
    kwargs.setdefault("decided_at", timezone.now())
    kwargs.setdefault("decided_by", UserFactory())
    return submitted(portfolio, **kwargs | {"status": status})


class TestWhoIsAnApprover:
    def test_linked_user_approves_the_portfolio(self, user, portfolio):
        ApproverFactory(portfolio=portfolio, user=user, email="a.different.address@example.com")

        assert list(portfolios_approved_by(user)) == [portfolio]

    def test_matching_contact_email_alone_is_not_enough(self, user, portfolio):
        ApproverFactory(portfolio=portfolio, email=user.email)

        assert not portfolios_approved_by(user).exists()

    def test_anonymous_user_approves_nothing(self, portfolio):
        ApproverFactory(portfolio=portfolio)

        assert not portfolios_approved_by(AnonymousUser()).exists()

    def test_several_portfolios_listed_once_each(self, user):
        first, second = PortfolioFactory(name="A"), PortfolioFactory(name="B")
        ApproverFactory(portfolio=first, user=user)
        ApproverFactory(portfolio=second, user=user)
        ApproverFactory(portfolio=second, user=UserFactory())

        assert list(portfolios_approved_by(user)) == [first, second]

    def test_same_user_cannot_be_linked_twice_to_one_portfolio(self, user, portfolio):
        ApproverFactory(portfolio=portfolio, user=user)

        with pytest.raises(IntegrityError):
            ApproverFactory(portfolio=portfolio, user=user)

    def test_unlinked_approvers_can_share_a_portfolio(self, portfolio):
        ApproverFactory.create_batch(2, portfolio=portfolio)

        assert portfolio.approvers.count() == 2

    def test_deleting_the_user_keeps_the_approver_as_a_contact(self, portfolio):
        approver = ApproverFactory(portfolio=portfolio, user=UserFactory())

        approver.user.delete()

        approver.refresh_from_db()
        assert approver.user is None

    @pytest.mark.parametrize("identifier", ["email_user_id", "email"])
    def test_seed_command_links_a_user_everywhere(self, user, identifier):
        value = getattr(user, identifier).upper()

        call_command("seed_portfolios", approver=value)
        call_command("seed_portfolios", approver=value)

        assert portfolios_approved_by(user).count() == Portfolio.objects.count() == 4
        assert user.approver_roles.count() == 4

    def test_seed_command_rejects_an_unknown_user(self):
        with pytest.raises(CommandError, match="No user"):
            call_command("seed_portfolios", approver="nobody@example.com")

    def test_seed_command_rejects_an_ambiguous_email(self):
        UserFactory.create_batch(2, email="shared@example.com")

        with pytest.raises(CommandError, match="More than one user"):
            call_command("seed_portfolios", approver="shared@example.com")

    def test_admin_can_link_and_search_users(self, client, portfolio):
        client.force_login(UserFactory(is_staff=True, is_superuser=True))
        ApproverFactory(portfolio=portfolio, user=UserFactory(email="linked@example.com"))

        assert client.get(f"/admin/portfolios/portfolio/{portfolio.pk}/change/").status_code == 200
        listing = client.get("/admin/portfolios/approver/?q=linked@example.com")
        assert listing.status_code == 200
        assert b"linked@example.com" in listing.content


class TestRequesterSeesApprovers:
    def test_confirm_and_detail_list_contact_emails(self, auth_client, user, portfolio):
        ApproverFactory(portfolio=portfolio, name="Priya Shah", email="priya.contact@example.com")
        draft = ChangeRequestFactory(requested_by=user, portfolio=portfolio)

        confirm = auth_client.get(f"/requests/{draft.pk}/confirm/").content.decode()
        auth_client.post(f"/requests/{draft.pk}/confirm/")
        detail = auth_client.get(f"/requests/{draft.pk}/").content.decode()

        for html in (confirm, detail):
            assert "Priya Shah" in html
            assert "mailto:priya.contact@example.com" in html

    def test_portfolio_without_approvers(self, auth_client, user, portfolio):
        draft = ChangeRequestFactory(requested_by=user, portfolio=portfolio)

        html = auth_client.get(f"/requests/{draft.pk}/confirm/").content.decode()

        assert "This portfolio has no approvers yet." in html


class TestNavbar:
    def test_link_hidden_from_non_approvers(self, auth_client):
        assert b'href="/approvals/"' not in auth_client.get("/").content

    def test_link_shows_count_waiting(self, auth_client, approver, portfolio):
        submitted(portfolio)
        submitted(portfolio)
        submitted(portfolio, requested_by=approver)  # own request: someone else decides
        decided(portfolio)
        submitted(PortfolioFactory())

        response = auth_client.get("/")

        assert b'href="/approvals/"' in response.content
        assert response.context["approvals_waiting"] == 2

    def test_no_badge_when_nothing_waiting(self, auth_client, approver):
        response = auth_client.get("/")

        assert response.context["approvals_waiting"] == 0
        assert b"text-bg-warning" not in response.content


class TestList:
    def test_requires_login(self, client):
        assert client.get(LIST).url == f"/login/?next={LIST}"

    def test_non_approver_sees_explanation(self, auth_client, portfolio):
        submitted(portfolio)

        response = auth_client.get(LIST)

        assert response.status_code == 200
        assert b"You are not an approver for any portfolio" in response.content
        assert list(response.context["open_requests"]) == []

    def test_open_and_completed_for_own_portfolios_only(self, auth_client, approver, portfolio):
        waiting = submitted(portfolio)
        approved = decided(portfolio)
        rejected = decided(portfolio, status=Status.REJECTED)
        ChangeRequestFactory(portfolio=portfolio)  # draft
        submitted(PortfolioFactory())  # another portfolio
        decided(PortfolioFactory())

        response = auth_client.get(LIST)

        assert list(response.context["open_requests"]) == [waiting]
        assert set(response.context["completed_requests"]) == {approved, rejected}

    def test_open_oldest_first_and_completed_newest_first(self, auth_client, approver, portfolio):
        now = timezone.now()
        newer = submitted(portfolio, submitted_at=now)
        older = submitted(portfolio, submitted_at=now - timedelta(days=3))
        done_early = decided(portfolio, decided_at=now - timedelta(days=2))
        done_late = decided(portfolio, decided_at=now)

        response = auth_client.get(LIST)

        assert list(response.context["open_requests"]) == [older, newer]
        assert list(response.context["completed_requests"]) == [done_late, done_early]

    def test_rows_and_empty_states(self, auth_client, approver, portfolio):
        html = auth_client.get(LIST).content.decode()
        assert "Nothing is waiting for approval." in html
        assert "No requests have been approved or rejected yet." in html

        requester = UserFactory(first_name="Jo", last_name="Bloggs")
        change_request = submitted(portfolio, requested_by=requester)
        html = auth_client.get(LIST).content.decode()

        assert f'href="/approvals/{change_request.pk}/"' in html
        for text in ("Jo Bloggs", "acme", "Modify repository trade-api", "Digital Trade"):
            assert text in html


class TestDetailAndDecision:
    @pytest.fixture
    def change_request(self, portfolio):
        change_request = submitted(portfolio)
        ChangeItemFactory(
            change_request=change_request,
            operation=Operation.CHANGE,
            principal_name="jbloggs",
            old_permission="push",
            new_permission="admin",
        )
        return change_request

    def url(self, change_request):
        return f"/approvals/{change_request.pk}/"

    def test_shows_summary_and_decision_buttons(self, auth_client, approver, change_request):
        response = auth_client.get(self.url(change_request))
        html = response.content.decode()

        assert response.status_code == 200
        assert "Change user jbloggs: push → admin" in html
        assert 'value="approve"' in html
        assert 'value="reject"' in html

    def test_approve(self, auth_client, approver, change_request):
        response = auth_client.post(
            self.url(change_request), {"decision": "approve", "comment": "Looks fine"}
        )

        change_request.refresh_from_db()
        assert response.url == LIST
        assert change_request.status == Status.APPROVED
        assert change_request.decided_by == approver
        assert change_request.decided_at is not None
        assert change_request.decision_comment == "Looks fine"
        assert "You approved the request" in str(list(get_messages(response.wsgi_request))[0])

    def test_approve_without_comment(self, auth_client, approver, change_request):
        auth_client.post(self.url(change_request), {"decision": "approve"})

        change_request.refresh_from_db()
        assert change_request.status == Status.APPROVED
        assert change_request.decision_comment == ""

    def test_reject_requires_a_comment(self, auth_client, approver, change_request):
        response = auth_client.post(
            self.url(change_request), {"decision": "reject", "comment": "  "}
        )

        change_request.refresh_from_db()
        assert response.status_code == 200
        assert response.context["form"].errors["comment"] == [
            "Say why you are rejecting this request."
        ]
        assert change_request.status == Status.SUBMITTED

    def test_reject(self, auth_client, approver, change_request):
        auth_client.post(self.url(change_request), {"decision": "reject", "comment": "Wrong team"})

        change_request.refresh_from_db()
        assert change_request.status == Status.REJECTED
        assert change_request.decision_comment == "Wrong team"

    @pytest.mark.parametrize("data", [{}, {"decision": "maybe"}])
    def test_invalid_decision_changes_nothing(self, auth_client, approver, change_request, data):
        response = auth_client.post(self.url(change_request), data)

        change_request.refresh_from_db()
        assert response.status_code == 200
        assert change_request.status == Status.SUBMITTED

    def test_decided_request_is_read_only(self, auth_client, approver, portfolio):
        done = decided(portfolio, status=Status.REJECTED, decision_comment="Not needed")
        original = done.decided_by

        page = auth_client.get(self.url(done))
        response = auth_client.post(self.url(done), {"decision": "approve"})

        done.refresh_from_db()
        assert b'value="approve"' not in page.content
        assert b"Not needed" in page.content
        assert response.status_code == 302
        assert done.status == Status.REJECTED
        assert done.decided_by == original
        assert "already been decided" in str(list(get_messages(response.wsgi_request))[0])

    def test_cannot_decide_on_own_request(self, auth_client, approver, portfolio):
        own = submitted(portfolio, requested_by=approver)

        page = auth_client.get(self.url(own))
        response = auth_client.post(self.url(own), {"decision": "approve"})

        own.refresh_from_db()
        assert page.status_code == 200
        assert b'value="approve"' not in page.content
        assert b"This is your own request" in page.content
        assert response.status_code == 403
        assert own.status == Status.SUBMITTED

    def test_other_portfolios_requests_are_404(self, auth_client, approver):
        other = submitted(PortfolioFactory())

        assert auth_client.get(self.url(other)).status_code == 404
        assert auth_client.post(self.url(other), {"decision": "approve"}).status_code == 404
        other.refresh_from_db()
        assert other.status == Status.SUBMITTED

    def test_non_approver_gets_404(self, auth_client, change_request):
        assert auth_client.get(self.url(change_request)).status_code == 404
        assert (
            auth_client.post(self.url(change_request), {"decision": "approve"}).status_code == 404
        )

    def test_draft_is_404(self, auth_client, approver, portfolio):
        draft = ChangeRequestFactory(portfolio=portfolio)

        assert auth_client.get(self.url(draft)).status_code == 404

    def test_requires_login(self, client, change_request):
        assert client.post(self.url(change_request), {"decision": "approve"}).status_code == 302
        change_request.refresh_from_db()
        assert change_request.status == Status.SUBMITTED


class TestRequesterSeesTheDecision:
    def test_my_requests_shows_decision(self, auth_client, user, portfolio):
        approver = UserFactory(first_name="Priya", last_name="Shah")
        change_request = decided(
            portfolio,
            status=Status.REJECTED,
            requested_by=user,
            decided_by=approver,
            decision_comment="Use the platform team instead",
        )

        listing = auth_client.get("/requests/").content.decode()
        detail = auth_client.get(f"/requests/{change_request.pk}/").content.decode()

        assert "text-bg-danger" in listing
        assert "Rejected" in listing
        assert "Rejected by" in detail
        assert "Priya Shah" in detail
        assert "Use the platform team instead" in detail

    def test_decided_request_cannot_be_discarded_or_resubmitted(self, auth_client, user, portfolio):
        change_request = decided(portfolio, requested_by=user)

        assert auth_client.post(f"/requests/{change_request.pk}/discard/").status_code == 404
        assert auth_client.post(f"/requests/{change_request.pk}/confirm/").status_code == 404
