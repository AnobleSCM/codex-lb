# AGENTS

## Environment

- Python: .venv/bin/python (uv, CPython 3.13.3)
- GitHub auth for git/API is available via env vars: `GITHUB_USER`, `GITHUB_TOKEN` (PAT). Do not hardcode or commit tokens.
- For authenticated git over HTTPS in automation, use: `https://x-access-token:${GITHUB_TOKEN}@github.com/<owner>/<repo>.git`

## Code Conventions

The `/project-conventions` skill is auto-activated on code edits (PreToolUse guard).

| Convention | Location | When |
|-----------|----------|------|
| Code Conventions (Full) | `/project-conventions` skill | On code edit (auto-enforced) |
| Git Workflow | `.agents/conventions/git-workflow.md` | Commit / PR |

## Workflow (OpenSpec-first)

This repo uses **OpenSpec as the primary workflow and SSOT** for change-driven development.

### How to work (default)

1) Find the relevant spec(s) in `openspec/specs/**` and treat them as source-of-truth.
2) If the work changes behavior, requirements, contracts, or schema: create an OpenSpec change in `openspec/changes/**` first (proposal -> tasks).
3) Implement the tasks; keep code + specs in sync (update `spec.md` as needed).
4) Validate specs locally: `openspec validate --specs`
5) When done: verify + archive the change (do not archive unverified changes).

### Source of Truth

- **Specs/Design/Tasks (SSOT)**: `openspec/`
  - Active changes: `openspec/changes/<change>/`
  - Main specs: `openspec/specs/<capability>/spec.md`
  - Archived changes: `openspec/changes/archive/YYYY-MM-DD-<change>/`

## Documentation & Release Notes

- **Do not add/update feature or behavior documentation under `docs/`**. Use OpenSpec context docs under `openspec/specs/<capability>/context.md` (or change-level context under `openspec/changes/<change>/context.md`) as the SSOT.
- **Do not edit `CHANGELOG.md` directly.** Leave changelog updates to the release process; record change notes in OpenSpec artifacts instead.

### Documentation Model (Spec + Context)

- `spec.md` is the **normative SSOT** and should contain only testable requirements.
- Use `openspec/specs/<capability>/context.md` for **free-form context** (purpose, rationale, examples, ops notes).
- If context grows, split into `overview.md`, `rationale.md`, `examples.md`, or `ops.md` within the same capability folder.
- Change-level notes live in `openspec/changes/<change>/context.md` or `notes.md`, then **sync stable context** back into the main context docs.

Prompting cue (use when writing docs):
"Keep `spec.md` strictly for requirements. Add/update `context.md` with purpose, decisions, constraints, failure modes, and at least one concrete example."

### Commands (recommended)

- Start a change: `/opsx:new <kebab-case>`
- Create artifacts (step): `/opsx:continue <change>`
- Create artifacts (fast): `/opsx:ff <change>`
- Implement tasks: `/opsx:apply <change>`
- Verify before archive: `/opsx:verify <change>`
- Sync delta specs → main specs: `/opsx:sync <change>`
- Archive: `/opsx:archive <change>`

## Contributing & Merge Gates

When authoring or merging a PR (as a human contributor, a collaborator,
or an AI assistant acting on behalf of either), the binding workflow is
in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). The sections
an AI assistant most often needs are:

- [Merge gates](.github/CONTRIBUTING.md#merge-gates) — CI green +
  `@codex review` clean (or findings addressed) + `mergeable=CLEAN` +
  OpenSpec change folder for behavior changes + `Fixes #N` /
  `Closes #N` for issue cover.
- [Collaborator rules](.github/CONTRIBUTING.md#collaborator-rules) —
  no self-merge by default; large PRs get split (≈1-concern per PR,
  ~800 net lines / scoped capability ceiling).
- [Bus factor escape hatch](.github/CONTRIBUTING.md#bus-factor-escape-hatch)
  — self-merge allowed after **14 days** with all gates met and a
  comment invoking the clause.

An assistant preparing a merge MUST verify the gates against the
actual GitHub state (status check rollup, codex review submissions,
`mergeable` field) rather than asserting them from local history.
Local `uv run pytest` / `uv run ruff` / `codex review --base origin/main`
are encouraged but not substitutes for the cloud gates.

## Live Runtime Discipline (Class C image-pin trap)

This repo is the **source code** for codex-lb. It is NOT the live runtime.

**The live MacBook codex-lb container is managed by a different compose file:**

```text
/Users/andrewnoble/.codex/codex-lb/docker-compose.yml
```

That live compose pins `image: codex-lb:active` — a Docker tag alias that
always points at the currently-deployed local build. The repo's own
`docker-compose.yml` defines a service named `server` and is for repo-local
testing, NOT for live deployment.

**Hard rules when working on codex-lb in this repo:**

1. **Do not change the live compose to `ghcr.io/soju06/codex-lb:latest`** or run
   `docker compose pull` against the live compose. The persistent
   `codex-lb-data` volume may have a schema revision the public image lacks,
   which causes an unrecoverable `MigrationBootstrapError` crash loop on
   startup. Discovered 2026-05-17.

2. **When publishing a new image for live deployment:**
   - Build locally; tag as `codex-lb:local-<short-sha>`.
   - Verify the new image's `/app/app/db/alembic/versions/` contains every
     revision the live `codex-lb-data` volume has applied.
   - Re-tag the new image as the stable alias:
     `docker --context colima tag codex-lb:local-<short-sha> codex-lb:active`.
   - Recreate the live container so it resolves the new image:
     `docker --context colima compose -f /Users/andrewnoble/.codex/codex-lb/docker-compose.yml up -d --force-recreate`.
     `docker restart` alone is not sufficient — the running container is
     pinned to its original image id at creation, so a tag swap on
     `codex-lb:active` only takes effect on container recreate. Verify with
     `docker --context colima inspect codex-lb --format '{{.Config.Image}} {{.Image}}'`
     and confirm the image sha matches the new `codex-lb:local-<short-sha>` build.
   - Verify `/health` returns 200 and check container logs for
     `current_revision=<expected>` instead of `MigrationBootstrapError`.

3. **When adding new alembic migrations**, document the revision id in the
   change's `openspec/changes/<change>/context.md` so future operators know
   which deployed image is required to read this schema.

4. **Pre-startup sanity check (future work):** the application should emit
   a clear warning like `image alembic head=<X> but DB alembic_version=<Y>;
   cannot start` before crash-looping. Tracked in
   `~/Developer/ecosystem-alignment/docs/superpowers/plans/2026-05-17-codex-lb-stream-disconnect-rca.md`
   P6 item 3.

**Full incident write-up:**
- RCA: `~/Developer/ecosystem-alignment/docs/superpowers/plans/2026-05-17-codex-lb-stream-disconnect-rca.md`
- Cross-agent broadcast: `~/workspace-wiki/wiki/message-board/active/2026-05-17-codex-lb-image-pin-discipline.md`
- Wiki project page: `~/workspace-wiki/wiki/projects/codex-lb/index.md`
