#!/usr/bin/env bash
# Record the demo video. Run from anywhere: ./demo/record.sh
#
# Uses a throwaway database and a throwaway copy of demo/config, so it never touches your
# own data or TERRAFORM_GITHUB_PATH. Output goes to demo/output/.
set -euo pipefail

cd "$(dirname "$0")/.."
OUTPUT="$PWD/demo/output"
TREE="$OUTPUT/terraform-github"
DATABASE=github_access_demo
WEB=demo-web

cleanup() {
  docker rm -f "$WEB" >/dev/null 2>&1 || true
  docker compose exec -T db dropdb -U postgres --if-exists "$DATABASE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Preparing a fresh database and config tree..."
rm -rf "$TREE"
mkdir -p "$OUTPUT"
cp -r demo/config "$TREE"
docker compose up -d --wait db
cleanup
docker compose exec -T db createdb -U postgres "$DATABASE"

echo "Starting the app..."
TERRAFORM_GITHUB_PATH="$TREE" docker compose run -d --name "$WEB" \
  -e DATABASE_URL="postgres://postgres:postgres@db:5432/$DATABASE" \
  -e ALLOWED_HOSTS="$WEB" -e DISABLE_SSO=True -e APPLY_APPROVED_CHANGES=True \
  web sh -c "python manage.py migrate -v 0 && python manage.py shell < demo/seed.py \
    && python manage.py runserver --noreload 0.0.0.0:8000" >/dev/null
network=$(docker inspect "$WEB" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}')

docker build -q -t gh-access-demo-recorder demo >/dev/null
recorder=(docker run --rm --network "$network" --user "$(id -u):$(id -g)" -e HOME=/tmp
  -e DEMO_SPEED="${DEMO_SPEED:-1}" -v "$PWD/demo:/demo" gh-access-demo-recorder)

for _ in $(seq 60); do
  if "${recorder[@]}" python -c "import urllib.request as u; u.urlopen('http://$WEB:8000/healthcheck/')" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if [ -z "${ready:-}" ]; then
  docker logs "$WEB" | tail -20
  echo "The app did not start." >&2
  exit 1
fi

echo "Recording..."
"${recorder[@]}"
echo "Done: demo/output/demo.mp4, with the caption timings in demo/output/narration.md"
