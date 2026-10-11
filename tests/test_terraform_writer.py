import os

import pytest

from catalogue.services import terraform_config, terraform_writer
from catalogue.services.terraform_writer import ConfigError

pytestmark = pytest.mark.usefixtures("writable_config")


def path(root, org, resource):
    return root / "terraform" / org / resource / "config.yaml"


def added(edit):
    return [
        line[1:]
        for line in edit.diff().splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def removed(edit):
    return [
        line[1:]
        for line in edit.diff().splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]


class TestRoundTrip:
    def test_repositories_file_is_reproduced_exactly(self):
        edit = terraform_writer.modify_repository("acme", "trade-api")

        assert not edit.changed
        assert edit.diff() == ""

    def test_teams_file_is_reproduced_exactly_including_comments(self):
        edit = terraform_writer.modify_team("acme", "platform-sre")

        assert "# The stub ID of platform-sre" in edit.before
        assert not edit.changed

    def test_nothing_is_written_until_asked(self, writable_config):
        target = path(writable_config, "acme", "repositories")
        original = target.read_text()

        edit = terraform_writer.modify_repository("acme", "trade-api", archived=True)

        assert edit.changed
        assert target.read_text() == original
        edit.write()
        assert target.read_text() == edit.after


class TestModifyRepository:
    def test_only_the_requested_lines_change(self):
        edit = terraform_writer.modify_repository(
            "acme",
            "trade-api",
            team_permissions={"contractors": "pull", "data-engineering": None},
            user_permissions={"jbloggs": "admin"},
        )

        assert added(edit) == ["        contractors: pull", "        jbloggs: admin"]
        assert removed(edit) == ["        data-engineering: push", "        jbloggs: maintain"]

    def test_fields_the_app_does_not_know_are_kept(self):
        edit = terraform_writer.modify_repository(
            "acme", "trade-api", user_permissions={"asmith": "triage"}
        )

        assert "      has_issues: true\n" in edit.after
        assert "      delete_branch_on_merge: true\n" in edit.after

    def test_reader_sees_the_result(self):
        terraform_writer.modify_repository(
            "acme",
            "trade-api",
            team_permissions={"contractors": "pull"},
            user_permissions={"old-contractor": None, "jbloggs": "admin"},
        ).write()

        repo = terraform_config.get_repository("acme", "trade-api")
        assert repo.team_permissions == {
            "platform-sre": "admin",
            "data-engineering": "push",
            "contractors": "pull",
        }
        assert repo.user_permissions == {"jbloggs": "admin"}

    def test_null_permissions_become_a_block_mapping(self):
        edit = terraform_writer.modify_repository(
            "acme", "legacy-importer", user_permissions={"asmith": "pull"}
        )

        assert removed(edit) == ["      user_permissions: null"]
        assert added(edit) == ["      user_permissions:", "        asmith: pull"]

    def test_empty_flow_mapping_becomes_a_block_mapping(self):
        edit = terraform_writer.modify_repository(
            "acme", ".github", user_permissions={"asmith": "pull", "kpatel": "push"}
        )

        assert removed(edit) == ["      user_permissions: {}"]
        assert added(edit) == [
            "      user_permissions:",
            "        asmith: pull",
            "        kpatel: push",
        ]

    def test_missing_permissions_key_is_added(self):
        terraform_writer.modify_repository(
            "acme", "design-docs", team_permissions={"platform-sre": "admin"}
        ).write()

        repo = terraform_config.get_repository("acme", "design-docs")
        assert repo.team_permissions == {"platform-sre": "admin"}

    def test_removing_someone_who_is_not_there_changes_nothing(self):
        edit = terraform_writer.modify_repository(
            "acme", "trade-api", user_permissions={"nobody": None}
        )

        assert not edit.changed

    def test_new_principal_goes_in_alphabetical_order_when_the_list_is_sorted(self):
        # jbloggs, old-contractor is alphabetical; platform-sre, data-engineering is not.
        edit = terraform_writer.modify_repository(
            "acme",
            "trade-api",
            team_permissions={"contractors": "pull"},
            user_permissions={"kpatel": "push"},
        )
        lines = edit.after.splitlines()

        users = lines.index("        jbloggs: maintain")
        assert lines[users : users + 3] == [
            "        jbloggs: maintain",
            "        kpatel: push",
            "        old-contractor: pull",
        ]
        teams = lines.index("        platform-sre: admin")
        assert lines[teams : teams + 3] == [
            "        platform-sre: admin",
            "        data-engineering: push",
            "        contractors: pull",
        ]

    def test_archive(self):
        edit = terraform_writer.modify_repository("acme", "trade-api", archived=True)

        assert removed(edit) == ["      archived: false"]
        assert added(edit) == ["      archived: true"]

    def test_archive_adds_the_key_when_missing(self):
        terraform_writer.modify_repository("acme", "design-docs", archived=True).write()

        assert terraform_config.get_repository("acme", "design-docs").archived is True

    def test_unknown_repository(self):
        with pytest.raises(ConfigError, match="nope is no longer in the config for acme"):
            terraform_writer.modify_repository("acme", "nope", archived=True)

    def test_top_level_key_may_differ_from_directory(self):
        terraform_writer.modify_repository("legacy", "old-site", archived=True).write()

        assert terraform_config.get_repository("legacy", "old-site").archived is True


class TestCreateRepository:
    def test_new_entry_uses_template_defaults(self):
        edit = terraform_writer.create_repository(
            "acme",
            "new-service",
            description="A new service",
            team_permissions={"platform-sre": "admin"},
            user_permissions={"jbloggs": "maintain"},
        )

        assert removed(edit) == []
        assert added(edit) == [
            "    new-service:",
            "      name: new-service",
            "      description: A new service",
            "      visibility: private",
            "      archived: false",
            "      is_template: false",
            "      has_issues: true",
            "      has_projects: true",
            "      has_wiki: true",
            "      has_discussions: false",
            "      has_downloads: true",
            "      has_pages: false",
            "      homepage_url: null",
            "      allow_merge_commit: true",
            "      allow_squash_merge: true",
            "      allow_rebase_merge: true",
            "      allow_auto_merge: false",
            "      allow_update_branch: false",
            "      delete_branch_on_merge: false",
            "      merge_commit_title: MERGE_MESSAGE",
            "      merge_commit_message: PR_TITLE",
            "      squash_merge_commit_title: COMMIT_OR_PR_TITLE",
            "      squash_merge_commit_message: COMMIT_MESSAGES",
            "      team_permissions:",
            "        platform-sre: admin",
            "      user_permissions:",
            "        jbloggs: maintain",
        ]

    def test_without_description_or_collaborators(self):
        edit = terraform_writer.create_repository("acme", "bare")

        assert "      description: null" in added(edit)
        assert "      team_permissions: {}" in added(edit)
        assert "      user_permissions: {}" in added(edit)

    def test_reader_sees_the_new_repository(self):
        terraform_writer.create_repository(
            "acme", "new-service", description="A new service", user_permissions={"asmith": "push"}
        ).write()

        repo = terraform_config.get_repository("acme", "new-service")
        assert repo.description == "A new service"
        assert repo.archived is False
        assert repo.visibility == "private"
        assert repo.user_permissions == {"asmith": "push"}
        assert len(terraform_config.get_repositories("acme")) == 5

    def test_existing_name_is_refused(self):
        with pytest.raises(ConfigError, match="trade-api already exists in acme"):
            terraform_writer.create_repository("acme", "trade-api")

    def test_into_an_empty_file(self, writable_config):
        terraform_writer.create_repository("empty-org", "first").write()

        text = path(writable_config, "empty-org", "repositories").read_text()
        assert text.startswith(
            "---\nempty-org:\n  slug: empty-org\n  repositories:\n    first:\n      name: first\n"
        )
        assert [r.name for r in terraform_config.get_repositories("empty-org")] == ["first"]

    def test_into_an_organisation_with_no_file_yet(self, writable_config):
        terraform_writer.create_repository("bare-org", "first").write()

        assert path(writable_config, "bare-org", "repositories").is_file()
        assert [r.name for r in terraform_config.get_repositories("bare-org")] == ["first"]

    def test_goes_in_alphabetical_order_when_the_file_is_sorted(self, writable_config):
        for name in ("alpha", "charlie"):
            terraform_writer.create_repository("empty-org", name).write()

        terraform_writer.create_repository("empty-org", "Bravo").write()

        text = path(writable_config, "empty-org", "repositories").read_text()
        assert text.index("    alpha:") < text.index("    Bravo:") < text.index("    charlie:")


class TestTeams:
    def test_modify_members(self):
        edit = terraform_writer.modify_team(
            "acme",
            "platform-sre",
            members={"kpatel": "member", "asmith": None, "jbloggs": "member"},
        )

        assert removed(edit) == ["        jbloggs: maintainer", "        asmith: member"]
        assert added(edit) == ["        jbloggs: member", "        kpatel: member"]

    def test_first_members_of_a_team_without_any(self):
        terraform_writer.modify_team("acme", "contractors", members={"kpatel": "member"}).write()

        assert terraform_config.get_team("acme", "contractors").members == {"kpatel": "member"}

    def test_unknown_team(self):
        with pytest.raises(ConfigError, match="nope is no longer in the config for acme"):
            terraform_writer.modify_team("acme", "nope", members={"kpatel": "member"})

    def test_create_uses_template_defaults(self):
        edit = terraform_writer.create_team(
            "acme",
            "Platform Leads",
            "platform-leads",
            description="Tech leads",
            parent_team_id=3152637,
            members={"jbloggs": "maintainer"},
        )

        assert removed(edit) == []
        assert added(edit) == [
            "    platform-leads:",
            "      name: Platform Leads",
            "      slug: platform-leads",
            "      description: Tech leads",
            "      privacy: closed",
            "      parent_team_id: 3152637",
            "      members:",
            "        jbloggs: maintainer",
        ]

    def test_create_without_optional_values(self):
        edit = terraform_writer.create_team("acme", "Solo", "solo")

        assert "      description: null" in added(edit)
        assert "      parent_team_id: null" in added(edit)
        assert "      members: {}" in added(edit)

    def test_reader_sees_the_new_team(self):
        terraform_writer.create_team(
            "acme", "Platform Leads", "platform-leads", parent_team_id=3152637
        ).write()

        team = terraform_config.get_team("acme", "platform-leads")
        assert team.name == "Platform Leads"
        assert team.parent_team_id == 3152637
        assert team.privacy == "closed"

    def test_existing_slug_is_refused(self):
        with pytest.raises(ConfigError, match="slug platform-sre already exists in acme"):
            terraform_writer.create_team("acme", "Anything", "platform-sre")

    def test_rest_of_the_teams_file_is_untouched(self):
        edit = terraform_writer.create_team("acme", "Solo", "solo")

        assert edit.after.startswith(edit.before)

    def test_into_an_empty_file(self):
        terraform_writer.create_team("empty-org", "First", "first").write()

        assert [t.slug for t in terraform_config.get_teams("empty-org")] == ["first"]


class TestProblems:
    def test_unknown_organisation(self):
        with pytest.raises(ConfigError, match="organisation nope is not managed by this app"):
            terraform_writer.create_repository("nope", "anything")

    def test_file_that_is_not_a_mapping(self):
        with pytest.raises(ConfigError, match="does not have the expected layout"):
            terraform_writer.create_team("legacy", "First", "first")

    def test_file_with_several_top_level_keys(self, writable_config):
        path(writable_config, "empty-org", "teams").write_text("one: {}\ntwo: {}\n")

        with pytest.raises(ConfigError, match="does not have the expected layout"):
            terraform_writer.create_team("empty-org", "First", "first")

    def test_organisation_section_that_is_not_a_mapping(self, writable_config):
        path(writable_config, "empty-org", "teams").write_text("empty-org: just text\n")

        with pytest.raises(ConfigError, match="does not have the expected layout"):
            terraform_writer.create_team("empty-org", "First", "first")

    def test_invalid_yaml_is_left_alone(self, writable_config):
        target = path(writable_config, "acme", "repositories")
        target.write_text("acme:\n  repositories:\n    a: {name: a\n  - broken: [\n")

        with pytest.raises(ConfigError, match="is not valid YAML, so it was not changed"):
            terraform_writer.create_repository("acme", "anything")
        assert "broken" in target.read_text()

    def test_write_failure_is_reported_and_leaves_no_temp_file(self, writable_config, monkeypatch):
        edit = terraform_writer.modify_repository("acme", "trade-api", archived=True)
        target = path(writable_config, "acme", "repositories")

        def fail(*args):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(os, "replace", fail)

        with pytest.raises(ConfigError, match="Could not write config.yaml: Read-only file system"):
            edit.write()
        assert target.read_text() == edit.before
        assert [p.name for p in target.parent.iterdir()] == ["config.yaml"]

    def test_file_without_document_marker_does_not_gain_one(self, writable_config):
        target = path(writable_config, "empty-org", "repositories")
        target.write_text("empty-org:\n  repositories: {}\n")

        edit = terraform_writer.create_repository("empty-org", "first")

        assert not edit.after.startswith("---")

    def test_diff_names_the_file_relative_to_the_config_root(self):
        diff = terraform_writer.modify_repository("acme", "trade-api", archived=True).diff()

        assert diff.startswith(
            "--- a/terraform/acme/repositories/config.yaml\n"
            "+++ b/terraform/acme/repositories/config.yaml\n"
        )

    def test_diff_of_a_file_outside_the_config_root_uses_its_name(self, tmp_path):
        edit = terraform_writer.Edit(tmp_path.parent / "elsewhere.yaml", "a: 1\n", "a: 2\n")

        assert edit.diff().startswith("--- a/elsewhere.yaml\n+++ b/elsewhere.yaml\n")

    def test_written_file_keeps_the_mode_of_the_one_it_replaces(self, writable_config):
        target = path(writable_config, "acme", "repositories")
        target.chmod(0o640)

        terraform_writer.modify_repository("acme", "trade-api", archived=True).write()

        assert target.stat().st_mode & 0o777 == 0o640

    def test_new_file_is_readable_by_others(self, writable_config):
        terraform_writer.create_repository("bare-org", "first").write()

        assert path(writable_config, "bare-org", "repositories").stat().st_mode & 0o777 == 0o644

    def test_ownership_that_cannot_be_changed_is_not_an_error(self, writable_config, monkeypatch):
        def refuse(*args):
            raise PermissionError

        monkeypatch.setattr(os, "chown", refuse)

        terraform_writer.modify_repository("acme", "trade-api", archived=True).write()

        assert terraform_config.get_repository("acme", "trade-api").archived is True
