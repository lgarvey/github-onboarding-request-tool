import pytest

from change_requests.choices import Operation, PrincipalType
from change_requests.services.diff import ChangeItemData, diff_permissions

USER = PrincipalType.USER
TEAM = PrincipalType.TEAM


def test_no_changes():
    current = {"jbloggs": "push", "asmith": "admin"}

    assert diff_permissions(current, dict(current), USER) == []


def test_both_empty():
    assert diff_permissions({}, {}, USER) == []


def test_add():
    assert diff_permissions({}, {"jbloggs": "push"}, USER) == [
        ChangeItemData(Operation.ADD, USER, "jbloggs", None, "push")
    ]


def test_remove():
    assert diff_permissions({"jbloggs": "push"}, {}, USER) == [
        ChangeItemData(Operation.REMOVE, USER, "jbloggs", "push", None)
    ]


def test_change():
    assert diff_permissions({"jbloggs": "push"}, {"jbloggs": "admin"}, USER) == [
        ChangeItemData(Operation.CHANGE, USER, "jbloggs", "push", "admin")
    ]


def test_unchanged_principals_are_left_out():
    current = {"jbloggs": "push", "asmith": "admin"}
    desired = {"jbloggs": "push", "asmith": "pull"}

    assert diff_permissions(current, desired, USER) == [
        ChangeItemData(Operation.CHANGE, USER, "asmith", "admin", "pull")
    ]


def test_mixed_changes_are_grouped_then_sorted_by_name():
    current = {"keep": "pull", "zed-leaves": "push", "al-leaves": "admin", "promoted": "push"}
    desired = {"keep": "pull", "promoted": "admin", "zoe-joins": "pull", "amy-joins": "maintain"}

    assert diff_permissions(current, desired, USER) == [
        ChangeItemData(Operation.ADD, USER, "amy-joins", None, "maintain"),
        ChangeItemData(Operation.ADD, USER, "zoe-joins", None, "pull"),
        ChangeItemData(Operation.CHANGE, USER, "promoted", "push", "admin"),
        ChangeItemData(Operation.REMOVE, USER, "al-leaves", "admin", None),
        ChangeItemData(Operation.REMOVE, USER, "zed-leaves", "push", None),
    ]


def test_replacing_everyone():
    assert diff_permissions({"old": "push"}, {"new": "push"}, TEAM) == [
        ChangeItemData(Operation.ADD, TEAM, "new", None, "push"),
        ChangeItemData(Operation.REMOVE, TEAM, "old", "push", None),
    ]


@pytest.mark.parametrize("principal_type", [USER, TEAM])
def test_principal_type_is_carried_through(principal_type):
    items = diff_permissions({"a": "pull"}, {"a": "push", "b": "pull"}, principal_type)

    assert {item.principal_type for item in items} == {principal_type}


def test_names_are_case_sensitive():
    assert diff_permissions({"JBloggs": "push"}, {"jbloggs": "push"}, USER) == [
        ChangeItemData(Operation.ADD, USER, "jbloggs", None, "push"),
        ChangeItemData(Operation.REMOVE, USER, "JBloggs", "push", None),
    ]


def test_inputs_are_not_modified():
    current, desired = {"a": "pull"}, {"b": "push"}

    diff_permissions(current, desired, USER)

    assert current == {"a": "pull"}
    assert desired == {"b": "push"}


def test_works_for_team_roles():
    current = {"jbloggs": "member", "asmith": "maintainer"}
    desired = {"jbloggs": "maintainer"}

    assert diff_permissions(current, desired, USER) == [
        ChangeItemData(Operation.CHANGE, USER, "jbloggs", "member", "maintainer"),
        ChangeItemData(Operation.REMOVE, USER, "asmith", "maintainer", None),
    ]


def test_result_maps_onto_fixture_repository(settings):
    from catalogue.services import terraform_config

    repo = terraform_config.get_repository("acme", "trade-api")
    desired = {"platform-sre": "admin", "contractors": "pull"}

    assert diff_permissions(repo.team_permissions, desired, TEAM) == [
        ChangeItemData(Operation.ADD, TEAM, "contractors", None, "pull"),
        ChangeItemData(Operation.REMOVE, TEAM, "data-engineering", "push", None),
    ]
