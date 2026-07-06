## Migration

Alembic revision `20260705_000000_harden_dashboard_session_ttl` changes the `dashboard_settings.dashboard_session_ttl_seconds` server default to `31536000` and updates existing rows only when they still equal the legacy default `43200`. Its downgrade restores rows carrying the new default back to `43200` before older app versions can issue one-year dashboard sessions directly.

## Guardrail

The 1-year effective TTL is intentionally limited to standard dashboard auth mode when the request has a loopback socket peer, uses a loopback dashboard URL, and has no forwarded-client headers. `CODEX_LB_DASHBOARD_TRUST_LOOPBACK_HOST_HEADER_FOR_LONG_SESSIONS=true` does not make Docker bridge peers or other non-loopback socket peers eligible for a long session; spoofed loopback Host headers still receive the 12-hour fallback when the configured value exceeds 30 days.
