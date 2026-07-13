# Harden sticky-session upsert concurrency

## Summary

Make sticky-session upserts return the mapping written by the database operation
without a post-commit readback that can race with another worker deleting or
rebinding the same key.

## Why

Concurrent proxy traffic can legitimately update the same durable affinity key.
The current upsert commits successfully and then performs a separate SELECT and
refresh. A competing delete or rebind in either gap turns a successful write into
`StickySession upsert failed` or SQLAlchemy's `Could not refresh instance`, which
can fail an otherwise healthy request.

## Scope

- Sticky-session repository upsert behavior for SQLite and PostgreSQL.
- Deterministic regression coverage for a concurrent delete after commit.
- No database schema, migration, routing-policy, live-runtime, or configuration
  change.
