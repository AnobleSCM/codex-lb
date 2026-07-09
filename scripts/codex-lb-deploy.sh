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
DRAIN_STARTED=0

fatal() {
  echo "FATAL: $*" >&2
  exit 1
}

cleanup_drain_on_exit() {
  local exit_code=$?
  trap - EXIT
  if [ "$exit_code" -ne 0 ] && [ "$DRAIN_STARTED" -eq 1 ]; then
    echo "==> Stopping live drain after failed deploy" >&2
    if curl -fsS -X POST "$DRAIN_STOP_URL" >/dev/null; then
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
    print(checks.get(sys.argv[1], ''))
except Exception as exc:
    raise SystemExit(f'failed to parse drain status: {exc}')
" "$key"
}

read_drain_status() {
  curl -fsS "$DRAIN_STATUS_URL"
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

require_idle_before_deploy() {
  local status_json
  status_json="$(read_drain_status)" || fatal "unable to read live drain status at $DRAIN_STATUS_URL"

  local draining bridge_drain_active in_flight
  draining="$(extract_drain_value "$status_json" "draining")" || fatal "unable to parse live drain status"
  bridge_drain_active="$(extract_drain_value "$status_json" "bridge_drain_active")" || fatal "unable to parse live drain status"
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
  curl -fsS -X POST "$DRAIN_START_URL" >/dev/null || fatal "unable to start live drain at $DRAIN_START_URL"
}

wait_for_drain_zero() {
  case "$DEPLOY_DRAIN_TIMEOUT_SECONDS" in
    ''|*[!0-9]*)
      fatal "CODEX_LB_DEPLOY_DRAIN_TIMEOUT_SECONDS must be a non-negative integer"
      ;;
  esac

  local deadline=$((SECONDS + DEPLOY_DRAIN_TIMEOUT_SECONDS))
  while true; do
    local status_json in_flight
    status_json="$(read_drain_status)" || fatal "unable to read live drain status at $DRAIN_STATUS_URL"
    in_flight="$(extract_in_flight "$status_json")" || fatal "unable to parse live drain status"
    if [ "$in_flight" -eq 0 ]; then
      echo "    drain complete: in_flight=0"
      return 0
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      fatal "live proxy still has $in_flight in-flight request(s) after ${DEPLOY_DRAIN_TIMEOUT_SECONDS}s; not recreating"
    fi
    echo "    waiting for in-flight requests to drain: in_flight=$in_flight"
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

echo "==> Verifying alembic parity against live volume"
# Read live volume head defensively: a fresh volume has no alembic_version
# row (or no table at all), in which case there is nothing to verify and
# the regular alembic upgrade path will populate it on next start.
LIVE_HEAD="$(docker --context colima exec codex-lb python -c "
import sqlite3
try:
    c = sqlite3.connect('/var/lib/codex-lb/store.db')
    row = c.execute('SELECT version_num FROM alembic_version').fetchone()
    print(row[0] if row else '')
except sqlite3.OperationalError:
    print('')
" 2>/dev/null)"

if [ -z "$LIVE_HEAD" ]; then
  echo "    live volume head: <fresh, no alembic_version yet — skipping parity check>"
else
  echo "    live volume head: $LIVE_HEAD"
  NEW_IMAGE_HAS_HEAD="$(docker --context colima run --rm --entrypoint sh "$IMAGE_TAG" -c "test -f /app/app/db/alembic/versions/${LIVE_HEAD}.py && echo yes || echo no")"
  if [ "$NEW_IMAGE_HAS_HEAD" != "yes" ]; then
    echo "FATAL: new image $IMAGE_TAG is missing alembic revision $LIVE_HEAD" >&2
    echo "       deploying it would crash-loop on MigrationBootstrapError" >&2
    echo "       see ~/workspace-wiki/wiki/projects/codex-lb/index.md (Class C runtime discipline)" >&2
    exit 1
  fi
  echo "    new image contains $LIVE_HEAD: OK"
fi

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
