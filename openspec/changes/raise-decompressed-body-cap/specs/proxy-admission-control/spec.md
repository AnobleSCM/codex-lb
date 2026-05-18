## ADDED Requirements

### Requirement: Request body decompression cap leaves headroom for the responses slimmer
The `request_decompression` middleware MUST enforce a hard ceiling on decompressed request body size to bound worst-case in-memory allocation from compressed payloads. The default ceiling MUST be set well above realistic tool-heavy Codex CLI session sizes (observed worst case ≈ 40-80 MiB decompressed for a 30-turn Computer Use run) so that the proxy-side `response.create` slimmer (`_slim_response_create_payload_for_upstream`) is the effective enforcer of the upstream-correct payload size on `/backend-api/codex/responses` and `/v1/responses`. Concretely, the default MUST be at least `128 * 1024 * 1024` bytes (128 MiB), which sits approximately 8× above `Settings.upstream_response_create_max_bytes` (15 MiB) and gives the slimmer the headroom it needs to strip historical screenshots before the request reaches OpenAI. The default MUST NOT be set so low that a request which the slimmer could otherwise reduce below `upstream_response_create_max_bytes` is rejected by the middleware before the slimmer runs.

#### Scenario: Long Computer Use session passes admission so the slimmer can run
- **GIVEN** an incoming `POST /backend-api/codex/responses` request whose body is `Content-Encoding: gzip`
- **AND** the decompressed body is larger than `Settings.upstream_response_create_max_bytes` but at most `Settings.max_decompressed_body_bytes`
- **AND** the body contains historical `function_call_output` items whose strings carry `data:image/...` base64 screenshots
- **WHEN** the request passes through the `request_decompression` middleware
- **THEN** the middleware MUST admit the request (no 413 response from the middleware)
- **AND** the request MUST reach the responses handler where the slimmer can strip historical screenshots
- **AND** the slimmer MUST be able to bring the upstream `response.create` payload below `Settings.upstream_response_create_max_bytes` and forward it to OpenAI

#### Scenario: Decompressed body above the hard cap is rejected with 413
- **GIVEN** an incoming request with any supported `Content-Encoding`
- **WHEN** decompression would produce a body strictly larger than `Settings.max_decompressed_body_bytes`
- **THEN** the middleware MUST return HTTP 413 with `dashboard_error("payload_too_large", "Request body exceeds the maximum allowed size")`
- **AND** the middleware MUST NOT materialize the full oversized body in memory beyond the configured ceiling
- **AND** the handler downstream of the middleware MUST NOT be invoked

#### Scenario: Decompressed body crossing 80% of the cap emits an operational warning
- **GIVEN** an incoming request with any supported `Content-Encoding`
- **WHEN** the decompressed body size is at least 80% of `Settings.max_decompressed_body_bytes` but at most the cap
- **THEN** the middleware MUST admit the request normally
- **AND** the middleware MUST emit a single `WARNING`-level log record from `app.core.middleware.request_decompression` whose message contains `Large decompressed request body`, the current `request_id`, the request path, the decompressed byte count, and the configured `max_bytes`
- **AND** decompressed bodies below 80% of the cap MUST NOT emit this warning

#### Scenario: Operators can override the cap without code changes
- **GIVEN** the operator sets `CODEX_LB_MAX_DECOMPRESSED_BODY_BYTES` in the runtime environment
- **WHEN** the application reads `Settings.max_decompressed_body_bytes`
- **THEN** the configured value MUST take precedence over the default
- **AND** the value MUST be `> 0` (Pydantic field validator), so setting `0` or a negative value MUST fail startup with a clear validation error
