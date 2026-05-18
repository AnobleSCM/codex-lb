## Why

The `request_decompression` middleware (`app/core/middleware/request_decompression.py`) rejects incoming requests with HTTP 413 whenever the decompressed body exceeds `Settings.max_decompressed_body_bytes`. The default is currently `32 * 1024 * 1024` (32 MiB) and codex-lb ships with no per-endpoint override.

On the `/backend-api/codex/responses` and `/v1/responses` paths, that cap collides with a deliberate downstream safety net. The proxy already implements a slimmer (`_slim_response_create_payload_for_upstream` in `app/core/clients/proxy.py:1493`) that strips historical screenshots and oversized `function_call_output` blobs so a long Codex CLI conversation can fit under OpenAI's 15 MiB `response.create` websocket frame cap (`Settings.upstream_response_create_max_bytes`). The slimmer only runs after the middleware admits the request. With the cap at 32 MiB, long-running Computer Use / Chrome DevTools sessions decompress past the middleware threshold (cumulative base64 screenshots + conversation history), get rejected, and never reach the slimmer that exists for exactly this case.

Observed 2026-05-18 on Andrew's MacBook (live runtime `codex-lb:active`): 28× `POST /backend-api/codex/responses → 413 Content Too Large` in 6 hours, arriving in 5-event retry bursts (matches Codex CLI's reconnect loop). Zero `Slimmed response.create before upstream websocket connect` warnings during the same window, confirming the slimmer never ran. The Codex CLI surface shows `unexpected status 413 Payload Too Large: Request body exceeds the maximum allowed size` — verbatim match for `request_decompression.py` line 142, not the slimmer's "response.create is too large for upstream websocket" envelope.

The 32 MiB default was set as a generic decompression-bomb ceiling without coordination with the slimmer's headroom needs. The slimmer's effective reduction on tool-heavy historical inputs is one to two orders of magnitude (a multi-MB screenshot becomes a one-line omission notice), so the middleware can safely admit much larger raw bodies while still bounding worst-case memory.

## What Changes

- Raise `Settings.max_decompressed_body_bytes` default from `32 * 1024 * 1024` to `128 * 1024 * 1024` in `app/core/config/settings.py`. The cap stays a hard OOM ceiling — it just sits above realistic Computer Use / DevTools session sizes (observed worst case ≈ 40-80 MiB decompressed for a 30-turn tool-heavy run) so the slimmer is what actually enforces the upstream-correct payload size.
- Add a `Large decompressed request body request_id=... path=... bytes=... max_bytes=...` warning log in `request_decompression.py` when the decompressed body crosses 80% of `max_decompressed_body_bytes`. Mirrors the existing 80%-of-cap warning pattern in `_UPSTREAM_RESPONSE_CREATE_WARN_BYTES` (`app/core/clients/proxy.py:1461`). Gives operators visibility before the next ceiling is hit.
- Add unit tests in `tests/unit/test_request_decompression_middleware.py` covering: warning fires at >= 80% of cap, no warning under that threshold, and a regression guard that the default is at least 128 MiB.
- Add an `ADDED Requirements` delta to the `proxy-admission-control` capability documenting the slimmer-is-the-enforcer architecture so the relationship survives future config tuning.

## Impact

- **Operators:** Default `CODEX_LB_MAX_DECOMPRESSED_BODY_BYTES` rises from 32 MiB to 128 MiB. Existing explicit overrides are honored unchanged (the env var has always been authoritative when set). Worst-case in-memory body size per concurrent decompression rises by 4×; container memory budgets that assumed the 32 MiB ceiling should be reviewed if they were tightly fitted.
- **Clients:** Long Codex CLI Computer Use / Chrome DevTools sessions stop hitting false `413 Payload Too Large` at the proxy. The slimmer reduces the historical input before the upstream `response.create` and the request reaches OpenAI under the 15 MiB frame cap.
- **Observability:** A new structured warning log fires when any request decompresses above 80% of the cap. No change to existing 413 envelopes or status codes.
- **Behavior unchanged:** No change to the inner `upstream_response_create_max_bytes` cap (15 MiB) or to the slimmer's logic. No change to the 413 envelope, error code, or message string. No change to non-compressed (`identity`) request handling. No change to admission-control on any other endpoint.
- **No API surface change.** No new env var. No migration. No image-pin / alembic interaction (the change is pure config default + middleware logging).
