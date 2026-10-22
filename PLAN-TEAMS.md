# Teams and Roles Layer — POC Plan

> Extends the existing POC described in `PLAN.md`. Read that first: its conventions, stack and
> working agreement (one phase at a time, tests green, ruff clean, stop and summarise) all apply
> here. Where this plan and `PLAN.md` disagree, this plan wins for the new work. The existing
> repository/team change-request flows stay as they are, except for member edits on *managed*
> GitHub teams (see Decisions).

## Decisions

Settled after reviewing this plan against the code (2026-10-19):

- **Where things live.** Three stores, each with one job:
  - **terraform-github** keeps defining repos, GitHub teams and repo permissions. For the POC
    it also holds team membership, which the reconciler writes.
  - **The world directory** is read-only input: snapshots of *other* systems (Staff SSO, the
    intranet). The app never writes it.
  - **The database** is the source of truth for teams, roles, grants, memberships, ownership and
    approvers. `export_world` writes them to YAML as a portable snapshot. The snapshot is not
    read back.
- **Managed GitHub teams.** A GitHub team is *managed* once any `Grant` references it. For managed
  teams, the existing member edit (`/orgs/<org>/teams/<slug>/edit/`) sends people to a role
  request instead of editing members directly. Unmanaged teams keep today's flow. Built in
  Phase 2.
- **GitHub user onboarding belongs to this layer.** A separate "onboard a user" change request
  was prototyped and dropped. Bringing someone into an org is a role request: joining a role
  whose grant puts them in a GitHub team is what gets them invited.
- **Branching.** This work lives on the `teams-roles` branch. `main` stays as the original demo.
- **Demo terraform tree.** `generate_demo_world` writes its terraform tree to a new, checked-in
  `terraform-github-demo/`. `terraform-github-sample/` stays as the schemas plus an empty org.
  Demos set `TERRAFORM_GITHUB_PATH=./terraform-github-demo`.
- **Scope.** Build Phases 0a–3. Phases 4–9 are deferred. Keep them here as design, and ask
  before starting any of them.

## Background

SRE onboarding across GitHub, AWS IAM Identity Center (IDC) and Staff SSO is manual. SRE built
structure in each system (GitHub teams, IDC team roles, SSO access profiles), but users cannot
see it. They ask for the *resource* ("give X access to repo Y", "add me to Datadog"), and SRE takes
the shortest path, granting it directly. The result is permission spaghetti.

This phase adds a layer above all three systems:

```
Portfolio → Team → owns → Resources (GitHub repos; later AWS accounts, SSO apps)
            Team → defines → Roles → Grants (GitHub team, SSO app permission, IDC role)
            Person → RoleMembership (approved by the team's owners or approvers)
```

People ask to join a **role**. The owning team approves. A reconciler works out what that means
in each underlying system and applies it. SRE stops handling membership and only manages role
definitions.

The app may be thrown away in ~18 months if ServiceNow becomes the better home. So the valuable
parts are the **domain model**, the **role catalogue as exportable data** and the **adapters**.
Keep the UI thin.

## Principles

1. **terraform-github defines teams and repo permissions. This layer owns who is in which team.**
   For the POC, membership is still written into the YAML (see the reconciler), so today's
   process keeps working unchanged.
2. **Every resource has one owning team.** A resource with no owner is an *orphan*.
3. **A team's roles only grant access to resources that team owns.** Cross-team access means
   holding a role in the other team, not joining it. Violations are reported, not blocked.
4. **Membership changes** are approved by the owning team's Owners or Approvers and automated.
   **Role definition changes** go to SRE.
5. **Org-wide access** (Cyber, Architects on every repo) is a *baseline grant*, defined by SRE,
   not a team role.
6. **Direct grants** (a person added straight to a repo) are *exceptions*, with a reason, an
   approver and an expiry date.
7. **No live data on the development machine.** All external data comes through adapters that
   read a "world" directory (see below). Development uses synthetic data; demos on the DBT
   workspace point the same code at a real snapshot.

## Out of scope

- Real writes to GitHub, Staff SSO or AWS. Everything is stubbed or written to local YAML.
- Raising PRs (still the open Phase 2 item from `PLAN.md`).
- Removing team membership from terraform-github. That migration is a design note at the end.
- A rich UI for role definition changes. A text box that raises a request is enough.
- Notifications.

---

## The world directory

Everything the app knows about the outside world, other than terraform-github, comes from YAML
under `WORLD_PATH` (env var, read the same way as `TERRAFORM_GITHUB_PATH`).

```
world-sample/           # checked in: synthetic data, the default WORLD_PATH
world-live/             # gitignored: real snapshot, only ever on the DBT workspace
  people.yaml           # stand-in for Staff SSO users + GitHub SAML identity mapping
  intranet.yaml         # stand-in for the intranet's team and portfolio structure
  sso_apps.yaml         # stand-in for Staff SSO SamlApplication / ApplicationPermission data
  exclusions.yaml       # bots, service accounts, break-glass admins: never touched by sweeps
```

The world directory is input only. The team/role catalogue is not stored here; it lives in the
database (see Decisions).

Each file is read through its own service in a new `world` app, returning dataclasses. Views never
read these files, the same rule as for terraform-github. Missing files behave as empty, as
terraform-github does. Add `world-live/` to `.gitignore`, and have docker-compose mount
`WORLD_PATH` read-only.

### `people.yaml`

```yaml
people:
  - sso_id: jane.doe-1a2b3c4d@id.trade.gov.uk   # Staff SSO email_user_id
    email: jane.doe@example.gov.uk
    first_name: Jane
    last_name: Doe
    active: true                # false = deactivated in Staff SSO
    deactivated_at: null        # ISO date when active is false
    github_login: janedoe-dbt   # from GitHub's SAML identity mapping; null if not linked
```

### `intranet.yaml`

```yaml
portfolios:
  - name: Digital Trade
    teams:
      - name: Data Science
        lead: jane.doe@example.gov.uk
        members: [jane.doe@example.gov.uk, ...]   # by email
```

### `sso_apps.yaml`

```yaml
applications:
  - slug: datadog
    name: Datadog
    kind: saml                  # saml | oauth
    permissions: [team-datascience, team-trade, platform-engineer, finops-engineer]
    assignments:
      jane.doe-1a2b3c4d@id.trade.gov.uk: [team-datascience]
  - slug: datahub
    name: Data Hub
    kind: oauth                 # oauth apps have no permissions, only "can sign in"
    permissions: []
    assignments:
      jane.doe-1a2b3c4d@id.trade.gov.uk: []
```

### `exclusions.yaml`

```yaml
github_logins: [dbt-ci-bot, breakglass-admin]
sso_ids: []
```

### Commands

- `validate_world`: loads every file and reports problems with file, line and a plain message.
  Exit status 1 on errors. This is what makes filling `world-live/` by hand on the workspace
  bearable, so the messages matter.
- `generate_demo_world`: writes a synthetic department to `world-sample/` **and** a matching
  terraform tree to `terraform-github-demo/` (never `terraform-github-sample/`). It copies the
  schemas from `terraform-github-sample/schemas/` so the demo tree is complete. It is
  deterministic (fixed seed), so re-running produces no diff. See "Demo data" below.

---

## Domain model

New apps: `world` (readers, no models), `people`, `teams`, `access`. Add them in the phase that
first needs them.

### `people.Person`

Someone who can hold access. Not the same as `users.User`, which is someone who signs in to this
app. Many people will never sign in.

- `sso_id` (PK, matches `User.email_user_id`), `email`, `first_name`, `last_name`
- `github_login` (nullable, unique when set)
- `is_active`, `deactivated_at`
- `synced_at`

`sync_people` refreshes it from `people.yaml`. Link to a `User` by matching `sso_id` with
`email_user_id`. Do not add an FK; a property is enough.

Once `Person` exists, `github_users.services.list_usernames()` (today a hard-coded stub) returns
the `github_login`s of active people instead, so the existing forms offer real people.

`teams.Team` shares a name with the `catalogue.services.terraform_config.Team` dataclass. Where a
module needs both, import the dataclass under an alias (`from ... import Team as GitHubTeam`).

### `teams.Team`

- `portfolio` (FK → Portfolio, `PROTECT`)
- `name`, `slug` (unique), `description`
- `status`: `draft | claimed | retired`. Imported teams start as `draft`. A team becomes
  `claimed` when someone confirms it (Phase 0c).
- `claimed_by` (FK → User, nullable), `claimed_at`

### `teams.TeamApprover`

- `team` (FK), `user` (FK → User). Unique together.

The people who can approve membership requests for a team are its `TeamApprover`s **plus**
anyone holding the team's Owner role who has a `User`. Put this in one function,
`teams.services.approvers_for(team) -> QuerySet[User]`, and use it everywhere.

This is separate from `portfolios.Approver`, which keeps approving the existing change requests.
Whether portfolio approvers should also act as a fallback for a team's membership requests (for
example while a team has no approvers) is an open question. Until it is answered, they do not.

### `teams.Resource`

Something a team owns.

- `kind`: `github_repository | aws_account | sso_application`
- `organisation` (str, GitHub org name; blank for non-GitHub kinds)
- `identifier` (repo name, account ID, or SSO app slug)
- `owner` (FK → Team, nullable, `SET_NULL`). Null means orphan.
- `owner_source`: `seeded | claimed | assigned`, so reports can show how confident ownership is.
- Unique on (`kind`, `organisation`, `identifier`).

`sync_resources` creates a `Resource` for every repository in terraform-github. It never changes
an existing owner.

### `access.Role`

- `team` (FK), `name`, `description`
- `template`: `owner | engineer | contributor | readonly | custom`
- Unique on (`team`, `name`). Creating a team creates its four template roles.

Templates are the defence against role explosion. Custom roles can only be created by SRE
(`is_staff`) in the POC.

### `access.Grant`

What holding a role gives you.

- `role` (FK, `related_name="grants"`)
- `kind`: `github_team | sso_permission`
- For `github_team`: `organisation`, `github_team` (slug), `team_role` (`member | maintainer`,
  the existing `TeamRole` choices)
- For `sso_permission`: `sso_application` (slug), `permission` (blank for OAuth apps)
- Validate in `clean()` that the fields for the kind are set and the others are blank.

IDC roles are expected to be SSO permissions on the IDC SAML application, so they need no
separate grant kind. **Confirm this with Lyndon before Phase 8.**

### `access.RoleMembership`

- `role` (FK), `person` (FK → Person)
- `source`: `imported | requested | assigned`
- `granted_by` (FK → User, nullable), `granted_at`
- `expires_at` (nullable)
- `ended_at`, `end_reason` (`removed | expired | deactivated`): memberships are ended, never
  deleted, so history survives.
- One active membership per (`role`, `person`): a conditional unique constraint on
  `ended_at IS NULL`.

### `access.MembershipRequest`

Mirrors `ChangeRequest`'s lifecycle and conventions, so reuse its status choices and the shape of
`submit()` / `decide()`.

- `role` (FK), `person` (FK → Person), `operation`: `add | remove`
- `requested_by` (FK → User), `reason`
- `status`: `draft | submitted | approved | rejected | applied`, the existing `Status` choices. A
  request is `draft` until the person confirms it on the confirm page, as `ChangeRequest` is.
- `decided_by`, `decided_at`, `decision_comment`, `applied_at`

Approving an `add` creates the `RoleMembership` (`source=requested`). Approving a `remove` ends
it. Then it is applied (Phase 3).

### `access.RoleChangeRequest`

The text-box path for role definition changes.

- `team` (FK), `role` (FK, nullable: null means "new role"), `requested_by`, `description`
- `status`: `submitted | done | rejected`, `decided_by`, `decided_at`, `decision_comment`

Visible to staff users at `/sre/role-requests/`. SRE edits the role in the admin and marks the
request done.

### `access.DirectGrant`

An exception: a person given access to one resource directly, outside any role.

- `person` (FK), `resource` (FK → Resource), `permission` (existing `RepositoryPermission`)
- `reason`, `approved_by` (FK → User), `approved_at`, `expires_at` (**required**)
- `ended_at`

### `access.BaselineGrant`

- `organisation`, `github_team` (slug), `permission`
- `scope`: `all_repositories` (only scope for the POC)
- `description` (e.g. "Cyber: read on every repo")
- Created in the admin only.

### `access.AuditEvent`

One row per thing that happened: request created, approved, rejected, membership started or
ended, reconcile applied, sweep removed someone.

- `at`, `actor` (FK → User, nullable for automated actions), `action` (choices), `subject`
  (short text), `data` (JSONField)

Write every event through one function, `access.services.audit.record(...)`. This replaces the
git history that membership changes will lose when they leave terraform-github, so it must be
complete.

### `teams.GitHubTeamClassification`

Used during bootstrapping (Phase 0b).

- `organisation`, `github_team` (slug), unique together
- `kind`: `team | role_of_team | baseline | stale | unclassified`
- `team` (FK → Team, nullable): which team this GitHub team belongs to, for `team` and
  `role_of_team`
- `note`

---

## Services

### `world.services.*`

`people`, `intranet`, `sso_apps`, `exclusions`: pure readers returning dataclasses, as
`terraform_config` does.

### `access.services.adapters.sso`

The Staff SSO adapter. It is a stub with the shape the real REST API will need:

- `list_applications() -> list[Application]`
- `list_permissions(app_slug) -> list[str]`
- `get_assignments(sso_id) -> dict[str, list[str]]`
- `grant(sso_id, app_slug, permission)`, `revoke(sso_id, app_slug, permission)`
- `deactivated_since(when) -> list[str]`

Reads come from `sso_apps.yaml` and `people.yaml`. Writes go to a DB table
`access.StubSSOAssignment`, overlaid on the YAML, so the demo can show changes without editing
world files. Keep the function signatures free of stub details so a REST client can replace the
module.

### `access.services.resolve`

Pure functions, heavily unit tested:

- `desired_github_team_members(org, team_slug) -> dict[github_login, team_role]`: the union over
  every active membership of every role with a grant on that GitHub team. If any grant gives
  `maintainer`, the person is a maintainer. Excludes people with no `github_login`, inactive
  people and expired memberships.
- `managed_github_teams() -> set[(org, slug)]`: GitHub teams referenced by at least one grant.
  Only managed teams are ever reconciled.
- `effective_repo_access(org, team_slug) -> dict[repo, permission]`: the team's own
  `team_permissions` plus everything it inherits from its ancestors through `parent_team_id`
  (GitHub child teams inherit their parent's repo access). The unexplained report and the
  principle-3 check use this, not the team's own permissions alone.
- `explain(org, team_slug, github_login) -> list[RoleMembership]`: why someone is in a team.
- `desired_sso_permissions(sso_id) -> dict[app, set[permission]]`.

### `access.services.reconcile`

```
plan = reconcile.plan()            # list of PlanItem(system, target, operation, principal, ...)
result = backend.apply(plan)       # backends below
```

- For each managed GitHub team: compare desired members with members in the YAML. Produce
  `add`, `change` and `remove` items.
- **Removing unexplained members is opt-in per team** (`Team.enforce_membership`, default
  `False`). When off, unexplained members show on the report but are not removed. This keeps the
  first runs safe.
- Never touch anyone in `exclusions.yaml`, or anyone in the org's `admin_logins` (org owners in
  the teams config). Both show on reports as explained, not as unexplained.
- For SSO: compare desired permissions with the adapter's assignments, for permissions that some
  grant references. Leave all other permissions alone.

Backends implement `apply(plan) -> ApplyResult`:

- `DryRunBackend`: records the plan, changes nothing.
- `TerraformYamlBackend`: writes team member changes through a new
  `catalogue.services.terraform_writer.modify_teams(org, {slug: Changes})`, one `Edit` per
  **organisation**. Model it on `modify_user_teams`. Comments and unknown fields survive as they
  do today. One Edit per org matters because each `Edit` holds a snapshot of the whole teams
  file. Several Edits built for the same file and then written would overwrite each other. The
  reconciler never writes YAML itself. It respects `APPLY_APPROVED_CHANGES`: when that is off, it
  behaves as dry run.
- `SSOAdapterBackend`: calls the SSO adapter's `grant` / `revoke`.

Later backends (GitHub API, SCIM) only need to implement `apply`. The reconciler must not know
which backend it is using.

Every applied item writes an `AuditEvent`.

### `access.services.sweep`

The leaver sweep:

1. `sync_people`.
2. For each person who is inactive and has active memberships: end them with
   `end_reason=deactivated`.
3. End expired memberships and direct grants with `end_reason=expired`.
4. Run the reconciler.

Also a full comparison: list GitHub logins that appear in terraform-github team members but
belong to inactive people, or to nobody in `people.yaml`. People who can't be mapped are reported,
never removed.

### `teams.services.bootstrap`

Phase 0 logic. See the phases.

---

## Pages

Keep the existing navbar, and add **Teams** and **Reports**. Approvers see **Team approvals** next
to the existing Approvals link. Staff see **SRE**.

- `/teams/`: teams grouped by portfolio, with status badges (draft/claimed), member and
  resource counts, and a search box.
- `/teams/<slug>/`: owned resources, roles (with their grants and members), approvers. Actions:
  **Request to join a role**, **Request a role change** (the text box), **Claim this team** (draft
  teams only).
- `/teams/<slug>/roles/<role>/request/`: pick a person (defaults to yourself), a reason, and
  optionally an expiry date. Then a confirm page, as in the existing flows.
- `/team-approvals/`: open membership requests for teams the user approves (via
  `approvers_for`). Approve, or reject with a comment. You cannot approve your own request.
- `/teams/<slug>/claim/`: confirm members (tick boxes from the draft), owned repos (tick boxes
  from the seeded candidates), and approvers. Submitting sets the team to `claimed`, creates
  imported memberships, sets ownership with `owner_source=claimed`, and makes the claimant a
  `TeamApprover` and an Owner.
- `/reports/unowned/`: orphaned resources, and resources whose owning team has no members or no
  approvers.
- `/reports/unexplained/`: members of managed GitHub teams that no role explains, direct
  `user_permissions` on repos not covered by an active `DirectGrant`, and grants that break
  principle 3 (a role's GitHub team has permissions on repos the role's team does not own).
- `/reports/leavers/`: output of the sweep's full comparison.
- `/reports/bootstrap/`: the Phase 0 conflicts view.
- `/reconcile/`: the current plan as a table, grouped by system and target, with a dry-run
  diff. Staff can press **Apply** (which uses the configured backend).
- `/sre/role-requests/`: role change requests, for staff.
- `/audit/`: audit events, newest first, filterable by team, person and action.

---

## Demo data

`generate_demo_world` builds a fake department of roughly 4 portfolios, 12 teams, 80 people,
2 GitHub orgs, 60 repos and 30 GitHub teams. It must deliberately include the problems the demo
needs to find. Each one should be reachable on a report:

- People added directly to repos (`user_permissions`) with no exception.
- GitHub team members who belong to no role, and members of another team's GitHub team.
- Two orphaned repos (no admin or maintain team).
- Three deactivated people still in GitHub teams, and one active person with no `github_login`.
- Stale GitHub teams (no repo permissions, or all members inactive).
- Role-like GitHub teams (`<team>-admins`) and baseline teams (`cyber`, `architects`) on every
  repo.
- Team names that differ between the intranet and GitHub (`Data Science` vs `data-sci`), and an
  intranet team with no GitHub team.
- SSO app assignments that bypass any role: people with `team-datascience` on Datadog who are
  not in Data Science.

Put the list in the command's docstring, and add a test per item asserting the generated world
contains it.

---

## Build order

At the end of each phase: all tests pass, ruff is clean, and you **stop and summarise** what
was done and anything that needs a decision.

### 0a. World readers and demo data
`world` app and readers, `WORLD_PATH` setting, `.env.example`, compose mount, `.gitignore`
entry, `validate_world`, `generate_demo_world` (writing both `world-sample/` and
`terraform-github-demo/`), test fixtures under `tests/fixtures/world/`. No models.

### 0b. People, teams and bootstrapping
`Person`, `Team`, `TeamApprover`, `Resource`, `GitHubTeamClassification`; `sync_people`,
`sync_resources`; `import_world`:

1. Create draft teams from `intranet.yaml`, with portfolios matched by name (create missing
   portfolios).
2. Propose a classification for every GitHub team. Match names after normalising (lower case,
   strip punctuation and common suffixes such as `-admins`, `-team`). Mark as `baseline` any
   team with `organisation_role_names` (such as `all_repo_read`), and `cyber`- and
   `architect`-like teams on every repo. Mark teams with no repo permissions, or no
   active members, as `stale`. Everything else is `unclassified`.
3. Seed repo ownership: the team mapped to the GitHub team with `admin` (else `maintain`) on a
   repo becomes its candidate owner, `owner_source=seeded`. Ties or no candidate leave it an
   orphan. Do not read CODEOWNERS; it is not reliable enough.
4. Never overwrite a claimed team or a claimed or assigned owner. Re-running is safe.

Classification and draft teams are editable in the admin. `/reports/bootstrap/` lists: people on
the intranet with no `Person`, GitHub logins with no `Person`, intranet members missing from the
mapped GitHub team and the reverse, unclassified GitHub teams, and teams with no portfolio.

### 0c. Claiming and ownership reports
The claim page, `/teams/` and `/teams/<slug>/` (read-only at this point), `/reports/unowned/`.
`export_world`: writes portfolios, teams, approvers, roles, grants, memberships and ownership to
YAML, so the catalogue survives the app being thrown away.

### 1. Roles and grants
`Role` (with templates created per team), `Grant`, admin for both. Creating a claimed team's
template roles maps them to its GitHub teams where classification makes it obvious
(`team` → Engineer, `role_of_team` with `admin` in the name → Owner), and leaves the rest for SRE.
Team pages show roles and grants. `resolve` services and their tests.

### 2. Membership requests and approvals
`RoleMembership`, `MembershipRequest`, `AuditEvent`, request and confirm pages, team approvals,
`RoleChangeRequest` and the SRE page, `/audit/`. Approving changes memberships only; nothing is
written to terraform-github yet. For managed GitHub teams, the existing member-edit page sends
people to a role request instead (see Decisions).

### 3. Reconciler
`reconcile` services, the three backends (`SSOAdapterBackend` can raise
`NotImplementedError` until Phase 7), the `/reconcile/` page, `/reports/unexplained/`. Approving
a membership request runs the reconciler for the affected GitHub teams and marks the request
`applied` when the backend succeeds. A management command `reconcile` (with `--dry-run`) runs it
for everything.

> **Phases 4–9 are deferred.** Keep them as design. Ask before starting any of them.

### 4. Direct grants
`DirectGrant` with a request and approval flow by the resource's owning team, expiry, and their
effect on the unexplained report.

### 5. Baseline grants
`BaselineGrant`; team and repo pages show baseline access as inherited; the unexplained report
and principle-3 check treat baseline teams as explained. The reconciler does not manage baseline
teams' membership.

### 6. Leaver sweep
`sweep` service, `sweep` command (with `--dry-run`), `/reports/leavers/`, exclusions honoured,
audit events for every removal.

### 7. Staff SSO adapter
The adapter stub and `StubSSOAssignment`, `sso_permission` grants, `SSOAdapterBackend`, SSO
applications as `Resource`s (`sync_resources` adds them; ownership assigned in the admin), SSO
rows on the unexplained report. Show the revocation caveat on SSO grants: for SAML apps, removal
takes effect at the person's next sign-in.

### 8. AWS accounts
**Ask before starting.** Needs Lyndon to confirm how IDC role assignments are stored in Staff SSO.
Expected shape: `aws_account` resources (from a new `accounts.yaml` in the world directory),
roles granting SSO permissions on the IDC application, and the account-ownership rules from
principle 2.

### 9. Polish and demo
Empty states, flash messages, README sections (world directory, live snapshot workflow,
commands), coverage pass. Extend `demo/walkthrough.py` with the new story: bootstrap conflicts →
claim a team → request to join a role → approve → reconcile diff → leaver sweep → audit trail.

---

## Running against live data (DBT workspace)

Document this in the README. The code never needs changing:

1. Clone the public repo, then disable pushing from that clone:
   `git remote set-url --push origin DISABLED`.
2. Put the real terraform-github checkout at `./terraform-github/` and the real world files at
   `./world-live/` (both gitignored).
3. Set `TERRAFORM_GITHUB_PATH=./terraform-github` and `WORLD_PATH=./world-live`, then run
   `validate_world` until it is clean.
4. `import_world`, then work through `/reports/bootstrap/`.

Nothing from these directories goes back to the development machine.

---

## Design note: taking membership out of terraform-github (not built)

The target state is terraform-github defining teams and repo permissions only, as the IDC repo
does. When that happens:

- Membership resources must leave terraform state with `removed` blocks (Terraform 1.7+) or
  `terraform state rm`, never by deleting them from config, which would remove everyone.
- Nothing authoritative over membership (such as `github_team_members`) may remain, or the next
  apply will undo the reconciler.
- Org membership needs a home too: invite on first role in that org, remove when someone holds
  none or is deactivated.
- The reconciler then switches to a GitHub API backend, and later perhaps an IdP group or SCIM
  backend. No other code changes.

## Open questions

Ask rather than guess when a phase depends on one of these.

- Where the real intranet data can be exported from, and in what shape (affects `intranet.yaml`).
- How IDC role assignments are stored in Staff SSO (Phase 8).
- Whether Cyber and Architects already use `organisation_role_names` in the real config. The
  team schema supports organisation roles (`all_repo_read` and similar), so the remaining
  question is whether DBT uses them. The answer affects whether baseline grants stay as team
  attachments.
- Whether portfolio approvers act as a fallback for teams with no approvers.
- Whether team members other than Owners and Approvers should be able to approve anything.
