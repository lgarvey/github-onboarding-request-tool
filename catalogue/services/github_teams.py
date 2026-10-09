"""GitHub team IDs.

The YAML refers to a parent team by GitHub's numeric ID (`parent_team_id`) but does not
record each team's own ID, so mapping between IDs and slugs needs GitHub itself.
"""

import zlib

from catalogue.services import terraform_config
from catalogue.services.terraform_config import Team


def get_team_ids(org: str) -> dict[str, int]:
    """Return `{team slug: numeric GitHub team ID}` for every team in the organisation.

    STUB: returns stable fake IDs derived from the slugs in the YAML. This will later be
    replaced by a GitHub GraphQL query (`organization.teams { slug databaseId }`) using a
    token with access to every organisation. Callers depend only on this function.
    """
    return {team.slug: _fake_team_id(org, team.slug) for team in terraform_config.get_teams(org)}


def _fake_team_id(org: str, slug: str) -> int:
    return zlib.crc32(f"{org}/{slug}".encode()) % 9_000_000 + 1_000_000


def get_team_id(org: str, slug: str) -> int | None:
    return get_team_ids(org).get(slug)


def get_parent_team(org: str, team: Team) -> Team | None:
    """Resolve a team's `parent_team_id` to the parent team, if it is known."""
    if team.parent_team_id is None:
        return None
    slugs_by_id = {team_id: slug for slug, team_id in get_team_ids(org).items()}
    parent_slug = slugs_by_id.get(team.parent_team_id)
    return terraform_config.get_team(org, parent_slug) if parent_slug else None
