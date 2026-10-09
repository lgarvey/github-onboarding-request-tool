import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def section(html, start, end=None):
    """The part of the page between two markers, for asserting on one section."""
    body = html.split(start, 1)[1]
    return body.split(end, 1)[0] if end else body


class TestOrganisationList:
    def test_requires_login(self, client):
        response = client.get(reverse("organisation_list"))

        assert response.status_code == 302
        assert response.url == "/login/?next=/"

    def test_lists_organisations_with_links(self, auth_client):
        response = auth_client.get(reverse("organisation_list"))

        assert response.status_code == 200
        assert response.context["organisations"] == ["acme", "bare-org", "empty-org", "legacy"]
        assert b'href="/orgs/acme/"' in response.content

    def test_empty_state(self, auth_client, settings, tmp_path):
        settings.TERRAFORM_GITHUB_PATH = tmp_path

        response = auth_client.get(reverse("organisation_list"))

        assert b"No organisations were found" in response.content

    def test_navbar_shows_user_and_links(self, auth_client, user):
        html = auth_client.get(reverse("organisation_list")).content.decode()

        assert user.email in html
        assert ">Organisations</a>" in html
        assert "Log out" in html


class TestOrganisationDetail:
    def get(self, auth_client, org="acme"):
        return auth_client.get(reverse("organisation_detail", args=[org]))

    def test_requires_login(self, client):
        assert client.get("/orgs/acme/").url == "/login/?next=/orgs/acme/"

    @pytest.mark.parametrize("org", ["nope", "..", "README.md"])
    def test_unknown_organisation_is_404(self, auth_client, org):
        assert self.get(auth_client, org).status_code == 404

    def test_sections_are_collapsed_by_default(self, auth_client):
        html = self.get(auth_client).content.decode()

        assert html.count('class="accordion-button collapsed"') == 2
        assert html.count('class="accordion-collapse collapse"') == 2

    def test_lists_repositories_and_teams(self, auth_client):
        response = self.get(auth_client)

        assert [r.name for r in response.context["repositories"]] == [
            ".github",
            "design-docs",
            "legacy-importer",
            "trade-api",
        ]
        assert [row["team"].slug for row in response.context["team_rows"]] == [
            "contractors",
            "data-engineering",
            "platform-sre",
            "platform-sre-oncall",
        ]

    def test_repository_actions(self, auth_client):
        html = self.get(auth_client).content.decode()

        assert 'href="/orgs/acme/repos/trade-api/edit/"' in html
        assert 'href="/orgs/acme/repos/trade-api/archive/"' in html
        assert 'href="/orgs/acme/repos/.github/edit/"' in html
        assert 'href="/orgs/acme/repos/new/"' in html

    def test_archived_repository_has_badge_and_no_actions(self, auth_client):
        html = self.get(auth_client).content.decode()
        row = section(html, ">legacy-importer</span>", "</li>")

        assert "Archived" in row
        assert "/orgs/acme/repos/legacy-importer/" not in html
        assert "Archived" not in section(html, ">trade-api</span>", "</li>")

    def test_team_rows(self, auth_client):
        html = self.get(auth_client).content.decode()

        assert "2 members" in section(html, ">Platform SRE</span>", "</li>")
        assert "1 member<" in section(html, ">Platform SRE On-call</span>", "</li>")
        assert "0 members" in section(html, ">Contractors</span>", "</li>")
        assert 'href="/orgs/acme/teams/platform-sre/edit/"' in html
        assert 'href="/orgs/acme/teams/new/"' in html

    def test_parent_team_is_shown_when_it_resolves(self, auth_client):
        response = self.get(auth_client)
        parents = {
            row["team"].slug: row["parent"] and row["parent"].slug
            for row in response.context["team_rows"]
        }

        assert parents == {
            "contractors": None,
            "data-engineering": None,
            "platform-sre": None,
            "platform-sre-oncall": "platform-sre",
        }
        assert "part of Platform SRE" in response.content.decode()

    @pytest.mark.parametrize("org", ["empty-org", "bare-org"])
    def test_empty_states_still_offer_add_buttons(self, auth_client, org):
        html = self.get(auth_client, org).content.decode()

        assert "This organisation has no repositories." in html
        assert "This organisation has no teams." in html
        assert f'href="/orgs/{org}/repos/new/"' in html
        assert f'href="/orgs/{org}/teams/new/"' in html
