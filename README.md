# Automata CRM

**A self-hosted, AI-agent CRM that lives in plain Markdown.**

No cloud. No vendor lock-in. Your entire CRM — clients, deals, invoices, tasks, chat history — is a folder of readable `.md` files (an Obsidian vault), with a Python engine and a live dashboard on top. AI coding agents (ZCode, Claude Code or compatible CLIs) become your CRM operators: they read and update the same files you can open in any text editor.

[Quickstart](#quickstart) · [Features](#features) · [Architecture](#architecture) · [Configuration](#configuration) · [Updating](#updating) · [Roadmap](#roadmap) · [README на русском](README.ru.md)

---

## Why plain Markdown?

- **It survives everything.** No database to corrupt, no export formats to pray for. Ten years from now the files are still readable, greppable, diffable in git.
- **The agent is the interface.** Because the CRM is just files + scripts, a coding agent with a skills folder can operate it end-to-end: draft an invoice, triage the morning inbox, remind a client about a signed act — while you watch the diff.
- **Local-first and private.** Data never leaves your machine. Every outbound network call in the engine goes through `sec_guard` (SSRF / path-traversal protection, private-network egress blocked).
- **Real production mileage.** This is not a demo — it is the working CRM of a solo 1C-Bitrix integrator, running daily since 2025.

## Features

| Area | What you get |
|---|---|
| **Unified communications** | Telegram (bot + personal account via a tiny VPS gateway), MAX messenger, multi-mailbox email (IMAP) — everything lands in one inbox; unknown senders are auto-filed as leads |
| **Client cards** | Full Markdown templates: contacts, decision-makers, contracts, service history, communication style notes |
| **Money** | Invoice & act generation (PDF), monthly auto-invoicing, [Tochka Bank](https://tochka.com) open-API integration (bills, acts, payment status, delivery by email/EDO), automatic payment reconciliation |
| **Site monitoring** | Uptime, SSL certificate and domain-expiry alerts, PageSpeed checks, GEO/SEO audits (visibility in LLM answers) |
| **Tasks** | Eisenhower matrix, SLA timers, finance reminders, daily brief |
| **Dashboard** | Unified three-column chat feed, client card, health widgets, mail tab with attachments and CRM cross-links, KPI charts |
| **Security** | `sec_guard` module: guarded `open`/`urlopen`/`requests` for every script — DNS-resolved SSRF checks, path-traversal containment |
| **Voice UI** (optional) | Hologram assistant with TTS (edge-tts / ElevenLabs fallback) |
| **Agent-native** | Skills layout for coding-agent CLIs — the agent reads the vault, runs the scripts, reports back |

> The dashboard UI is currently in Russian; i18n is first on the roadmap. All data structures and code comments follow the same layout regardless.

## Architecture

```
┌───────────────────────────── your machine ─────────────────────────────┐
│                                                                         │
│   Vault (Markdown / Obsidian)          Engine (scripts/, Python)       │
│   10_Clients/   30_Invoices/    ⇄      FastAPI  api_server  :8001      │
│   25_Chats/     30_Tasks/              monitoring, billing, mail, …     │
│         ▲                                                              │
│         │ reads/writes                                                 │
│   AI agent CLI (skills/)               Dashboard (Vite + vanilla JS)   │
│                                          chat feed · client card ·     │
│   tg-gateway/ (Telethon, Docker/VPS)     mail · health · analytics     │
│   └─ Telegram ↔ MAX ↔ Email channels                                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Quickstart

Requirements: Linux, Python 3.10+, Node.js 18+, git.

```bash
git clone https://github.com/eudigitaldotru/automata-crm.git
cd automata-crm
./install.sh            # venv + Python deps + data folders
cp .env.example .env    # fill in only what you use
./start.sh              # API on :8001 + dashboard
```

Open **http://localhost:5173** — the dashboard reads the (still empty) vault. Create your first client card:

```bash
./venv/bin/python scripts/create_entity.py client "Acme LLC"
```

Then point your AI agent at the repo and let it work — see [skills layout](#agent-skills) below.

### Telegram gateway (optional)

`tg-gateway/` is a small Telethon service that bridges a personal Telegram account into the CRM (runs on any VPS or locally in Docker):

```bash
cd tg-gateway
cp .env.example .env    # TG_API_ID, TG_API_HASH, GATEWAY_TOKEN
docker compose up -d
```

### Agent skills

The repo is designed to be driven by a coding-agent CLI. Point your agent (ZCode / Claude Code) at the checkout, share the `README.ru.md` data-layout section as context, and it can create entities, send invoices, triage the inbox and answer "how much does Acme owe me?" by reading files — every action reviewable as a git diff.

## Data layout

| Folder | Content |
|---|---|
| `10_Clients/` | Client cards + `Contacts/` |
| `15_Leads/` | Auto-filed unknown senders, prospects |
| `20_Inbox/`, `20_Outbox/` | Incoming / outgoing messages |
| `25_Chats/` | Materialized chat threads |
| `30_Deals/`, `30_Invoices/`, `30_Tasks/` | Pipeline, billing, tasks |
| `45_Tickets/`, `55_Goals/` | Incidents, goals |
| `90_Templates/` | Document templates (`{{seller_*}}` placeholders) |

All folders are git-ignored — your data is yours.

## Configuration

Everything is env-driven (`.env`); see [.env.example](.env.example) for the full list. Highlights:

| Variable | Purpose |
|---|---|
| `CRM_OWNER_NAME` … `CRM_OWNER_LEGAL` | Your name / contacts / legal details used in contracts, invoices, signatures |
| `SMTP_HOST` `SMTP_USER` `SMTP_PASS` | Outbound email |
| `EMAIL_IMAP_HOST` `EMAIL_USER` `EMAIL_PASS` | Inbound email (IMAP) |
| `TG_GATEWAY_URL` `TG_GATEWAY_TOKEN` | Telegram gateway connection |
| `MAX_BOT_TOKEN` | MAX messenger bot |
| `HUB_URL` `HUB_TOKEN` | Optional mobile-hub push notifications |
| `MONITOR_VPS_HOST`, `TG_GATEWAY_VPS_HOST` | Optional SSH-based external monitoring |

## Updating

```bash
./update.sh    # git pull + dependencies + migrations; never touches data folders
```

## Security

- The API binds to localhost by default — do not expose it to the internet without TLS + auth in front.
- All engine network calls pass through [`scripts/sec_guard.py`](scripts/sec_guard.py): scheme allow-list, DNS resolution with private/loopback/link-local/metadata IP blocking, redirect re-validation, filesystem path containment.
- Secrets live in `.env` (git-ignored). No credentials in code.
- Found something? See [SECURITY.md](SECURITY.md).

## Roadmap

- [ ] Dashboard i18n (EN / RU)
- [ ] Personal-data encryption module for client cards (field-level, sleep-lock)
- [ ] Plugin system for custom KPI panels
- [ ] One-command Docker Compose bundle
- [ ] Installation wizard (`automata doctor`)

## License

[MIT](LICENSE) © Evgen Uryadov · [automata.sale](https://automata.sale)

Built as the production CRM of a solo 1C-Bitrix integrator. If it runs a one-man business, it can run yours.
