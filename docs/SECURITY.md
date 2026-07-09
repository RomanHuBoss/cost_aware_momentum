# Security

## Supported security posture

- Advisory-only operation; no implemented order create/amend/cancel/withdraw methods.
- PostgreSQL-only persistence; no hidden SQLite fallback.
- Explicit operator authentication and signed session handling.
- Secrets belong in environment configuration, never in release archives.
- Production configuration must not enable demo or uncalibrated actionable baseline behavior.
- Fail-closed behavior is preferred over silent fallback.

## Release hygiene

Release artifacts must exclude `.env`, credentials, bytecode caches, virtual environments, build outputs, dumps, logs, and real model artifacts. `scripts/release_integrity.py` verifies required release evidence and forbidden artifact absence.

## 1.52.13 note

No new credentials, scopes, Bybit trading permissions, or exchange write endpoints were added.
