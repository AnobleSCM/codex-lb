#!/usr/bin/env bash
# Local deploy for codex-lb. Builds the current source tree as
# codex-lb:local-<short-sha>, verifies the new image contains every
# alembic revision available in the running image, retags the new image
# as codex-lb:active, force-recreates the container via the live compose
# file, and confirms /health=200 plus a clean current_revision in
# container logs.
#
# Exits non-zero on any failure. Safe to re-run.
#
# Usage: scripts/codex-lb-deploy.sh
#
# Requires:
#   - cwd is the codex-lb repo root
#   - working tree is clean (or you accept that uncommitted changes ship)
#   - docker --context colima is available
#   - docker buildx (BuildKit) is installed (brew install docker-buildx)
#   - the live compose lives at ~/.codex/codex-lb/docker-compose.yml

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

SHORT_SHA="$(git rev-parse --short HEAD)"
IMAGE_TAG="codex-lb:local-${SHORT_SHA}"
LIVE_COMPOSE="${HOME}/.codex/codex-lb/docker-compose.yml"
HEALTH_URL="http://127.0.0.1:2455/health"
DRAIN_STATUS_URL="${CODEX_LB_DEPLOY_DRAIN_STATUS_URL:-http://127.0.0.1:2455/internal/drain/status}"
DRAIN_START_URL="${CODEX_LB_DEPLOY_DRAIN_START_URL:-http://127.0.0.1:2455/internal/drain/start}"
DRAIN_STOP_URL="${CODEX_LB_DEPLOY_DRAIN_STOP_URL:-http://127.0.0.1:2455/internal/drain/stop}"
DEPLOY_DRAIN_TIMEOUT_SECONDS="${CODEX_LB_DEPLOY_DRAIN_TIMEOUT_SECONDS:-900}"
DEPLOY_DRAIN_POLL_SECONDS="${CODEX_LB_DEPLOY_DRAIN_POLL_SECONDS:-2}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ALEMBIC_VERSIONS_DIR="/app/app/db/alembic/versions"
DRAIN_STARTED=0

fatal() {
  echo "FATAL: $*" >&2
  exit 1
}

drain_request() {
  local method="$1"
  local url="$2"
  docker --context colima exec codex-lb python -c "
import sys
import urllib.request

request = urllib.request.Request(sys.argv[1], method=sys.argv[2])
with urllib.request.urlopen(request, timeout=10) as response:
    sys.stdout.buffer.write(response.read())
" "$url" "$method"
}

cleanup_drain_on_exit() {
  local exit_code=$?
  trap - EXIT
  if [ "$exit_code" -ne 0 ] && [ "$DRAIN_STARTED" -eq 1 ]; then
    echo "==> Stopping live drain after failed deploy" >&2
    if drain_request POST "$DRAIN_STOP_URL" >/dev/null; then
      echo "    live drain stopped" >&2
    else
      echo "WARN: unable to stop live drain at $DRAIN_STOP_URL; manual recovery may be required" >&2
    fi
  fi
  exit "$exit_code"
}

trap cleanup_drain_on_exit EXIT

drain_check() {
  local key="$1"
  "$PYTHON_BIN" -c "
import json
import sys

try:
    payload = json.load(sys.stdin)
    checks = payload.get('checks', {})
    if not isinstance(checks, dict):
        raise TypeError('checks is not an object')
    value = checks.get(sys.argv[1], '')
    # The shell caller matches lowercase true|false; Python bools print as
    # True/False, which made every real JSON drain response unparseable.
    if isinstance(value, bool):
        print('true' if value else 'false')
    else:
        print(value)
except Exception as exc:
    raise SystemExit(f'failed to parse drain status: {exc}')
" "$key"
}

read_drain_status() {
  drain_request GET "$DRAIN_STATUS_URL"
}

extract_drain_value() {
  local status_json="$1"
  local key="$2"
  printf '%s' "$status_json" | drain_check "$key"
}

extract_in_flight() {
  local status_json="$1"
  local in_flight
  in_flight="$(extract_drain_value "$status_json" "in_flight")" || return 1
  case "$in_flight" in
    ''|*[!0-9]*)
      echo "invalid in_flight value in drain status: $in_flight" >&2
      return 1
      ;;
  esac
  printf '%s' "$in_flight"
}

extract_drain_boolean() {
  local status_json="$1"
  local key="$2"
  local value
  value="$(extract_drain_value "$status_json" "$key")" || return 1
  case "$value" in
    true|false)
      printf '%s' "$value"
      ;;
    *)
      echo "invalid $key value in drain status: $value" >&2
      return 1
      ;;
  esac
}

require_idle_before_deploy() {
  local status_json
  status_json="$(read_drain_status)" || fatal "unable to read live drain status at $DRAIN_STATUS_URL"

  local draining bridge_drain_active in_flight
  draining="$(extract_drain_boolean "$status_json" "draining")" || fatal "unable to parse live drain status"
  bridge_drain_active="$(extract_drain_boolean "$status_json" "bridge_drain_active")" || fatal "unable to parse live drain status"
  in_flight="$(extract_in_flight "$status_json")" || fatal "unable to parse live drain status"

  if [ "$draining" = "true" ] || [ "$bridge_drain_active" = "true" ]; then
    fatal "live proxy is already draining; refusing to build or recreate during an active drain"
  fi
  if [ "$in_flight" -ne 0 ]; then
    fatal "live proxy has $in_flight in-flight request(s); refusing to build or recreate"
  fi

  echo "    live proxy idle: in_flight=0"
}

start_live_drain() {
  DRAIN_STARTED=1
  drain_request POST "$DRAIN_START_URL" >/dev/null || fatal "unable to start live drain at $DRAIN_START_URL"
}

wait_for_drain_zero() {
  case "$DEPLOY_DRAIN_TIMEOUT_SECONDS" in
    ''|*[!0-9]*)
      fatal "CODEX_LB_DEPLOY_DRAIN_TIMEOUT_SECONDS must be a non-negative integer"
      ;;
  esac

  local deadline=$((SECONDS + DEPLOY_DRAIN_TIMEOUT_SECONDS))
  while true; do
    local status_json in_flight draining bridge_drain_active
    status_json="$(read_drain_status)" || fatal "unable to read live drain status at $DRAIN_STATUS_URL"
    in_flight="$(extract_in_flight "$status_json")" || fatal "unable to parse live drain status"
    draining="$(extract_drain_boolean "$status_json" "draining")" || fatal "unable to parse live drain status"
    bridge_drain_active="$(extract_drain_boolean "$status_json" "bridge_drain_active")" || fatal "unable to parse live drain status"
    # in_flight=0 alone is racy: until the drain flags latch, the proxy is
    # still admitting new work, and a request accepted between this poll and
    # the recreate would be killed. Require the SAME status read to show the
    # drain latched AND zero in-flight before declaring the drain complete.
    if [ "$in_flight" -eq 0 ] && [ "$draining" = "true" ] && [ "$bridge_drain_active" = "true" ]; then
      echo "    drain complete: draining=true bridge_drain_active=true in_flight=0"
      return 0
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      fatal "live proxy not drained after ${DEPLOY_DRAIN_TIMEOUT_SECONDS}s (draining=$draining bridge_drain_active=$bridge_drain_active in_flight=$in_flight); not recreating"
    fi
    echo "    waiting for drain: draining=$draining bridge_drain_active=$bridge_drain_active in_flight=$in_flight"
    sleep "$DEPLOY_DRAIN_POLL_SECONDS"
  done
}

if [ ! -f "$LIVE_COMPOSE" ]; then
  echo "FATAL: live compose not found at $LIVE_COMPOSE" >&2
  exit 1
fi

# The Dockerfile uses BuildKit cache mounts (`RUN --mount=type=cache`), so the
# build needs BuildKit plus the buildx plugin. The docker CLI falls back to the
# legacy builder unless DOCKER_BUILDKIT=1, and buildx must be installed
# (`brew install docker-buildx`). Force BuildKit and fail early with an
# actionable message instead of failing mid-build. (2026-05-21: buildx was not
# re-wired in the Docker Desktop -> Homebrew migration and broke this deploy.)
export DOCKER_BUILDKIT=1
if ! docker buildx version >/dev/null 2>&1; then
  echo "FATAL: docker buildx is required (the Dockerfile uses BuildKit cache mounts) but is unavailable." >&2
  echo "       Install it with: brew install docker-buildx" >&2
  exit 1
fi

echo "==> Checking live proxy idle gate"
require_idle_before_deploy

echo "==> Building $IMAGE_TAG from $REPO_ROOT (HEAD=$SHORT_SHA)"
docker --context colima build -t "$IMAGE_TAG" .

echo "==> Verifying alembic parity against running image"
ALEMBIC_INVENTORY_PYTHON="
from pathlib import Path

for migration in sorted(Path('$ALEMBIC_VERSIONS_DIR').glob('*.py')):
    if migration.name != '__init__.py':
        print(migration.stem)
"

if ! LIVE_REVISIONS="$(docker --context colima exec codex-lb python -c "$ALEMBIC_INVENTORY_PYTHON")"; then
  fatal "unable to read alembic revision inventory from the running container"
fi
if [ -z "$LIVE_REVISIONS" ]; then
  fatal "running container has no readable alembic revisions; refusing to skip parity verification"
fi

if ! NEW_IMAGE_REVISIONS="$(docker --context colima run --rm --entrypoint python "$IMAGE_TAG" -c "$ALEMBIC_INVENTORY_PYTHON")"; then
  fatal "unable to read alembic revision inventory from new image $IMAGE_TAG"
fi
if [ -z "$NEW_IMAGE_REVISIONS" ]; then
  fatal "new image $IMAGE_TAG has no readable alembic revisions"
fi

if ! MISSING_REVISIONS="$("$PYTHON_BIN" -c "
import sys

live_revisions = set(sys.argv[1].splitlines())
new_image_revisions = set(sys.argv[2].splitlines())
print('\\n'.join(sorted(live_revisions - new_image_revisions)))
" "$LIVE_REVISIONS" "$NEW_IMAGE_REVISIONS")"; then
  fatal "unable to compare running and candidate alembic revision inventories"
fi

if [ -n "$MISSING_REVISIONS" ]; then
  echo "FATAL: new image $IMAGE_TAG is missing alembic revision(s) from the running image:" >&2
  while IFS= read -r revision; do
    echo "       $revision" >&2
  done <<< "$MISSING_REVISIONS"
  echo "       deploying it could crash-loop on MigrationBootstrapError" >&2
  echo "       see ~/workspace-wiki/wiki/projects/codex-lb/index.md (Class C runtime discipline)" >&2
  exit 1
fi
echo "    new image contains every running-image alembic revision: OK"

echo "==> Draining live proxy before recreate"
start_live_drain
wait_for_drain_zero

echo "==> Retagging $IMAGE_TAG as codex-lb:active"
docker --context colima tag "$IMAGE_TAG" codex-lb:active

echo "==> Force-recreating container"
docker --context colima compose -f "$LIVE_COMPOSE" up -d --force-recreate

echo "==> Waiting for /health"
for i in 1 2 3 4 5 6 7 8 9 10; do
  CODE="$(curl -sS -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")"
  if [ "$CODE" = "200" ]; then
    break
  fi
  if [ "$i" = "10" ]; then
    echo "FATAL: /health did not return 200 within 10 attempts (last code: $CODE)" >&2
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
