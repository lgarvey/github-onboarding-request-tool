"""Everything wrong with the world directory, for `validate_world`.

Errors are problems within a file: an entry the readers had to skip. Warnings are
references between files that do not line up, such as an intranet member with no entry in
`people.yaml`. Warnings are expected in real data, and the bootstrap report deals with them.
"""

from dataclasses import dataclass

from world.services import exclusions, intranet, people, sso_apps
from world.services._loader import WARNING, Problem, world_path

READERS = {
    people.FILE: people.parse,
    intranet.FILE: intranet.parse,
    sso_apps.FILE: sso_apps.parse,
    exclusions.FILE: exclusions.parse,
}


@dataclass(frozen=True)
class Result:
    missing: list[str]
    problems: list[Problem]

    @property
    def errors(self) -> list[Problem]:
        return [problem for problem in self.problems if problem.severity != WARNING]

    @property
    def warnings(self) -> list[Problem]:
        return [problem for problem in self.problems if problem.severity == WARNING]


def check() -> Result:
    root = world_path()
    missing = [file for file in READERS if not (root / file).is_file()]
    parsed = {}
    problems = []
    for file, parse in READERS.items():
        parsed[file], file_problems = parse()
        problems.extend(sorted(file_problems, key=lambda problem: problem.line or 0))
    problems.extend(_cross_references(parsed))
    return Result(missing=missing, problems=problems)


def _cross_references(parsed) -> list[Problem]:
    known = parsed[people.FILE]
    if not known:
        # Nothing to check references against.
        return []
    emails = {person.email for person in known}
    sso_ids = {person.sso_id for person in known}
    warnings = []

    def warn(file, message):
        warnings.append(Problem(file, None, message, severity=WARNING))

    for portfolio in parsed[intranet.FILE]:
        for team in portfolio.teams:
            for email in sorted({*team.members, *([team.lead] if team.lead else [])} - emails):
                warn(intranet.FILE, f"{email} in team {team.name} is not in {people.FILE}.")
    for application in parsed[sso_apps.FILE]:
        for sso_id in sorted(set(application.assignments) - sso_ids):
            warn(sso_apps.FILE, f"{sso_id} on {application.slug} is not in {people.FILE}.")
    for sso_id in sorted(parsed[exclusions.FILE].sso_ids - sso_ids):
        warn(exclusions.FILE, f"{sso_id} is not in {people.FILE}.")
    return warnings
