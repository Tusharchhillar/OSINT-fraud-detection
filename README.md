# Smart OSINT & Fraud Intelligence

An OSINT detection tool that surfaces illicit, hidden communities and scams by monitoring
public posts on **Telegram, Instagram, X, and WhatsApp**. It combines multi-platform
scraping, structured data processing, on-device intent analysis (Ollama), and an
interactive **Streamlit** dashboard.

> 📄 The full internship report lives in [`report/report.md`](report/report.md) and grows
> in lockstep with the code. The technical plan is in [`implementation.md`](implementation.md).

---

## Architecture

```
Scrapers (Telegram / Instagram / X / WhatsApp)
        │
        ▼  RawEvent (NDJSON + structlog)
Processing (Pandas clean / normalize / URL extract)
        │
        ▼  CleanEvent (SQLite)
Intent Analysis (Ollama llama3.1 + heuristic scorer)
        │
        ▼  EnrichedEvent (risk_score, intent, indicators)
Dashboard (Streamlit: trends, events, alerts, source detail)
```

## Tech stack

- **Language:** Python 3.11+
- **Packaging:** Poetry
- **Scraping:** Playwright (primary), Scrapy (fallback), Telethon (Telegram)
- **Data:** Pandas, SQLite, NDJSON
- **AI:** Ollama (`llama3.1` / `mistral`, local)
- **Dashboard:** Streamlit
- **Logging:** `structlog` (structured JSON)

## Quick start

```bash
poetry install
cp .env.example .env       # fill in TELEGRAM_API_ID / TELEGRAM_API_HASH
poetry run playwright install chromium
ollama pull llama3.1
poetry run osint-dashboard # → http://localhost:8501
```

See [`implementation.md`](implementation.md) for the full setup, milestone plan, and risks.

## Status

- [x] M0 — Project plan, report skeleton, repo bootstrap
- [ ] M1 — Foundations (Poetry, env, JSON logging, schemas, SQLite)
- [ ] M2 — Telegram scraper
- [ ] M3 — Instagram / X / WhatsApp scrapers
- [ ] M4 — Processing pipeline
- [ ] M5 — Intent analysis (Ollama)
- [ ] M6 — Streamlit dashboard
- [ ] M7 — Hardening & docs
