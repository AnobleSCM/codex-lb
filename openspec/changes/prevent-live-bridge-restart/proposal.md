# Prevent live bridge restart during executor work

## Problem

The local `scripts/codex-lb-deploy.sh` path can force-recreate the live
`codex-lb` container without first proving that the proxy has no active
Responses bridge work. A container recreation during an executor turn closes
the in-memory bridge stream and can orphan continuity state for the active
session.

The application already exposes loopback-only drain primitives and the Helm
chart already uses them during Kubernetes termination. The local deploy helper
needs the same safety gate before `docker compose up -d --force-recreate`.

Single-container Docker Compose examples also need to pin a stable
`CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_INSTANCE_ID`. Without an explicit value,
the application defaults to the container hostname, which changes on recreation.

## Proposed behavior

- Refuse local deploy before build/recreate when `/internal/drain/status`
  reports active in-flight work or an already active drain.
- After the new image is built and alembic parity is verified, start drain on
  the live proxy, wait for in-flight work to reach zero, then retag and
  force-recreate the container.
- Keep the gate fail-closed when drain status cannot be read or parsed.
- Pin stable single-container bridge instance IDs in the repo Compose templates.

## Non-goals

- No live deploy, restart, or compose mutation is performed by this change.
- No provider/runtime retry policy change is included.
- No migration or schema change is included.

