from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from change_requests.choices import Action, Operation, Status, TargetType
from tests.factories import ChangeItemFactory, ChangeRequestFactory, PortfolioFactory, UserFactory

pytestmark = pytest.mark.django_db

LIST = "/requests/"


def submitted(user, **kwargs):
    kwargs.setdefault("submitted_at", timezone.now())
    return ChangeRequestFactory(requested_by=user, status=Status.SUBMITTED, **kwargs)


class TestList:
    def test_requires_login(self, client):
        assert client.get(LIST).url == f"/login/?next={LIST}"

    def test_empty_state(self, auth_client):
        response = auth_client.get(LIST)

        assert response.status_code == 200
        assert b"You have not submitted any requests yet." in response.content

    def test_shows_only_the_users_own_submitted_requests(self, auth_client, user):
        mine = submitted(user)
        ChangeRequestFactory(requested_by=user)  # still a draft
        submitted(UserFactory())

        response = auth_client.get(LIST)

        assert list(response.context["change_requests"]) == [mine]

    def test_newest_first(self, auth_client, user):
        now = timezone.now()
        old = submitted(user, submitted_at=now - timedelta(days=2))
        new = submitted(user, submitted_at=now)
        middle = submitted(user, submitted_at=now - timedelta(days=1))

        response = auth_client.get(LIST)

        assert list(response.context["change_requests"]) == [new, middle, old]

    def test_row_contents(self, auth_client, user):
        change_request = submitted(
            user,
            target_type=TargetType.TEAM,
            target_name="platform-sre",
            action=Action.MODIFY,
            portfolio=PortfolioFactory(name="Digital Trade"),
        )

        html = auth_client.get(LIST).content.decode()

        assert f'href="/requests/{change_request.pk}/"' in html
        for text in ("acme", "Team: platform-sre", "Modify", "Digital Trade", "Submitted"):
            assert text in html

    def test_navbar_links_to_my_requests(self, auth_client):
        assert b'href="/requests/">My requests</a>' in auth_client.get("/").content


class TestDetail:
    def test_shows_summary_read_only(self, auth_client, user):
        change_request = submitted(user, portfolio=PortfolioFactory(name="Digital Trade"))
        ChangeItemFactory(
            change_request=change_request,
            operation=Operation.CHANGE,
            principal_name="jbloggs",
            old_permission="push",
            new_permission="admin",
        )

        response = auth_client.get(reverse("change_request_detail", args=[change_request.pk]))
        html = response.content.decode()

        assert response.status_code == 200
        assert response.context["summary_lines"] == [
            "Repository: trade-api (org: acme)",
            "  Change user jbloggs: push → admin",
            "Portfolio: Digital Trade",
        ]
        assert "Change user jbloggs: push → admin" in html
        assert "<form" not in html.split("<main", 1)[1]

    def test_other_users_request_is_404(self, auth_client):
        theirs = submitted(UserFactory())

        assert auth_client.get(f"/requests/{theirs.pk}/").status_code == 404

    def test_draft_is_404(self, auth_client, user):
        draft = ChangeRequestFactory(requested_by=user)

        assert auth_client.get(f"/requests/{draft.pk}/").status_code == 404

    def test_unknown_request_is_404(self, auth_client):
        assert auth_client.get("/requests/999999/").status_code == 404

    def test_requires_login(self, client, user):
        change_request = submitted(user)

        assert client.get(f"/requests/{change_request.pk}/").status_code == 302


class TestSubmitLandsOnMyRequests:
    def test_submit_redirects_to_list_with_message(self, auth_client, user):
        draft = ChangeRequestFactory(requested_by=user)
        ChangeItemFactory(change_request=draft)

        response = auth_client.post(reverse("change_request_confirm", args=[draft.pk]))

        assert response.url == LIST
        assert "has been submitted" in str(list(get_messages(response.wsgi_request))[0])
        page = auth_client.get(LIST)
        assert list(page.context["change_requests"]) == [draft]
        assert b"has been submitted" in page.content
