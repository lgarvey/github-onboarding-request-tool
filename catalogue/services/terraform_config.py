"""Read-only access to the terraform-github YAML config.

Layout, relative to settings.TERRAFORM_GITHUB_PATH:

    terraform/{organisation}/repositories/config.yaml
    terraform/{organisation}/teams/config.yaml

Both files have a single top-level organisation key. Repositories live under its
`repositories` mapping and teams under its `teams` mapping. Missing or empty files are
treated as containing nothing.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Repository:
    name: str
    archived: bool = False
    description: str | None = None
    visibility: str | None = None
    team_permissions: dict[str, str] = field(default_factory=dict)
    user_permissions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Team:
    name: str
    slug: str
    description: str | None = None
    privacy: str | None = None
    # GitHub's numeric ID of the parent team. Resolve it with catalogue.services.github_teams.
    parent_team_id: int | None = None
    members: dict[str, str] = field(default_factory=dict)


def _terraform_root() -> Path:
    return Path(settings.TERRAFORM_GITHUB_PATH) / "terraform"


def list_organisations() -> list[str]:
    root = _terraform_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _load_org_section(org: str, resource: str) -> dict:
    """Return the organisation's mapping from `{org}/{resource}/config.yaml`."""
    # Only ever build paths from directory names we discovered ourselves.
    if org not in list_organisations():
        return {}
    path = _terraform_root() / org / resource / "config.yaml"
    if not path.is_file():
        return {}
    try:
        data = _as_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError:
        # Show the organisation as empty rather than failing every page that lists it.
        logger.exception("Could not parse %s", path)
        return {}
    if org in data:
        return _as_dict(data[org])
    if len(data) == 1:
        # The top-level key normally mirrors the directory name; tolerate it differing.
        return _as_dict(next(iter(data.values())))
    return {}


def _permissions(value) -> dict[str, str]:
    return {str(name): str(level) for name, level in _as_dict(value).items()}


def get_repositories(org: str) -> list[Repository]:
    entries = _as_dict(_load_org_section(org, "repositories").get("repositories"))
    repositories = []
    for key, raw in entries.items():
        entry = _as_dict(raw)
        repositories.append(
            Repository(
                name=str(entry.get("name") or key),
                archived=bool(entry.get("archived", False)),
                description=entry.get("description"),
                visibility=entry.get("visibility"),
                team_permissions=_permissions(entry.get("team_permissions")),
                user_permissions=_permissions(entry.get("user_permissions")),
            )
        )
    return sorted(repositories, key=lambda r: r.name.lower())


def get_repository(org: str, name: str) -> Repository | None:
    return next((r for r in get_repositories(org) if r.name == name), None)


def get_teams(org: str) -> list[Team]:
    entries = _as_dict(_load_org_section(org, "teams").get("teams"))
    teams = []
    for key, raw in entries.items():
        entry = _as_dict(raw)
        teams.append(
            Team(
                name=str(entry.get("name") or key),
                slug=str(entry.get("slug") or key),
                description=entry.get("description"),
                privacy=entry.get("privacy"),
                parent_team_id=entry.get("parent_team_id"),
                members=_permissions(entry.get("members")),
            )
        )
    return sorted(teams, key=lambda t: t.name.lower())


def get_team(org: str, slug: str) -> Team | None:
    return next((t for t in get_teams(org) if t.slug == slug), None)
