"""People, from `people.yaml`: a stand-in for Staff SSO users and GitHub's SAML identity mapping.

    people:
      - sso_id: jane.doe-1a2b3c4d@id.example.gov.uk   # Staff SSO email_user_id
        email: jane.doe@example.gov.uk
        first_name: Jane
        last_name: Doe
        active: true                # false = deactivated in Staff SSO
        deactivated_at: null        # the date they were deactivated, when active is false
        github_login: janedoe       # null if they have not linked a GitHub account

Emails are lower-cased. An entry with a problem is skipped, as is a repeated `sso_id`,
`email` or `github_login` after its first appearance.
"""

from dataclasses import dataclass
from datetime import date

from world.services._loader import Parser, Problem

FILE = "people.yaml"


@dataclass(frozen=True)
class Person:
    sso_id: str
    email: str
    first_name: str
    last_name: str
    active: bool = True
    deactivated_at: date | None = None
    github_login: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def parse() -> tuple[list[Person], list[Problem]]:
    parser = Parser(FILE)
    entries = parser.load({"people": list})["people"]
    people = []
    seen: dict[str, set[str]] = {"sso_id": set(), "email": set(), "github_login": set()}
    for index in range(len(entries)):
        entry = parser.entry(
            entries,
            index,
            "person",
            required=("sso_id", "email", "first_name", "last_name"),
            optional=("active", "deactivated_at", "github_login"),
        )
        if entry is None:
            continue
        where = f"person {entry['sso_id']}"
        sso_id = parser.text(entry, "sso_id", "person")
        email = parser.email(entry, "email", where)
        first_name = parser.text(entry, "first_name", where)
        last_name = parser.text(entry, "last_name", where)
        active = parser.boolean(entry, "active", where, default=True)
        deactivated_at = parser.date(entry, "deactivated_at", where)
        github_login = None
        if entry.get("github_login") is not None:
            github_login = parser.github_login(entry, "github_login", where)
            if github_login is None:
                continue
        if None in (sso_id, email, first_name, last_name):
            continue
        if active and deactivated_at:
            parser.error(entry, "deactivated_at", f"{where} is active but has a deactivated_at.")
            continue
        keys = {"sso_id": sso_id, "email": email, "github_login": github_login}
        repeated = [
            field
            for field, value in keys.items()
            if value is not None and value.lower() in seen[field]
        ]
        for field in repeated:
            parser.error(entry, field, f"{field} '{keys[field]}' appears more than once.")
        if repeated:
            continue
        for field, value in keys.items():
            if value is not None:
                seen[field].add(value.lower())
        people.append(
            Person(
                sso_id=sso_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                active=active,
                deactivated_at=deactivated_at,
                github_login=github_login,
            )
        )
    return people, parser.problems


def get_people() -> list[Person]:
    return parse()[0]
