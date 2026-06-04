# Smart OSINT & Fraud Intelligence — Implementation Plan

## 1. Project Overview

**Smart OSINT & Fraud Intelligence** is an OSINT (Open Source Intelligence) detection tool
designed to surface illicit, hidden communities and scams by continuously monitoring multiple
social media platforms. It combines multi-platform scraping, structured data processing,
on-device intent analysis, and an interactive dashboard to help analysts triage suspicious
activity in near real-time.

The system is built around four logical stages: **Data Acquisition → Data Processing →
Intent Analysis → Visualization**, with a shared **Structured JSON Logging** layer used by
every stage for traceability and downstream consumption.

---

## 2. Core Components

### 2.1 Data Acquisition
Scrape public data from Telegram, Instagram, X, and WhatsApp, prioritizing promotional
messages, invite links, and broadcast-style posts that typically signal fraud activity.

- **Telegram** — Telethon client targeting public channels/groups, scraping recent messages,
  forwarded-origin metadata, and any embedded `t.me/` invite links.
- **Instagram** — Playwright-driven browser automation for public hashtag/keyword pages and
  profile bio scraping (no login required for public content).
- **X (Twitter)** — Playwright/Scrapy hybrid for public search results, profile timelines, and
  tweet content via `nitter.net` or advanced-search fallbacks.
- **WhatsApp** — `whatsapp-web.js` (Node bridge) or Playwright for public `chat.whatsapp.com`
  invite-link preview metadata, and any publicly indexed broadcast lists.
- All scrapers emit a common **RawEvent** schema to a unified queue.

### 2.2 Data Processing
Convert incoming raw data (text, HTML, partial JSON) into a structured JSON format and apply
cleaning/filtering before downstream analysis.

- **Normalizer** maps platform-specific payloads to a single `RawEvent` shape:
  `{event_id, platform, source, author, timestamp, text, urls, media, raw}`.
- **Cleaning layer** (Pandas) drops duplicates, strips noise (emoji-only messages, bot
  footers), normalizes URLs, detects crypto/wallet/payment keywords, and language-tags text.
- **Persistence** writes structured events to both **NDJSON files** (append-only audit log)
  and a **SQLite** store for fast querying by the dashboard.

### 2.3 Intent Analysis
Use a local AI model via Ollama to read messages, infer intent, and assign a numeric
risk score. Local inference avoids sending scraped content to third-party services.

- **Engine** wraps Ollama's HTTP API; default model `llama3.1` (fallback `mistral`).
- **Prompt** asks the model to classify intent into `benign | suspicious | scam | illicit`
  and return a JSON object with `intent`, `risk_score (0-100)`, `category`, `reasoning`,
  and `indicators[]`.
- **Scoring** combines the model's risk_score with deterministic heuristics
  (e.g. known-scam domains, repeated invite links, crypto-only payment requests) for a
  final composite score.
- **Caching** of model responses keyed by content-hash to avoid repeat inference cost.

### 2.4 Visualization
A responsive Streamlit dashboard surfaces trends, supports filtering, and displays
real-time alerts.

- **Trend view** — time-series chart of event volume per platform and intent class.
- **Event explorer** — filterable, searchable table of all processed events.
- **Alerts panel** — high-risk events (score ≥ 70) highlighted in real time.
- **Source detail** — drill-down by channel/handle with intent breakdown.

---

## 3. Technology Stack

| Layer              | Technology                                |
|--------------------|-------------------------------------------|
| Language           | Python 3.11+                              |
| Package Mgmt       | Poetry                                    |
| Scraping           | Playwright (primary), Scrapy (fallback)   |
| Telegram Client    | Telethon                                  |
| Data Manipulation  | Pandas                                    |
| AI / Intent        | Ollama (local `llama3.1` / `mistral`)     |
| Dashboard          | Streamlit                                 |
| Persistence        | SQLite + NDJSON                           |
| Logging            | `structlog` (structured JSON output)      |

---

## 4. Project Structure

```
smart-osint-fraud-intel/
├── pyproject.toml
├── poetry.lock
├── README.md
├── .env.example
├── implementation.md
├── src/
│   └── osint/
│       ├── __init__.py
│       ├── config.py              # env + paths
│       ├── logging_setup.py       # structlog → JSON
│       ├── schemas.py             # RawEvent, EnrichedEvent
│       ├── scrapers/
│       │   ├── base.py
│       │   ├── telegram.py        # Telethon
│       │   ├── instagram.py       # Playwright
│       │   ├── x.py               # Playwright/Scrapy
│       │   └── whatsapp.py        # Playwright / wa-web bridge
│       ├── processing/
│       │   ├── normalize.py
│       │   ├── clean.py           # Pandas
│       │   └── store.py           # SQLite + NDJSON
│       ├── analysis/
│       │   ├── ollama_client.py
│       │   ├── prompt.py
│       │   ├── heuristics.py
│       │   └── scorer.py
│       └── dashboard/
│           └── app.py             # Streamlit
├── data/
│   ├── raw/                       # NDJSON append-only logs
│   └── osint.db                   # SQLite
└── tests/
    ├── test_normalize.py
    ├── test_scorer.py
    └── test_logging.py
```

---

## 5. Setup & Execution

### 5.1 Prerequisites
1. **Install Python 3.11+** — verify with `python --version`.
2. **Install Poetry** — `pip install poetry` or use the official installer.
3. **Install Ollama** — download from <https://ollama.com/download> and pull a model:
   ```bash
   ollama pull llama3.1
   # optional fallback:
   ollama pull mistral
   ```
4. **Install Playwright browsers** (only for the scrapers that need it):
   ```bash
   playwright install chromium
   ```

### 5.2 Project Initialization
```bash
# from the project root
poetry install
cp .env.example .env   # then fill in credentials
```

### 5.3 Telegram API Credentials
1. Visit <https://my.telegram.org> and sign in.
2. Go to **API development tools** and create a new application.
3. Copy the `api_id` and `api_hash` into `.env`:
   ```env
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
   TELEGRAM_SESSION=osint_session
   ```
4. On first run, Telethon will prompt for your phone number and a login code —
   the session string is then persisted to disk.

### 5.4 Structured JSON Logging
Every module routes its logs through a single `structlog` configuration that emits
one JSON object per line to stdout **and** to `data/raw/events.log`. The schema:

```json
{
  "timestamp": "2026-06-04T12:34:56.789Z",
  "level": "info",
  "event": "message.scraped",
  "platform": "telegram",
  "event_id": "tg-9f3c1a",
  "source": "@example_channel",
  "trace_id": "scrape-2026-06-04T12:34:56Z"
}
```

This guarantees every stage (scraper → processor → analyzer → dashboard) produces
machine-parseable logs and that RawEvents are never silently dropped.

### 5.5 Running the Pipeline
```bash
# Start Ollama in a separate terminal
ollama serve

# Run a specific scraper
poetry run osint-scrape telegram --channel example_channel
poetry run osint-scrape instagram --hashtag scamalert

# Process + analyze everything in data/raw/
poetry run osint-process

# Launch the dashboard
poetry run osint-dashboard   # http://localhost:8501
```

---

## 6. Implementation Milestones

1. **M1 — Foundations**: project skeleton, Poetry config, `.env`, structured JSON logging,
   `RawEvent`/`EnrichedEvent` schemas, SQLite store, unit tests.
2. **M2 — Telegram scraper**: Telethon client, channel/group discovery, message capture,
   RawEvent emission, rate limiting.
3. **M3 — Other scrapers**: Instagram, X, and WhatsApp scrapers using Playwright;
   integration tests against public test channels.
4. **M4 — Processing pipeline**: Pandas cleaning, URL normalization, language tagging,
   heuristic pre-scoring, persistence to SQLite.
5. **M5 — Intent analysis**: Ollama client, prompt template, JSON-mode parsing, composite
   scorer, response cache.
6. **M6 — Dashboard**: Streamlit app with trends, event explorer, alerts panel, and
   source detail.
7. **M7 — Hardening**: retry/backoff, proxy rotation knobs, observability, docs,
   end-to-end smoke test.

---

## 7. Risks & Mitigations

- **Platform ToS** — scrapers target only **public** data; configurable user-agent and
  conservative rate limits; no login-only content.
- **Model drift / latency** — composite score blends heuristics + LLM; response cache
  keeps cost flat as volume grows.
- **Data volume** — NDJSON append-only + SQLite keeps the MVP simple; swap in
  DuckDB/Postgres later without changing the schema.
- **False positives** — risk threshold is configurable in the dashboard; analysts can
  whitelist/blacklist sources.
