"""Loading and checking the world directory's YAML files.

Each reader parses its file into dataclasses and collects a `Problem` for anything it has
to skip, with the line it is on. Readers return what they could parse; `validate_world`
shows the problems. A missing file is treated as empty, as terraform-github's files are.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings
from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from catalogue.models import github_name_validator

# GitHub logins follow the same rules as organisation names.
GITHUB_LOGIN = github_name_validator.regex
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+\Z")

ERROR = "error"
# Something that is valid on its own but does not line up with another file.
WARNING = "warning"


@dataclass(frozen=True)
class Problem:
    file: str
    line: int | None
    message: str
    severity: str = ERROR

    def __str__(self):
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"{where}: {self.severity}: {self.message}"


def world_path() -> Path:
    return Path(settings.WORLD_PATH)


def line_of(node, key=None) -> int | None:
    """The 1-based line of `node`, or of `node[key]` when a key or index is given."""
    lc = getattr(node, "lc", None)
    if lc is None:
        return None
    try:
        if key is None:
            return lc.line + 1
        position = lc.item(key) if isinstance(node, list) else lc.key(key)
        return position[0] + 1
    except (KeyError, IndexError, TypeError):
        return lc.line + 1


class Parser:
    """Reads one file and records what is wrong with it."""

    def __init__(self, file: str):
        self.file = file
        self.problems: list[Problem] = []

    def error(self, node, key, message: str) -> None:
        self.problems.append(Problem(self.file, line_of(node, key), message))

    def load(self, sections: dict[str, type]) -> dict:
        """Load the file and return its top-level sections.

        `sections` maps each allowed top-level key to the type it must hold (`list` or
        `dict`). Missing or null sections come back empty.
        """
        empty = {name: kind() for name, kind in sections.items()}
        path = world_path() / self.file
        if not path.is_file():
            return empty
        try:
            data = YAML(typ="rt").load(path.read_text(encoding="utf-8"))
        except MarkedYAMLError as error:
            mark = error.problem_mark or error.context_mark
            line = mark.line + 1 if mark else None
            reason = error.problem or error.context or "it is not valid YAML"
            self.problems.append(Problem(self.file, line, f"Could not read the file: {reason}."))
            return empty
        except YAMLError as error:
            self.problems.append(Problem(self.file, None, f"Could not read the file: {error}."))
            return empty
        if data is None:
            return empty
        if not isinstance(data, dict):
            self.error(data, None, f"Expected the file to hold {self._names(sections)}.")
            return empty
        for key in data:
            if key not in sections:
                self.error(data, key, f"Unknown section '{key}'. Expected {self._names(sections)}.")
        result = {}
        for name, kind in sections.items():
            value = data.get(name)
            if value is None:
                result[name] = kind()
            elif not isinstance(value, kind):
                shape = "a list" if kind is list else "a mapping"
                self.error(data, name, f"'{name}' should be {shape}.")
                result[name] = kind()
            else:
                result[name] = value
        return result

    @staticmethod
    def _names(sections) -> str:
        return " and ".join(f"'{name}'" for name in sections)

    def entry(self, items: list, index: int, where: str, *, required, optional=()) -> dict | None:
        """The mapping at `items[index]`, if it has all its required fields and no others."""
        entry = items[index]
        if not isinstance(entry, dict):
            self.error(items, index, f"Each {where} should be a mapping of fields.")
            return None
        allowed = set(required) | set(optional)
        for key in entry:
            if key not in allowed:
                expected = ", ".join(sorted(allowed))
                self.error(entry, key, f"Unknown field '{key}' in {where}. Expected: {expected}.")
        missing = [key for key in required if entry.get(key) in (None, "")]
        for key in missing:
            self.error(entry, None, f"The {where} has no '{key}'.")
        return None if missing else entry

    def text(self, entry: dict, key: str, where: str) -> str | None:
        """A non-empty string field, or None if it is missing or not text."""
        value = entry.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            self.error(entry, key, f"'{key}' in {where} should be text.")
            return None
        return value.strip()

    def email(self, node, key, where: str) -> str | None:
        """An email address, lower-cased so files can be matched on it."""
        value = node[key]
        if not isinstance(value, str) or not EMAIL.match(value.strip()):
            self.error(node, key, f"'{value}' in {where} is not an email address.")
            return None
        return value.strip().lower()

    def github_login(self, node, key, where: str) -> str | None:
        value = node[key]
        if not isinstance(value, str) or not GITHUB_LOGIN.match(value) or len(value) > 39:
            self.error(node, key, f"'{value}' in {where} is not a valid GitHub login.")
            return None
        return value

    def boolean(self, entry: dict, key: str, where: str, default: bool) -> bool:
        value = entry.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            self.error(entry, key, f"'{key}' in {where} should be true or false.")
            return default
        return value

    def date(self, entry: dict, key: str, where: str) -> date | None:
        value = entry.get(key)
        if value is None or isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            self.error(entry, key, f"'{key}' in {where} should be a date such as 2026-01-31.")
            return None

    def strings(self, entry: dict, key: str, where: str) -> list | None:
        """The list at `entry[key]` (empty when missing), or None if it is not a list."""
        value = entry.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            self.error(entry, key, f"'{key}' in {where} should be a list.")
            return None
        return value
