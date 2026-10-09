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
