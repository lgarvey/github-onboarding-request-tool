"""The intranet's portfolios and teams, from `intranet.yaml`.

    portfolios:
      - name: Digital Trade
        teams:
          - name: Data Science
            lead: jane.doe@example.gov.uk
            members: [jane.doe@example.gov.uk, ...]   # by email

People are referred to by email, lower-cased here. Team names must be unique across the
whole file, because each one becomes a team in this app.
"""

from dataclasses import dataclass

from world.services._loader import Parser, Problem

FILE = "intranet.yaml"


@dataclass(frozen=True)
class IntranetTeam:
    name: str
    lead: str | None = None
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntranetPortfolio:
    name: str
    teams: tuple[IntranetTeam, ...] = ()


def parse() -> tuple[list[IntranetPortfolio], list[Problem]]:
    parser = Parser(FILE)
    entries = parser.load({"portfolios": list})["portfolios"]
    portfolios = []
    portfolio_names: set[str] = set()
    team_names: set[str] = set()
    for index in range(len(entries)):
        entry = parser.entry(entries, index, "portfolio", required=("name",), optional=("teams",))
        if entry is None:
            continue
        name = parser.text(entry, "name", "portfolio")
        if name is None:
            continue
        if name.lower() in portfolio_names:
            parser.error(entry, "name", f"The portfolio '{name}' appears more than once.")
            continue
        portfolio_names.add(name.lower())
        teams = []
        team_entries = parser.strings(entry, "teams", f"portfolio {name}") or []
        for team_index in range(len(team_entries)):
            team = _parse_team(parser, team_entries, team_index, name)
            if team is None:
                continue
            if team.name.lower() in team_names:
                message = f"The team '{team.name}' appears more than once."
                parser.error(team_entries[team_index], "name", message)
                continue
            team_names.add(team.name.lower())
            teams.append(team)
        portfolios.append(IntranetPortfolio(name=name, teams=tuple(teams)))
    return portfolios, parser.problems


def _parse_team(parser: Parser, entries: list, index: int, portfolio: str) -> IntranetTeam | None:
    entry = parser.entry(
        entries, index, f"team in {portfolio}", required=("name",), optional=("lead", "members")
    )
    if entry is None:
        return None
    name = parser.text(entry, "name", f"team in {portfolio}")
    if name is None:
        return None
    where = f"team {name}"
    lead = parser.email(entry, "lead", where) if entry.get("lead") is not None else None
    raw_members = parser.strings(entry, "members", where)
    if raw_members is None:
        return None
    members = []
    for member_index in range(len(raw_members)):
        email = parser.email(raw_members, member_index, where)
        if email is None:
            continue
        if email in members:
            parser.error(raw_members, member_index, f"{email} is listed twice in {where}.")
            continue
        members.append(email)
    return IntranetTeam(name=name, lead=lead, members=tuple(members))


def get_portfolios() -> list[IntranetPortfolio]:
    return parse()[0]
