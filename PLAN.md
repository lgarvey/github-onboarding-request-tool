# GitHub Access Request Tool — POC Plan

## Background

The SRE team manages GitHub on/offboarding via a private Terraform repo, `terraform-github`. Today every request to add/remove/archive repos or teams, or change access, means someone hand-editing YAML, raising a PR, and chasing approval from the right portfolio approver.

This POC is a small Django app that:

1. Reads the current state of orgs, repos and teams **directly from the `terraform-github` YAML files** (not the GitHub API).
2. Lets staff request a change to **one** repo or team.
3. Captures the change as a structured, atomic **change request** tied to an approving **portfolio**.
4. Records it in the database.

Generating PRs against `terraform-github` and running approvals in-app are **out of scope** (see Phase 2 notes at the end). The UI is the thing being demoed. But the data model should make PR generation straightforward later.

---

## Tech stack

| Concern | Choice |
|---|---|
| Python | 3.13.x |
| Django | **5.2 LTS** |
| Dependency management | Poetry |
| Database | PostgreSQL (docker-compose locally; AWS RDS when deployed) |
| Settings | `django-environ` |
| DB config | `dj-database-url` |
| Static files | `whitenoise` (serves static when `DEBUG=False`) |
| Feature flags | `django-waffle` |
| Auth | `django-staff-sso-client` (https://github.com/uktrade/django-staff-sso-client) |
| CSS | Bootstrap 5, **vendored into static files** (no CDN, no build step) |
| JS | Vanilla JS in `static/js/`, no build step, no SPA framework. Use it freely for dynamic form rows and small UX touches |
| Tests | `pytest`, `pytest-django`, `factory-boy`, `pytest-cov` |
| Lint/format | `ruff` |

Rendering is server-side Django templates with standard form POSTs and page reloads. JS enhances forms (adding/removing rows), but pages must not depend on a JS framework or client-side routing.

---

## Project layout (target)

```
project-root/
  config/                 # settings.py, urls.py, wsgi.py, asgi.py
  users/                  # custom user model, auth views, admin login override
  catalogue/              # terraform-github reader service + browse views
  portfolios/             # Portfolio + Approver models
  change_requests/        # ChangeRequest + ChangeItem models, edit/create/archive flows
  github_users/           # stubbed GitHub username provider (API later)
  templates/
  static/                 # vendored bootstrap, js/, css/
  tests/
    fixtures/terraform-github/terraform/...   # fake config tree used by tests
  terraform-github/       # real checkout (gitignored), mounted read-only
  docker-compose.yml
  Dockerfile
  pyproject.toml
  .env.example
```

Do not name an app `requests` because it collides with the `requests` library.

---

## Source data: `terraform-github`

The location comes from the env var `TERRAFORM_GITHUB_PATH`, defaulting to `./terraform-github`. The structure is:

```
terraform-github/terraform/{organisation-name}/
  repositories/config.yaml
  teams/config.yaml
```

- **Organisations** are the top-level directories under `terraform-github/terraform/`.
- **Repositories** are read from `repositories/config.yaml`. The top-level key is the organisation, mirroring the org directory name:

```yaml
{organisation-name}:
  slug: {organisation-name}
  repositories:
    {repo-name}:
      name: {repo-name}
      description: string|null
      visibility: public|private|internal
      archived: true|false
      team_permissions:
        {team-slug}: pull|triage|push|maintain|admin
      user_permissions:             # may be null
        {github-username}: pull|triage|push|maintain|admin
      # ...other fields exist; ignore for POC but MUST be preserved conceptually for later PR generation
```

- **Teams** are read from `teams/config.yaml`:

```yaml
{organisation-name}:            # mirrors the org directory name
  # ...
  teams:
    {team-slug}:
      name: {team-name}
      slug: {team-slug}
      description: string|null
      privacy: closed|secret
      parent_team_id: integer|null   # GitHub's numeric team ID, not a slug
      members:
        {github-username}: member|maintainer
      # ...other fields exist; ignore for POC
```

The real repo is internal and is not available to this project. The source of truth for structure and values is the pair of schemas in `terraform-github/schemas/`. `terraform-github/terraform/org1/` is an empty sample org. Permission and role values are defined exactly once, as Django `TextChoices` in `catalogue/choices.py`, and used everywhere.

Confirmed by the SRE team rather than the schemas: keys in `team_permissions` are team slugs, a team's YAML key is its slug, and each `config.yaml` has one top-level org key.

Handle a missing or empty YAML file gracefully by treating it as an empty list rather than raising a 500.

---

## Authentication

### Custom user model (must be the first migration)

`users.User` is built on `AbstractBaseUser` + `PermissionsMixin`:

- `email_user_id`: `CharField`, **primary key**, `USERNAME_FIELD`
- `email`: `EmailField`
- `first_name`, `last_name`
- `is_active`, `is_staff`
- A custom manager supporting `create_user` / `create_superuser`

Set `AUTH_USER_MODEL = "users.User"` **before any migrations are generated**. Read the `django-staff-sso-client` README for how it maps the SSO profile onto the user model, and conform to that. Do not invent the mapping.

### SSO toggle via waffle

The org's existing pattern is a waffle toggle that disables SSO for local development, which reactivates the standard admin login.

- Use a waffle **switch** (global, not per-request) named **`DISABLE_SSO`**.
  - The name is deliberately negative so the safe default holds: if the switch is absent or off, **SSO is on**. Do **not** create this switch in a data migration.
  - Local dev enables it via a management command or the waffle CLI (`manage.py waffle_switch DISABLE_SSO on --create`). Document this in the README.
- Provide a `/login/` view and set `LOGIN_URL = "/login/"`:
  - SSO on: redirect to the authbroker login URL.
  - SSO off: redirect to `/admin/login/?next=...`.
- Override `/admin/login/`:
  - SSO on: redirect to `LOGIN_URL` (SSO), preserving `next`.
  - SSO off: render the normal Django admin login.
- Use Django's `LoginRequiredMiddleware` (Django 5.1+) so every view requires auth by default. Mark login/callback/health views with `@login_not_required`.
- Configure `AUTHENTICATION_BACKENDS` with both the authbroker backend and `ModelBackend`.
- Admin itself stays available (for managing portfolios) and is reached via SSO when SSO is on.

Settings come from env: `AUTHBROKER_URL`, `AUTHBROKER_CLIENT_ID`, `AUTHBROKER_CLIENT_SECRET`, etc. Use placeholders in `.env.example`.

---

## Domain model

### Portfolio

**`portfolios.Portfolio`**
- `name` (unique), `description`

**`portfolios.Approver`**
- `portfolio` (FK → Portfolio, `related_name="approvers"`)
- `name`, `email`
- Approvers are not necessarily app users. Phase 2 may link them to `User` by email.

Both models are registered in admin with Approver as an inline. Add a `seed_portfolios` management command that creates 3–4 example portfolios with approvers for demos.

### Change requests

A change request targets **exactly one repo or one team** in one org. This keeps every request inside a single portfolio and avoids basket/cart functionality.

**`change_requests.ChangeRequest`**
- `requested_by` (FK → User)
- `organisation` (str, org directory name)
- `target_type`: `repository | team`
- `target_name` (str; for creates, the new name)
- `action`: `create | modify | archive`
- `portfolio` (FK → Portfolio, `PROTECT`)
- `details` (JSONField): create-time metadata such as `description` and `parent_team`
- `status`: `draft | submitted` (Phase 2 adds `approved | rejected | applied`)
- `created_at`, `submitted_at`

**`change_requests.ChangeItem`**
- `change_request` (FK, `related_name="items"`)
- `operation`: `add | remove | change`
- `principal_type`: `team | user`
- `principal_name` (team slug or GitHub username)
- `old_permission` (nullable)
- `new_permission` (nullable)

Items store the **diff against the current YAML**, not the full desired state. That gives the summary text for free, and later maps directly onto YAML edits for a PR.

A `ChangeRequest.summary_lines()` method (or a template tag) renders human-readable lines, for example:

```
Repository: my-repo (org: uktrade)
  Add team platform-sre with maintain
  Change user jbloggs: push → admin
  Remove user old-contractor
Portfolio: Digital Trade
```

---

## Services

### `catalogue.services.terraform_config`

This is a pure-Python read layer over the YAML that returns dataclasses. Views never touch YAML directly.

- `list_organisations() -> list[str]`
- `get_repositories(org) -> list[Repository]` (name, archived, team_permissions dict, user_permissions dict)
- `get_repository(org, name) -> Repository | None`
- `get_teams(org) -> list[Team]` (name, slug, description, privacy, parent_team_id, members dict)
- `get_team(org, slug) -> Team | None`

Keep it simple; no caching is needed for the POC. Tests run against `tests/fixtures/terraform-github/`, never the real checkout. Override the path in pytest settings.

### `catalogue.services.github_teams`

The YAML refers to a parent team by numeric GitHub ID but records no ID for each team, so IDs have to come from GitHub.

- `get_team_ids(org) -> dict[str, int]` maps team slug to numeric ID. It is a **stub** returning stable fake IDs for the teams in the YAML. It will later be a GitHub GraphQL query using a token with access to every org.
- `get_team_id(org, slug)` and `get_parent_team(org, team)` are built on it. Nothing else knows about IDs.

### `change_requests.services.diff`

- `diff_permissions(current: dict[str, str], desired: dict[str, str], principal_type) -> list[ChangeItemData]`

This is a pure function and must be heavily unit tested.

### `github_users.services`

- `list_usernames() -> list[str]` returns a **stubbed** list of ~30 fake GitHub usernames for now.
- Add a docstring noting that it will later call the GitHub API. Views and forms depend only on this function.

---

## User flows and pages

All pages share a simple Bootstrap layout with a navbar containing: app name, Organisations, My requests, user email, and logout.

### 1. Organisation list (`/`)
- Lists every org inferred from directories, each linking to its detail page.

### 2. Organisation detail (`/orgs/<org>/`)
- Has two collapsible sections, **Repositories** and **Teams**, both collapsed by default. Bootstrap collapse or `<details>` both work.
- Under the repositories section is an **Add repository** button. Under the teams section is an **Add team** button.
- Each repository row shows its name and an archived badge if archived, plus these actions:
  - **Edit collaborators**
  - **Archive** (only if not already archived)
- Each team row shows its name, member count, and an **Edit members** action.
- Archived repos are not editable.

### 3. Edit repository collaborators (`/orgs/<org>/repos/<repo>/edit/`)
- The form is pre-populated from current YAML and has two dynamic sections:
  - **Teams**: each row is a team select (teams in this org) + permission select + delete button. An "Add team" button appends a row.
  - **Users**: each row is a username select (from the stub provider) + permission select + delete button. An "Add user" button appends a row.
- A **Portfolio** select is required.
- Implement the rows as Django formsets with a small vanilla JS helper to add and remove rows (manage `TOTAL_FORMS`, clone an empty-form template). Use one reusable helper for all dynamic-row forms.
- On POST: validate, compute the diff against current YAML, and create a `ChangeRequest` (status `draft`) with its items, then redirect to the summary page.

### 4. Edit team members (`/orgs/<org>/teams/<slug>/edit/`)
- Same pattern as the repository edit: member rows (username select + role select + delete) and a Portfolio select.

### 5. Add repository (`/orgs/<org>/repos/new/`)
- Fields: **Name**, **Description**, Teams rows (team + permission), Users rows (username + permission), and **Portfolio**.
- Creates a `ChangeRequest(action=create, target_type=repository)`. Name and description go in `details`, and every row becomes an `add` item.

### 6. Add team (`/orgs/<org>/teams/new/`)
- Fields: **Name**, **Description**, **Parent** (optional select of existing teams in the org), Members rows (username + role), and **Portfolio**.
- Creates a `ChangeRequest(action=create, target_type=team)`, with the parent stored in `details`.

### 7. Archive repository (`/orgs/<org>/repos/<repo>/archive/`)
- A confirmation page with a Portfolio select. It creates a draft `ChangeRequest(action=archive)` with no items, then goes to the summary page.

### 8. Summary / confirm (`/requests/<id>/confirm/`)
- Only the owner can view it, and only while it is a draft.
- Renders the text summary (see the format above) and the portfolio, with two buttons:
  - **Submit request**: sets status `submitted` and `submitted_at`, then redirects to My requests with a success message.
  - **Back to edit**: returns to the edit form, pre-populated from the draft.

### 9. My requests (`/requests/`)
- A table of the current user's submitted requests: date, org, target, action, portfolio, and status. Each row links to a read-only detail page showing the summary.

### Validation rules
- A request must contain at least one change, so a modify with no diff is a form error ("No changes made").
- No duplicate principals within one form (e.g. the same user listed twice).
- For creates, the name must not already exist in that org.
- A team cannot be its own parent.
- Archived repos cannot be edited or archived again.
- Permission and role values must be valid enum members.
- Org, repo, and team names in URLs must exist in the YAML, otherwise return 404.

---

## Infrastructure

- **Dockerfile**: `python:3.13-slim`, installs Poetry, `poetry install`, and runs `runserver 0.0.0.0:8000` for dev.
- **docker-compose.yml**:
  - `db`: postgres (current stable), with a named volume and healthcheck.
  - `web`: builds the Dockerfile, mounts the project for live reload, mounts `./terraform-github` **read-only**, depends on `db` being healthy, and runs migrations on start.
- **`.env.example`** lists every env var with safe local defaults (`DEBUG=True`, `DATABASE_URL`, `SECRET_KEY`, `TERRAFORM_GITHUB_PATH`, and `AUTHBROKER_*` placeholders).
- **Settings** live in a single `config/settings.py` driven by `django-environ`. `DATABASES` comes from `dj_database_url`. Whitenoise middleware sits directly after `SecurityMiddleware`, and `STORAGES` uses whitenoise's compressed manifest storage.
- A `/healthcheck/` endpoint, exempt from login, returns 200.
- **README** covers: running with docker-compose, enabling `DISABLE_SSO` locally, creating a superuser, seeding portfolios, and running tests.

---

## Testing

Use `pytest` + `pytest-django`, with factory-boy factories for User, Portfolio, Approver, ChangeRequest, and ChangeItem. Cover:

- **Terraform reader**: org discovery, repo and team parsing, missing or empty files.
- **Diff service**: add, remove, change, no-op, and mixed cases.
- **Auth**: `DISABLE_SSO` on/off behaviour of `/login/` and `/admin/login/`, `LoginRequiredMiddleware` redirects, and healthcheck exemption.
- **Each flow**: GET renders, valid POST creates the correct draft and items, invalid POST shows errors, confirm submits, and other users cannot view or submit someone else's draft.
- **Summary rendering**.
- **My requests**: users see only their own requests.

All tests use the fixture tree. Aim for high coverage of services and views, and do not chase 100% on boilerplate.

---

## Build order

Work through these phases in order. **At the end of each phase: all tests pass, ruff is clean, and you stop and summarise what was done and anything that needs a decision before continuing.**

1. **Scaffold**: Poetry project, Django 5.2, `config/` settings via environ/dj-database-url, whitenoise, waffle installed, Dockerfile + docker-compose + `.env.example`, pytest configured, healthcheck view, base template with vendored Bootstrap. No models yet.
2. **Users & auth**: custom `User` model as the **first** migration, staff-sso-client integration, `DISABLE_SSO` waffle switch logic, `/login/`, admin login override, `LoginRequiredMiddleware`, auth tests.
3. **Terraform reader**: `catalogue.services.terraform_config`, fixture tree under `tests/fixtures/`, enum definitions (after inspecting the real files if present), tests.
4. **Browse views**: organisation list and organisation detail with collapsible repos/teams and action buttons (links can 404 until later phases).
5. **Domain models**: Portfolio, Approver (with admin inline), ChangeRequest, ChangeItem, `seed_portfolios` command, `github_users` stub, diff service + tests, summary rendering.
6. **Edit repository collaborators**: formsets, reusable dynamic-row JS helper, draft creation, confirm page, submit.
7. **Edit team members**: reuses the pattern from phase 6.
8. **Create & archive**: add repository, add team, archive repository.
9. **My requests**: list and detail pages.
10. **Polish**: validation edge cases, flash messages, empty states, README, coverage pass.

---

## Phase 2 (not in scope, design with these in mind)

- Generate a branch and PR against `terraform-github` from a submitted `ChangeRequest`, using the stored items to edit YAML while preserving unknown fields.
- In-app approval by the portfolio approvers (`approved | rejected` statuses, notifications).
- Replace the stubbed GitHub usernames with the GitHub API.
- Detect stale requests where the YAML changed after submission, and warn about multiple pending requests against the same target.
