"""Staff SSO applications, from `sso_apps.yaml`: a stand-in for SamlApplication and
ApplicationPermission data.

    applications:
      - slug: datadog
        name: Datadog
        kind: saml                  # saml | oauth
        permissions: [team-datascience, platform-engineer]
        assignments:                # sso_id: the permissions they hold
          jane.doe-1a2b3c4d@id.example.gov.uk: [team-datascience]
      - slug: datahub
        name: Data Hub
        kind: oauth                 # oauth apps have no permissions, only "can sign in"
        permissions: []
        assignments:
          jane.doe-1a2b3c4d@id.example.gov.uk: []
"""

import re
from dataclasses import dataclass, field

from world.choices import SSOApplicationKind
from world.services._loader import Parser, Problem

FILE = "sso_apps.yaml"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")


@dataclass(frozen=True)
class Application:
    slug: str
    name: str
    kind: str
    permissions: tuple[str, ...] = ()
    # sso_id → the permissions they hold. An OAuth app's assignments are always empty.
    assignments: dict[str, tuple[str, ...]] = field(default_factory=dict)


def parse() -> tuple[list[Application], list[Problem]]:
    parser = Parser(FILE)
    entries = parser.load({"applications": list})["applications"]
    applications = []
    slugs: set[str] = set()
    for index in range(len(entries)):
        application = _parse_application(parser, entries, index)
        if application is None:
            continue
        if application.slug in slugs:
            message = f"The application '{application.slug}' appears more than once."
            parser.error(entries[index], "slug", message)
            continue
        slugs.add(application.slug)
        applications.append(application)
    return applications, parser.problems


def _parse_application(parser: Parser, entries: list, index: int) -> Application | None:
    entry = parser.entry(
        entries,
        index,
        "application",
        required=("slug", "name", "kind"),
        optional=("permissions", "assignments"),
    )
    if entry is None:
        return None
    slug = parser.text(entry, "slug", "application")
    if slug is None:
        return None
    where = f"application {slug}"
    if not SLUG.match(slug):
        parser.error(entry, "slug", f"'{slug}' should be lower case letters, numbers and hyphens.")
        return None
    name = parser.text(entry, "name", where)
    kind = entry["kind"]
    if kind not in SSOApplicationKind.values:
        expected = " or ".join(SSOApplicationKind.values)
        parser.error(entry, "kind", f"'kind' in {where} should be {expected}, not '{kind}'.")
        return None
    permissions = _permissions(parser, entry, where)
    if name is None or permissions is None:
        return None
    if kind == SSOApplicationKind.OAUTH and permissions:
        parser.error(entry, "permissions", f"{where} is an OAuth app, so it has no permissions.")
        return None
    assignments = _assignments(parser, entry, where, permissions)
    if assignments is None:
        return None
    return Application(
        slug=slug, name=name, kind=kind, permissions=tuple(permissions), assignments=assignments
    )


def _permissions(parser: Parser, entry: dict, where: str) -> list[str] | None:
    raw = parser.strings(entry, "permissions", where)
    if raw is None:
        return None
    permissions = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            parser.error(raw, index, f"Each permission in {where} should be text.")
            return None
        if value in permissions:
            parser.error(raw, index, f"The permission '{value}' is listed twice in {where}.")
            return None
        permissions.append(value)
    return permissions


def _assignments(
    parser: Parser, entry: dict, where: str, permissions: list[str]
) -> dict[str, tuple[str, ...]] | None:
    raw = entry.get("assignments")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        parser.error(entry, "assignments", f"'assignments' in {where} should map sso_id to a list.")
        return None
    assignments = {}
    for sso_id, held in raw.items():
        if held is None:
            held = []
        if not isinstance(held, list):
            parser.error(raw, sso_id, f"The permissions for {sso_id} in {where} should be a list.")
            continue
        unknown = [permission for permission in held if permission not in permissions]
        if unknown:
            names = ", ".join(str(permission) for permission in unknown)
            parser.error(raw, sso_id, f"{sso_id} holds {names}, which {where} does not define.")
            continue
        assignments[str(sso_id)] = tuple(held)
    return assignments


def get_applications() -> list[Application]:
    return parse()[0]
