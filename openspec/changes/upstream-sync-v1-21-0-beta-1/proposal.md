# Upstream sync to codex-lb v1.21.0-beta.1

## Why

The AnobleSCM fork of codex-lb had drifted **311 commits behind** upstream
`Soju06/codex-lb`. That drift was no longer cosmetic — it was breaking the live
proxy against current Codex CLI clients:

- Modern Codex CLI request payloads were **400-erroring** against the fork's
  stale request schemas: upstream Responses-API validation had moved on, so
  current clients tripped `Field required` and rejected the `instructions`
  parameter the fork's older models did not model.
- Session continuity regressed: the fork missed upstream's
  `previous_response_not_found` continuity handling, so multi-turn Codex
  sessions lost their prior-response linkage.

The divergence inventory (AGE-3087) showed the fork's own patches had largely
been **overtaken by upstream** — the same problems were fixed upstream, usually
better and with more test coverage. Re-basing 311 commits of hand-carried
history onto current upstream would have been a high-risk, low-value merge.

The decision (AGE-3086 / AGE-3087) is therefore **reset-and-reimplement**: make
the fork's new `main` be upstream `v1.21.0-beta.1` (commit `65dc4b75`) verbatim,
then re-implement only the small set of **consciously-carried** fork patches
against current upstream code as isolated, reviewed commits.

## What changes

- The fork `main` is reset to upstream `65dc4b75` (`v1.21.0-beta.1`).
- A small set of fork patches is re-implemented against current upstream as
  separate carry-lane commits:
  - **Lane 2** — shrink the no-reset quota fallback from 3600s to 900s
    (fork `fea73d5c`).
  - **Lane 3** — surface upstream degradation on `/health`
    (`{"status","degradation":{"level","reason"},"available_accounts"}`)
    (fork `9005277b`).
  - **Lane 4** — own/close DB sessions in the three non-request session borrows
    (fork `d350ce4d`, #12).
  - **Lane 5** — carry the single-container deploy tooling
    (`scripts/codex-lb-deploy.sh` + tests), the `.codex -> .agents` symlink, and
    the "Live Runtime Discipline (Class C image-pin trap)" safety rail in
    AGENTS.md (fork #8/#10/#21/#23 + #3).
- **Lane 1** (fork #1/#2 RATE_LIMITED early recovery) is **NOT** carried: current
  upstream already covers both semantics (see `context.md`).
- Everything else the fork carried is either already in upstream or deliberately
  retired (full disposition in `context.md`).

## Impact

- **No new capability spec** — this is a sync/meta change. The behavior of the
  carried lanes is documented per-lane in their commit messages and in
  `context.md`; the normative specs are upstream's own `openspec/specs/**`.
- **Operators** must review the breaking-config list in `context.md`
  (`CODEX_LB_DATA_DIR` pinning, websocket `trust_env` auto-detect, `smart`
  transport default, 7200s stream-idle default, 1-year dashboard loopback
  session TTL, Python 3.14 image) before the live cutover.
- **Rollback is a database restore**, not a code revert: several upstream
  migrations between the fork base and `v1.21.0-beta.1` have lossy or no-op
  downgrades, so reverting the image without restoring the pre-cutover
  `codex-lb-data` snapshot risks an unrecoverable schema mismatch.
- **Risk** is bounded: the reset is to a tagged upstream beta, and each carry
  lane is small, independently tested, and reviewable in isolation.
