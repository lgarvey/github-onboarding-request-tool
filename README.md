# github-onboarding-request-tool

A Django proof of concept for requesting GitHub repository and team access changes, backed by the
`terraform-github` YAML config. See `PLAN.md` for the spec and build order.

## Running locally

```bash
cp .env.example .env
git clone <terraform-github remote> terraform-github   # optional; gitignored and mounted read-only
docker compose up --build
```

The app is served at http://localhost:8000. Migrations run when the `web` container starts.

## Signing in

Every page except `/healthcheck/` requires a signed-in user. Sign-in goes through Staff SSO
(`AUTHBROKER_*` settings) unless the `DISABLE_SSO` waffle switch is on. The switch is never
created automatically, so SSO is the default.

For local development, turn SSO off and use a Django superuser. `/login/` then sends you to the
normal admin login form:

```bash
docker compose exec web python manage.py waffle_switch DISABLE_SSO on --create
docker compose exec web python manage.py createsuperuser
```

Users are keyed on the SSO `email_user_id`. With SSO on, `/admin/` is reached through SSO and
needs `is_staff`, so the first admin has to be created with `createsuperuser` using their SSO
`email_user_id`.

## Tests and linting

Python 3.13 is only needed inside the container, so everything can be run through compose:

```bash
docker compose exec web pytest
docker compose exec web pytest --cov
docker compose exec web sh -c "ruff check . && ruff format ."
```

## Dependencies

Managed with Poetry. Add them with `poetry add` (inside the container if you have no local
Python 3.13: `docker compose exec web poetry add --lock <package>`), then rebuild the image.
