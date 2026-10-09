import pytest
from django.core.management import call_command
from django.db import IntegrityError
from django.db.models import ProtectedError

from catalogue.services import terraform_config
from change_requests.choices import Action, Operation, PrincipalType, Status, TargetType
from github_users.services import list_usernames
from portfolios.models import Approver, Portfolio
from tests.factories import (
    ApproverFactory,
    ChangeItemFactory,
    ChangeRequestFactory,
    PortfolioFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


class TestPortfolios:
    def test_str(self):
        approver = ApproverFactory(name="Jo Bloggs", email="jo@example.com")

        assert str(approver) == "Jo Bloggs <jo@example.com>"
        assert str(PortfolioFactory(name="Digital Trade")) == "Digital Trade"

    def test_approvers_related_name(self):
        portfolio = PortfolioFactory()
        ApproverFactory.create_batch(2, portfolio=portfolio)

        assert portfolio.approvers.count() == 2

    def test_portfolio_name_is_unique(self):
        PortfolioFactory(name="Digital Trade")

        with pytest.raises(IntegrityError):
            PortfolioFactory(name="Digital Trade")

    def test_portfolio_with_requests_cannot_be_deleted(self):
        change_request = ChangeRequestFactory()

        with pytest.raises(ProtectedError):
            change_request.portfolio.delete()

    def test_seed_portfolios_is_repeatable(self):
        call_command("seed_portfolios")
        counts = Portfolio.objects.count(), Approver.objects.count()
        call_command("seed_portfolios")

        assert counts == (Portfolio.objects.count(), Approver.objects.count())
        assert 3 <= counts[0] <= 4
        assert all(p.approvers.exists() for p in Portfolio.objects.all())

    def test_admin_shows_approvers_inline(self, client):
        client.force_login(UserFactory(is_staff=True, is_superuser=True))
        portfolio = ApproverFactory(email="inline@example.com").portfolio

        response = client.get(f"/admin/portfolios/portfolio/{portfolio.pk}/change/")

        assert response.status_code == 200
        assert b"inline@example.com" in response.content
        assert client.get("/admin/portfolios/approver/").status_code == 200


class TestGithubUsers:
    def test_returns_about_thirty_sorted_unique_usernames(self):
        usernames = list_usernames()

        assert 25 <= len(usernames) <= 40
        assert usernames == sorted(set(usernames))

    def test_includes_every_username_in_the_fixtures(self):
        in_yaml = set()
        for repo in terraform_config.get_repositories("acme"):
            in_yaml |= repo.user_permissions.keys()
        for team in terraform_config.get_teams("acme"):
            in_yaml |= team.members.keys()

        assert in_yaml <= set(list_usernames())


class TestChangeRequest:
    def test_defaults(self):
        change_request = ChangeRequestFactory()

        assert change_request.status == Status.DRAFT
        assert change_request.details == {}
        assert change_request.created_at is not None
        assert change_request.submitted_at is None

    def test_str(self):
        assert str(ChangeRequestFactory()) == "Modify repository trade-api"

    def test_modify_repository_summary(self):
        change_request = ChangeRequestFactory(
            organisation="uktrade",
            target_name="my-repo",
            portfolio=PortfolioFactory(name="Digital Trade"),
        )
        ChangeItemFactory(
            change_request=change_request,
            operation=Operation.ADD,
            principal_type=PrincipalType.TEAM,
            principal_name="platform-sre",
            new_permission="maintain",
        )
        ChangeItemFactory(
            change_request=change_request,
            operation=Operation.CHANGE,
            principal_name="jbloggs",
            old_permission="push",
            new_permission="admin",
        )
        ChangeItemFactory(
            change_request=change_request,
            operation=Operation.REMOVE,
            principal_name="old-contractor",
            old_permission="pull",
            new_permission=None,
        )

        assert change_request.summary_lines() == [
            "Repository: my-repo (org: uktrade)",
            "  Add team platform-sre with maintain",
            "  Change user jbloggs: push → admin",
            "  Remove user old-contractor",
            "Portfolio: Digital Trade",
        ]

    def test_modify_team_summary(self):
        change_request = ChangeRequestFactory(
            target_type=TargetType.TEAM,
            target_name="platform-sre",
            portfolio=PortfolioFactory(name="Platform"),
        )
        ChangeItemFactory(
            change_request=change_request, principal_name="kpatel", new_permission="maintainer"
        )
        ChangeItemFactory(
            change_request=change_request,
            operation=Operation.CHANGE,
            principal_name="asmith",
            old_permission="member",
            new_permission="maintainer",
        )

        assert change_request.summary_lines() == [
            "Team: platform-sre (org: acme)",
            "  Add user kpatel as maintainer",
            "  Change user asmith: member → maintainer",
            "Portfolio: Platform",
        ]

    def test_create_repository_summary(self):
        change_request = ChangeRequestFactory(
            action=Action.CREATE,
            target_name="new-service",
            details={"description": "A new service"},
            portfolio=PortfolioFactory(name="Digital Trade"),
        )
        ChangeItemFactory(
            change_request=change_request,
            principal_type=PrincipalType.TEAM,
            principal_name="platform-sre",
            new_permission="admin",
        )

        assert change_request.summary_lines() == [
            "New repository: new-service (org: acme)",
            "  Description: A new service",
            "  Add team platform-sre with admin",
            "Portfolio: Digital Trade",
        ]

    def test_create_team_summary_includes_parent(self):
        change_request = ChangeRequestFactory(
            action=Action.CREATE,
            target_type=TargetType.TEAM,
            target_name="platform-sre-leads",
            details={"description": "", "parent_team": "platform-sre"},
            portfolio=PortfolioFactory(name="Platform"),
        )

        assert change_request.summary_lines() == [
            "New team: platform-sre-leads (org: acme)",
            "  Parent team: platform-sre",
            "Portfolio: Platform",
        ]

    def test_archive_summary_has_no_items(self):
        change_request = ChangeRequestFactory(
            action=Action.ARCHIVE, portfolio=PortfolioFactory(name="Digital Trade")
        )

        assert change_request.summary_lines() == [
            "Archive repository: trade-api (org: acme)",
            "Portfolio: Digital Trade",
        ]

    def test_items_are_deleted_with_the_request(self):
        item = ChangeItemFactory()

        item.change_request.delete()

        assert not type(item).objects.filter(pk=item.pk).exists()

    def test_item_str_is_its_summary(self):
        item = ChangeItemFactory(principal_name="jbloggs", new_permission="push")

        assert str(item) == "Add user jbloggs with push"
