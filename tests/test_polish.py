import logging
from pathlib import Path

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from catalogue.services import terraform_config
from change_requests.choices import Status
from change_requests.models import ChangeRequest
from portfolios.models import Portfolio
from tests.factories import ChangeItemFactory, ChangeRequestFactory, PortfolioFactory, UserFactory
from tests.helpers import formset_data
from users.models import User

pytestmark = pytest.mark.django_db

BROKEN = Path(__file__).parent / "fixtures" / "broken-terraform-github"


class TestDrafts:
    def test_drafts_section_lists_own_drafts_with_actions(self, auth_client, user):
        draft = ChangeRequestFactory(requested_by=user, target_name="trade-api")
        ChangeRequestFactory()  # someone else's draft

        response = auth_client.get("/requests/")
        html = response.content.decode()

        assert list(response.context["drafts"]) == [draft]
        assert "Drafts" in html
        assert f'href="/requests/{draft.pk}/confirm/"' in html
        assert f'action="/requests/{draft.pk}/discard/"' in html

    def test_no_drafts_section_without_drafts(self, auth_client, user):
        ChangeRequestFactory(requested_by=user, status=Status.SUBMITTED)

        assert b"Drafts" not in auth_client.get("/requests/").content

    def test_drafts_show_even_with_nothing_submitted(self, auth_client, user):
        ChangeRequestFactory(requested_by=user)

        html = auth_client.get("/requests/").content.decode()

        assert "Drafts" in html
        assert "You have not submitted any requests yet." in html

    def test_discard_deletes_the_draft_and_its_items(self, auth_client, user):
        draft = ChangeRequestFactory(requested_by=user)
        ChangeItemFactory(change_request=draft)

        response = auth_client.post(reverse("change_request_discard", args=[draft.pk]))

        assert response.url == "/requests/"
        assert not ChangeRequest.objects.exists()
        assert "Draft discarded" in str(list(get_messages(response.wsgi_request))[0])

    def test_discard_must_be_a_post(self, auth_client, user):
        draft = ChangeRequestFactory(requested_by=user)

        assert auth_client.get(f"/requests/{draft.pk}/discard/").status_code == 405
        assert ChangeRequest.objects.exists()

    def test_cannot_discard_another_users_draft(self, auth_client):
        draft = ChangeRequestFactory()

        assert auth_client.post(f"/requests/{draft.pk}/discard/").status_code == 404
        assert ChangeRequest.objects.exists()

    def test_cannot_discard_a_submitted_request(self, auth_client, user):
        submitted = ChangeRequestFactory(requested_by=user, status=Status.SUBMITTED)

        assert auth_client.post(f"/requests/{submitted.pk}/discard/").status_code == 404
        assert ChangeRequest.objects.exists()


class TestEdgeCases:
    def test_malformed_yaml_is_treated_as_empty_and_logged(self, settings, caplog):
        settings.TERRAFORM_GITHUB_PATH = BROKEN

        with caplog.at_level(logging.ERROR):
            repositories = terraform_config.get_repositories("broken")

        assert repositories == []
        assert "Could not parse" in caplog.text
        assert [t.slug for t in terraform_config.get_teams("broken")] == ["ok-team"]

    def test_organisation_page_survives_malformed_yaml(self, auth_client, settings):
        settings.TERRAFORM_GITHUB_PATH = BROKEN

        response = auth_client.get("/orgs/broken/")

        assert response.status_code == 200
        assert b"This organisation has no repositories." in response.content
        assert b"OK Team" in response.content

    def test_missing_management_form_is_an_error_not_a_crash(self, auth_client):
        portfolio = PortfolioFactory()

        response = auth_client.post(
            "/orgs/acme/repos/trade-api/edit/", {"portfolio": portfolio.pk, "x": "1"}
        )

        assert response.status_code == 200
        assert not ChangeRequest.objects.exists()

    def test_tampered_form_count_is_an_error_not_a_crash(self, auth_client):
        data = formset_data("teams", []) | formset_data("users", [])
        data |= {"users-TOTAL_FORMS": "abc", "portfolio": PortfolioFactory().pk}

        response = auth_client.post("/orgs/acme/repos/trade-api/edit/", data)

        assert response.status_code == 200
        assert not ChangeRequest.objects.exists()

    def test_unknown_portfolio_is_an_error(self, auth_client):
        data = formset_data("members", [("kpatel", "member")]) | {"portfolio": 999999}

        response = auth_client.post("/orgs/acme/teams/contractors/edit/", data)

        assert "portfolio" in response.context["portfolio_form"].errors
        assert not ChangeRequest.objects.exists()

    def test_form_warns_when_no_portfolios_exist(self, auth_client):
        assert not Portfolio.objects.exists()

        html = auth_client.get("/orgs/acme/repos/trade-api/edit/").content.decode()

        assert "No portfolios have been set up yet" in html

    def test_no_warning_once_a_portfolio_exists(self, auth_client):
        PortfolioFactory()

        html = auth_client.get("/orgs/acme/repos/trade-api/edit/").content.decode()

        assert "No portfolios have been set up yet" not in html

    def test_superuser_must_be_superuser(self):
        with pytest.raises(ValueError):
            User.objects.create_superuser("admin@id.example.com", is_superuser=False)


class TestErrorPages:
    def test_404_uses_site_layout(self, auth_client):
        response = auth_client.get("/orgs/nope/")

        assert response.status_code == 404
        assert b"Page not found" in response.content
        assert b"Browse organisations" in response.content

    def test_403_uses_site_layout(self, client):
        client.force_login(UserFactory())

        response = client.get("/admin/login/")

        assert response.status_code == 403
        assert b"You do not have access to this page" in response.content
