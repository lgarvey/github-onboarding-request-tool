# CLAUDE.md

This project is a Django POC for requesting GitHub repo/team access changes, backed by the `terraform-github` YAML config. **Read `PLAN.md` first.** It holds the spec and the phased build order.

## Working agreement

- Work through `PLAN.md` one phase at a time. At the end of each phase: tests green, `ruff check` and `ruff format` clean, then **stop and summarise** before starting the next phase.
- If something in the plan is ambiguous or conflicts with what you find in the real `terraform-github` files, ask. Don't guess.
- The custom user model (`users.User`, PK `email_user_id`) must exist before any other migration is generated.

## Conventions

- Python 3.13, Django 5.2 LTS, Poetry. Add dependencies with `poetry add`, never by editing the lock file.
- Server-rendered templates with standard POST/redirect/GET. Vanilla JS is fine for dynamic form rows and UX; no SPA frameworks and no JS build step.
- Bootstrap 5 is vendored into `static/`, not loaded from a CDN.
- Views never read YAML directly. Go through `catalogue.services.terraform_config`.
- Permission/role values are defined once as `TextChoices` and reused everywhere.
- All settings come from env vars via `django-environ`. No secrets in code.
- The config tree is read from `TERRAFORM_GITHUB_PATH`. The default is `terraform-github-sample/`, a checked-in stand-in holding the schemas and an empty sample org. A real checkout at `terraform-github/` is gitignored. Either way it is **read-only**: the app never writes to it (yet).
- Tests use `tests/fixtures/terraform-github/`, never the real checkout.

## Commands

```bash
docker compose up --build                                   # run app + postgres
docker compose exec web python manage.py migrate
docker compose exec web python manage.py waffle_switch DISABLE_SSO on --create   # local login without SSO
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_portfolios
docker compose exec web pytest
docker compose exec web sh -c "ruff check . && ruff format ."
```
