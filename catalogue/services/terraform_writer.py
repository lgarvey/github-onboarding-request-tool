"""Edits to the terraform-github YAML config.

Each function works out one change and returns it as an `Edit` without touching the disk.
Call `Edit.write()` to save it, or `Edit.diff()` to show what it would do.

Files are round-tripped, so comments, key order and fields this app knows nothing about are
kept. New repositories and teams start from the defaults in `catalogue/config_templates/`.
"""

import difflib
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml as pyyaml
from django.conf import settings
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from catalogue.services import terraform_config

TEMPLATES = Path(__file__).resolve().parent.parent / "config_templates"

# A permission change maps a principal to its new permission, or to None to remove it.
Changes = dict[str, str | None]


class ConfigError(Exception):
    """A change could not be worked out or saved. The message is fit to show to a user."""


@dataclass(frozen=True)
class Edit:
    path: Path
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def diff(self) -> str:
        """A unified diff of the file, with the path shown relative to the config root."""
        try:
            name = self.path.relative_to(settings.TERRAFORM_GITHUB_PATH).as_posix()
        except ValueError:
            name = self.path.name
        lines = difflib.unified_diff(
            self.before.splitlines(keepends=True),
            self.after.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
        )
        return "".join(lines)

    def write(self) -> None:
        """Save the file, replacing it in one step so a failure cannot leave it half-written."""
        try:
            self._make_directories()
            handle, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", text=True)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as temp:
                    temp.write(self.after)
                self._match_ownership(temp_name)
                os.replace(temp_name, self.path)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        except OSError as error:
            raise ConfigError(f"Could not write {self.path.name}: {error.strerror}.") from error

    def _make_directories(self) -> None:
        """Create the file's missing directories, owned like the directory they go in."""
        missing = []
        directory = self.path.parent
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        owner = directory.stat()
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            try:
                os.chown(directory, owner.st_uid, owner.st_gid)
            except PermissionError:
                pass

    def _match_ownership(self, temp_name: str) -> None:
        """Give the new file the owner and mode of the one it replaces, or of its directory.

        The app often runs as root in a container, and the files belong to whoever owns
        the checkout.
        """
        like = self.path if self.path.exists() else self.path.parent
        details = like.stat()
        os.chmod(temp_name, details.st_mode & 0o666 if like is self.path else 0o644)
        try:
            os.chown(temp_name, details.st_uid, details.st_gid)
        except PermissionError:
            pass


def _represent_none(representer, _value):
    # Write `key: null`, as the schemas describe it, not ruamel's default bare `key:`.
    return representer.represent_scalar("tag:yaml.org,2002:null", "null")


def _yaml(explicit_start: bool) -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.explicit_start = explicit_start
    yaml.representer.add_representer(type(None), _represent_none)
    return yaml


class _Document:
    """One organisation's config.yaml for a resource, loaded for editing.

    The file and its directories need not exist yet: they are created on the first write.
    """

    def __init__(self, org: str, resource: str):
        directory = terraform_config.get_directory(org)
        if directory is None:
            raise ConfigError(f"The organisation {org} is not managed by this app.")
        self.org = org
        self.directory = directory
        self.resource = resource
        self.path = terraform_config.config_path(directory, resource)
        self.before = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        # New and empty files get the `---` marker the existing files use.
        self._explicit_start = not self.before.strip() or self.before.lstrip().startswith("---")
        try:
            data = _yaml(self._explicit_start).load(self.before)
        except Exception as error:
            raise ConfigError(f"{self._label} is not valid YAML, so it was not changed.") from error
        if data is None:
            data = CommentedMap()
        if not isinstance(data, CommentedMap):
            raise ConfigError(f"{self._label} does not have the expected layout.")
        self.data = data

    @property
    def _label(self) -> str:
        return f"{self.directory}/{self.resource}/config.yaml"

    def entries(self) -> CommentedMap:
        """The mapping of repositories or teams, created if the file does not have one yet."""
        if self.directory in self.data:
            section = self.data[self.directory]
        elif len(self.data) == 1:
            # The top-level key normally mirrors the directory name; tolerate it differing.
            section = next(iter(self.data.values()))
        elif not self.data:
            # A new file: the directory is the key and `slug` is the name on GitHub.
            section = self.data[self.directory] = CommentedMap({"slug": self.org})
        else:
            raise ConfigError(f"{self._label} does not have the expected layout.")
        if not isinstance(section, CommentedMap):
            raise ConfigError(f"{self._label} does not have the expected layout.")
        if not isinstance(section.get(self.resource), CommentedMap):
            section[self.resource] = CommentedMap()
        return section[self.resource]

    def edit(self) -> Edit:
        buffer = io.StringIO()
        _yaml(self._explicit_start).dump(self.data, buffer)
        return Edit(self.path, self.before, buffer.getvalue())


def _find(entries: CommentedMap, field: str, value: str) -> CommentedMap | None:
    """The entry whose key, or whose `field`, is `value`."""
    for key, entry in entries.items():
        if isinstance(entry, CommentedMap) and (key == value or entry.get(field) == value):
            return entry
    return None


def _insert(mapping: CommentedMap, key: str, value) -> None:
    """Add a key, keeping the mapping alphabetical if it already is."""
    keys = [str(existing) for existing in mapping]
    if keys == sorted(keys, key=str.lower):
        position = sum(1 for existing in keys if existing.lower() < key.lower())
        mapping.insert(position, key, value)
    else:
        mapping[key] = value


def _apply_changes(entry: CommentedMap, field: str, changes: Changes | None) -> None:
    if not changes:
        return
    mapping = entry.get(field)
    if not isinstance(mapping, CommentedMap):
        mapping = entry[field] = CommentedMap()
    for principal, permission in changes.items():
        if permission is None:
            mapping.pop(principal, None)
        elif principal in mapping:
            mapping[principal] = permission
        else:
            # An empty `{}` would otherwise grow into `{a: b, c: d}` on one line.
            mapping.fa.set_block_style()
            _insert(mapping, principal, permission)


def _from_template(name: str, values: dict) -> CommentedMap:
    """A new entry: the template's defaults with `values` laid over them."""
    defaults = pyyaml.safe_load((TEMPLATES / name).read_text(encoding="utf-8"))
    entry = CommentedMap()
    for key, default in defaults.items():
        value = values.get(key, default)
        entry[key] = CommentedMap(value) if isinstance(value, dict) else value
    return entry


def modify_repository(
    org: str,
    name: str,
    *,
    team_permissions: Changes | None = None,
    user_permissions: Changes | None = None,
    archived: bool | None = None,
) -> Edit:
    document = _Document(org, "repositories")
    entry = _find(document.entries(), "name", name)
    if entry is None:
        raise ConfigError(f"The repository {name} is no longer in the config for {org}.")
    _apply_changes(entry, "team_permissions", team_permissions)
    _apply_changes(entry, "user_permissions", user_permissions)
    if archived is not None:
        entry["archived"] = archived
    return document.edit()


def create_repository(
    org: str,
    name: str,
    *,
    description: str = "",
    team_permissions: Changes | None = None,
    user_permissions: Changes | None = None,
) -> Edit:
    document = _Document(org, "repositories")
    entries = document.entries()
    if _find(entries, "name", name) is not None:
        raise ConfigError(f"A repository called {name} already exists in {org}.")
    entry = _from_template("repository.yaml", {"name": name, "description": description or None})
    _apply_changes(entry, "team_permissions", team_permissions)
    _apply_changes(entry, "user_permissions", user_permissions)
    _insert(entries, name, entry)
    return document.edit()


def modify_team(org: str, slug: str, *, members: Changes | None = None) -> Edit:
    document = _Document(org, "teams")
    entry = _find(document.entries(), "slug", slug)
    if entry is None:
        raise ConfigError(f"The team {slug} is no longer in the config for {org}.")
    _apply_changes(entry, "members", members)
    return document.edit()


def create_team(
    org: str,
    name: str,
    slug: str,
    *,
    description: str = "",
    parent_team_id: int | None = None,
    members: Changes | None = None,
) -> Edit:
    document = _Document(org, "teams")
    entries = document.entries()
    if _find(entries, "slug", slug) is not None:
        raise ConfigError(f"A team with the slug {slug} already exists in {org}.")
    entry = _from_template(
        "team.yaml",
        {
            "name": name,
            "slug": slug,
            "description": description or None,
            "parent_team_id": parent_team_id,
        },
    )
    _apply_changes(entry, "members", members)
    _insert(entries, slug, entry)
    return document.edit()
