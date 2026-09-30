# Contributing

Thanks for considering a contribution!

## Ways to help

- **Bug reports** — open an issue with: what you did, what happened, what you expected, OS / Python / Node versions, relevant log tail.
- **Small fixes** — PRs are welcome: one logical change per PR, describe *why*, keep diffs minimal.
- **i18n** — the dashboard UI is currently Russian-only; help with the English translation is the single most wanted contribution.

## Ground rules

1. The vault layout (`10_Clients/`, `30_Invoices/`, …) is a public contract — do not rename data folders without a migration script in `migrations/`.
2. Any new outbound-network code **must** use guards from `scripts/sec_guard.py` (`guard_open`, `guard_urlopen`, `guard_requests_get/post`) — PRs with raw `requests.`/`urlopen(` calls in the engine will be asked to rework.
3. No secrets, personal data or client names in code, tests or examples — use `.env` and `{{placeholders}}`.
4. `./update.sh` must stay idempotent and never touch data folders.

## Dev loop

```bash
./install.sh
./venv/bin/python -m py_compile scripts/*.py   # syntax gate
cd dashboard && npm install && npm run build   # frontend gate
```
