"""People and accounts that automated changes never touch, from `exclusions.yaml`.

    github_logins: [dbt-ci-bot, breakglass-admin]   # bots, service accounts, break-glass admins
    sso_ids: []

GitHub logins are matched without regard to case, as GitHub does.
"""

from dataclasses import dataclass

from world.services._loader import Parser, Problem

FILE = "exclusions.yaml"


@dataclass(frozen=True)
class Exclusions:
    github_logins: frozenset[str] = frozenset()
    sso_ids: frozenset[str] = frozenset()

    def excludes_login(self, login: str) -> bool:
        return login.lower() in self.github_logins

    def excludes_sso_id(self, sso_id: str) -> bool:
        return sso_id in self.sso_ids


def parse() -> tuple[Exclusions, list[Problem]]:
    parser = Parser(FILE)
    sections = parser.load({"github_logins": list, "sso_ids": list})
    logins = set()
    for index in range(len(sections["github_logins"])):
        login = parser.github_login(sections["github_logins"], index, "github_logins")
        if login is not None:
            logins.add(login.lower())
    sso_ids = set()
    for index, value in enumerate(sections["sso_ids"]):
        if isinstance(value, str) and value.strip():
            sso_ids.add(value.strip())
        else:
            parser.error(sections["sso_ids"], index, "Each entry in sso_ids should be text.")
    return Exclusions(github_logins=frozenset(logins), sso_ids=frozenset(sso_ids)), parser.problems


def get_exclusions() -> Exclusions:
    return parse()[0]
