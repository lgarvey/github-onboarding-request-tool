_STUB_USERNAMES = [
    "abanks",
    "achen",
    "asmith",
    "bwright",
    "cdavies",
    "cmorgan",
    "dreid",
    "ekowalski",
    "eturner",
    "fahmed",
    "gmurphy",
    "hlewis",
    "ijohnson",
    "jbloggs",
    "jdoe",
    "kpatel",
    "lgreen",
    "mjones",
    "mnowak",
    "nwilliams",
    "old-contractor",
    "oevans",
    "pshah",
    "qtran",
    "rcooper",
    "sbaker",
    "smarin",
    "tokafor",
    "vsingh",
    "wclarke",
    "ybrown",
    "zhussain",
]


def list_usernames() -> list[str]:
    """Return the GitHub usernames that can be given access.

    STUB: returns a fixed list of fake usernames. This will later call the GitHub API
    to list organisation members. Views and forms depend only on this function.
    """
    return sorted(_STUB_USERNAMES)
