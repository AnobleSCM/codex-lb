#!/usr/bin/env bash
# Local deploy for codex-lb. Builds the current source tree as
# codex-lb:local-<short-sha>, verifies the new image contains every
# alembic revision the live codex-lb-data volume has applied, retags
# the new image as codex-lb:active, force-recreates the container via
# the live compose file, and confirms /health=200 plus a clean
# current_revision in container logs.
#
# Exits non-zero on any failure. Safe to re-run.
#
# Usage: scripts/codex-lb-deploy.sh
#
# Requires:
#   - cwd is the codex-lb repo root
#   - working tree is clean (or you accept that uncommitted changes ship)
#   - docker --context colima is available
#   - the live compose lives at ~/.codex/codex-lb/docker-compose.yml

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

SHORT_SHA="$(git rev-parse --short HEAD)"
IMAGE_TAG="codex-lb:local-${SHORT_SHA}"
LIVE_COMPOSE="${HOME}/.codex/codex-lb/docker-compose.yml"
HEALTH_URL="http://127.0.0.1:2455/health"

if [ ! -f "$LIVE_COMPOSE" ]; then
  echo "FATAL: live compose not found at $LIVE_COMPOSE" >&2
  exit 1
fi

echo "==> Building $IMAGE_TAG from $REPO_ROOT (HEAD=$SHORT_SHA)"
docker --context colima build -t "$IMAGE_TAG" .

echo "==> Verifying alembic parity against live volume"
LIVE_HEAD="$(docker --context colima exec codex-lb python -c "import sqlite3; c=sqlite3.connect('/var/lib/codex-lb/store.db'); print(c.execute('SELECT version_num FROM alembic_version').fetchone()[0])")"
echo "    live volume head: $LIVE_HEAD"

NEW_IMAGE_HAS_HEAD="$(docker --context colima run --rm --entrypoint sh "$IMAGE_TAG" -c "test -f /app/app/db/alembic/versions/${LIVE_HEAD}.py && echo yes || echo no")"
if [ "$NEW_IMAGE_HAS_HEAD" != "yes" ]; then
  echo "FATAL: new image $IMAGE_TAG is missing alembic revision $LIVE_HEAD" >&2
  echo "       deploying it would crash-loop on MigrationBootstrapError" >&2
  echo "       see ~/workspace-wiki/wiki/projects/codex-lb/index.md (Class C runtime discipline)" >&2
  exit 1
fi
echo "    new image contains $LIVE_HEAD: OK"

echo "==> Retagging $IMAGE_TAG as codex-lb:active"
docker --context colima tag "$IMAGE_TAG" codex-lb:active

echo "==> Force-recreating container"
docker --context colima compose -f "$LIVE_COMPOSE" up -d --force-recreate

echo "==> Waiting for /health"
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sS -o /dev/null -w "" "$HEALTH_URL" 2>/dev/null; then
    CODE="$(curl -sS -o /dev/null -w "%{http_code}" "$HEALTH_URL")"
    if [ "$CODE" = "200" ]; then
      break
    fi
  fi
  if [ "$i" = "10" ]; then
    echo "FATAL: /health did not return 200 within 10 attempts" >&2
    echo "       check: docker --context colima logs --tail 100 codex-lb" >&2
    exit 1
  fi
  sleep 2
done
echo "    /health: 200"

echo "==> Verifying current_revision in container logs"
CURRENT_REVISION="$(docker --context colima logs --tail 200 codex-lb 2>&1 | grep -oE 'current_revision=[a-z0-9_]+' | tail -1 || true)"
if [ -z "$CURRENT_REVISION" ]; then
  echo "WARN: no current_revision line found in last 200 log lines (may be a clean restart with quieter logging)" >&2
else
  echo "    $CURRENT_REVISION"
fi

if docker --context colima logs --tail 200 codex-lb 2>&1 | grep -q "MigrationBootstrapError"; then
  echo "FATAL: container is crash-looping with MigrationBootstrapError" >&2
  echo "       this should have been caught by the alembic parity check above" >&2
  exit 1
fi

echo ""
echo "==> Deploy complete"
echo "    image:  $IMAGE_TAG  (also tagged codex-lb:active)"
echo "    health: 200"
echo "    HEAD:   $SHORT_SHA"
