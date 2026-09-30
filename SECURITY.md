# Security Policy

## Supported versions

Only the latest `master` (and the latest tagged release) receives security fixes.

## Design principles

- **Local-first.** The API binds to `127.0.0.1` and is meant to stay on your machine or inside your LAN/VPN. If you expose it, put TLS + authentication (reverse proxy) in front.
- **Guarded egress.** Every outbound HTTP call in the engine goes through `scripts/sec_guard.py`: http/https only, DNS-resolved IP checks (private / loopback / link-local / cloud-metadata ranges blocked), redirects re-validated per hop, filesystem access contained to the vault.
- **Secrets in `.env`, never in code.** `.env` is git-ignored; `.env.example` documents every variable.
- **Data is yours.** Data folders are git-ignored by default; nothing is telemetry-phoned home. The optional mobile-hub push (`HUB_*`) is disabled unless explicitly configured.

## Reporting a vulnerability

Please report privately:

1. Open a GitHub **Security Advisories** draft (Repo → Security → Advisories → New draft), **or**
2. Email: **hello@automata.sale** with subject `automata-crm security`.

Include reproduction steps and, if possible, a minimal PoC. Please do not open public issues for vulnerabilities. You will get a response within 72 hours; fixes ship as patch releases credited to the reporter (unless you prefer anonymity).
