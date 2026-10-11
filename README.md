# github-onboarding-request-tool

A Django proof of concept for requesting GitHub repository and team access changes. It reads the
current state from the `terraform-github` YAML config, lets staff describe one change to one
repository or team, and records it as a change request tied to an approving portfolio.

Portfolio approvers can approve or reject requests in the app, and an approved request can be
written straight into the YAML. It does not raise pull requests yet. `PLAN.md` has the full spec, the build
order, and what is planned next.

## Running locally

```bash
cp .env.example .env
docker compose up --build
```

The app is served at http://localhost:8000. Migrations run when the `web` container starts.

Then, in a second terminal:

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_portfolios
docker compose exec web python manage.py import_organisations
```

## Signing in

Every page except `/healthcheck/` requires a signed-in user. Sign-in goes through Staff SSO
(`AUTHBROKER_*` settings) unless the `DISABLE_SSO` environment variable is on. It is off when
unset, so SSO is the default. `.env.example` turns it on for local development.

It is read at start-up, so after changing it in `.env` run `docker compose up -d` to recreate the
container.

With `DISABLE_SSO` on, `/login/` sends you to the normal Django admin login form, so local users
need to be staff (a superuser is easiest).

Users are keyed on the SSO `email_user_id`. With SSO on, `/admin/` is reached through SSO and
needs `is_staff`, so the first admin has to be created with `createsuperuser` using their SSO
`email_user_id`.

## The terraform-github config

The app reads repositories and teams from YAML, never from the GitHub API:

```
terraform-github/terraform/{directory}/repositories/config.yaml
terraform-github/terraform/{directory}/teams/config.yaml
```

### Organisations

Which organisations the app manages is set in the admin at `/admin/catalogue/organisation/`, not
worked out from the directories. An organisation has its **GitHub name** and the **directory**
its config lives in, which defaults to the GitHub name. A directory with no organisation is
ignored.

- `import_organisations` adds an organisation for each directory that already exists, taking the
  GitHub name from the file's `slug` where there is one. It is safe to re-run.
- To start managing a new organisation, add it in the admin. It appears straight away with no
  repositories or teams. Its directory and `config.yaml` files are created the first time an
  approved change is written to them, with the directory as the top-level key and the GitHub
  name as `slug`.

`TERRAFORM_GITHUB_PATH` in `.env` sets where that tree is read from. The app only reads it unless
`APPLY_APPROVED_CHANGES` is on (see below). Missing, empty or unparseable files show the
organisation as having no repositories or teams.

By default it points at `./terraform-github-sample`, a stand-in checked into this repo because the
real one is internal. It holds the two schemas and an empty sample organisation, `org1`. To see
the app with data, add fake repositories and teams to `org1` that follow the schemas.
`tests/fixtures/terraform-github/` has a worked example.

To use a real checkout, set the variable and restart:

```bash
# .env
TERRAFORM_GITHUB_PATH=/path/to/terraform-github     # absolute, or relative starting with ./
```

```bash
docker compose up -d
```

A checkout placed at `./terraform-github` is gitignored, so it cannot be committed by accident.

## Using it

- **Organisations** (`/`) lists each organisation. Its page has collapsible Repositories and
  Teams sections.
- From there you can **edit a repository's collaborators**, **edit a team's members**,
  **add a repository**, **add a team**, or **archive a repository**.
- Each form asks for a **portfolio** and leads to a **confirm page** showing a text summary of the
  change. Nothing is sent until you choose Submit request. Back to edit reopens the form.
- **My requests** (`/requests/`) shows your submitted requests and any drafts you have not sent
  yet. Drafts can be continued or discarded.

- **Approvals** (`/approvals/`) appears in the navbar for portfolio approvers. It lists the open
  and completed requests for their portfolios, and each request can be approved or rejected with
  a comment. The requester sees the decision in My requests.

- **The admin** (`/admin/change_requests/changerequest/`) gives staff an overview of every request
  from every portfolio, drafts included, with filters by status, organisation and portfolio and
  a search. It is read-only: requests only change through the pages above.

A request stores the difference from the current YAML (add, change or remove a team or user), not
the full desired state.

### Portfolios

Portfolios and their approvers are managed in the admin at `/admin/portfolios/`.
`seed_portfolios` loads four made-up examples and is safe to re-run.

An approver entry has a name and a **contact email**, which requesters see so they know who to
chase. It also has an optional **user**: the account the approver signs in with. That link, not
the email, is what gives them the Approvals page, because an SSO user can have several email
addresses. An approver without a linked user is a contact only. Set the link in the admin once
the person has signed in for the first time.

Approvers cannot decide on their own requests, and rejecting needs a comment. To try the approver
pages locally, link your own account to every example portfolio, giving its `email_user_id` or
email:

```bash
docker compose exec web python manage.py seed_portfolios --approver you@example.com
```

You will need a second user to submit requests, since your own are left for another approver.

## Writing approved changes into the YAML

With `APPLY_APPROVED_CHANGES=True` in `.env`, approving a request edits the matching
`config.yaml` under `TERRAFORM_GITHUB_PATH`. It is off when unset, so a real checkout is never
written to unless you ask. `.env.example` turns it on, because the default path is the sample tree.

- The approver's page shows the exact diff before they approve, and both the approver and the
  requester see the diff that was made afterwards. The request's status becomes **Applied**.
- The file is edited in place: comments, key order and fields the app does not know about are
  kept. Only the lines for the change move.
- A new repository or team starts from the defaults in `catalogue/config_templates/repository.yaml`
  and `team.yaml`. Edit those to change what a new entry looks like.
- If the YAML has moved on (the repository has gone, or the name is now taken), the request stays
  **Approved**, the approver is told why, and an **Apply to YAML** button lets them retry.

Nothing is committed or pushed. With the sample tree, `git diff terraform-github-sample` shows
what the app wrote and `git checkout -- terraform-github-sample` undoes it.

## What is stubbed

Both stubs are single functions, so a GitHub API implementation can replace them without touching
the views or forms. That will need a token with access to every organisation.

| Stub | Returns | Later |
|---|---|---|
| `github_users.services.list_usernames()` | About 30 fake GitHub usernames | Organisation members from the GitHub API |
| `catalogue.services.github_teams.get_team_ids(org)` | A fake numeric ID for each team in the YAML | Team IDs from the GitHub GraphQL API |

Team IDs matter because the YAML names a team's parent by GitHub's numeric ID. With the stub, a
`parent_team_id` typed into the YAML by hand will not match a team unless it equals the fake ID.
The same fake ID is what gets written as `parent_team_id` when a new team with a parent is applied.

## Tests and linting

Python 3.13 is only needed inside the container, so everything runs through compose:

```bash
docker compose exec web pytest
docker compose exec web pytest --cov
docker compose exec web sh -c "ruff check . && ruff format ."
```

Tests read `tests/fixtures/terraform-github/`, never the real checkout.

## Dependencies

Managed with Poetry. Add them with `poetry add` (inside the container if you have no local
Python 3.13: `docker compose exec web poetry add --lock <package>`), then rebuild the image.

## Layout

| Path | Purpose |
|---|---|
| `config/` | Settings, root URLs, healthcheck |
| `users/` | Custom user model, login views, admin login override |
| `catalogue/` | Organisation model, YAML reader and writer, new-entry templates, team ID stub, organisation pages, permission and role values |
| `portfolios/` | Portfolio and approver models, `seed_portfolios` |
| `change_requests/` | Change request models, forms, diff, draft and apply services, request and approval pages |
| `github_users/` | Stubbed GitHub usernames |
| `static/` | Vendored Bootstrap 5, `js/formset.js` for add and remove rows |
