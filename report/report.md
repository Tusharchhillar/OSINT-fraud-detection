# Internship Report — Smart OSINT & Fraud Intelligence

> **Programme:** GPCSSI 2026 — Final Project
> **Author:** Tushar Chhillar
> **Mentor / Org:** *(to fill in)*
> **Repository:** <https://github.com/Tusharchhillar/OSINT-fraud-detection>
> **Document status:** Draft v0.2 — updated as the project progresses.

---

## Abstract

*(1 paragraph summary of the problem, approach, and outcome — to be finalized at the end.)*

The **Smart OSINT & Fraud Intelligence** project builds an end-to-end pipeline that detects
illicit and fraudulent online communities by scraping public content from Telegram,
Instagram, X, and WhatsApp, normalising it into structured events, scoring it with a local
large language model (Ollama) plus heuristic signals, and surfacing high-risk activity on a
Streamlit dashboard. The system is designed for analyst triage: it surfaces risk, not
verdicts, and keeps scraped data on-device to limit exposure.

---

## 1. Introduction & Problem Statement

Online fraud — investment scams, pig-butchering rings, fake-job luring, illegal goods
marketplaces, and coordinated harassment — increasingly recruits victims through public
social media. Investigators and trust-and-safety teams struggle to keep up with the
**volume, fragmentation, and cross-platform nature** of these campaigns: a single scam
operation will often run a Telegram channel for "customer support," an Instagram page for
social proof, an X account for reach, and a WhatsApp invite link for closed-group
recruitment.

**Problem:** there is no single, analyst-friendly tool that lets a non-engineer
**discover, monitor, and triage** these multi-platform fraud funnels from public data
alone.

**Goal of this project:** design and prototype such a tool, with a focus on:
- *Coverage* — multiple platforms in one pipeline.
- *Structure* — every event in a single, queryable schema.
- *Local-first analysis* — no scraped content leaves the analyst's machine.
- *Actionable output* — a dashboard that highlights the riskiest items first.

---

## 2. Objectives

1. Build scrapers for **Telegram, Instagram, X, and WhatsApp** that target public
   channels/profiles/hashtags and emit a unified event schema.
2. Implement a **processing layer** (Pandas) that cleans, deduplicates, and persists
   events to both NDJSON (audit) and SQLite (query).
3. Integrate a **local LLM via Ollama** to classify intent and assign a risk score,
   combined with deterministic heuristics for a final composite score.
4. Deliver a **Streamlit dashboard** with trend charts, an event explorer, and a real-time
   alerts panel.
5. Adopt **structured JSON logging** throughout so every stage is observable and
   reproducible.

---

## 3. Tools, Libraries & Rationale

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Dominant in data/ML; richest ecosystem for scraping and dashboards |
| Packaging | Poetry | Reproducible envs, lockfile, simple CLI entry points |
| Telegram | Telethon | Mature, async, official-grade MTProto client |
| Web scraping | Playwright | Handles modern JS-heavy sites (IG, X); fallback to Scrapy for HTML-only |
| Data wrangling | Pandas | De-facto standard for tabular cleaning/filtering |
| Storage | SQLite + NDJSON | Zero-ops for the MVP; NDJSON is a durable append-only audit log |
| AI / intent | Ollama (llama3.1, mistral) | Local inference — no scraped content sent to a third party |
| Dashboard | Streamlit | Fastest path to a usable analyst UI in Python |
| Logging | structlog | First-class JSON output, plays well with log aggregators |

---

## 4. Methodology

The pipeline is divided into four stages, each with its own contract and tests:

### 4.1 Data Acquisition
Target **public** content only. Each scraper exposes a `run(target)` method that yields
`RawEvent` records with a common shape:
`{event_id, platform, source, author, timestamp, text, urls, media, raw}`.

### 4.2 Data Processing
Pandas-based cleaning: dedupe on `(platform, source, event_id)`, strip noise, normalize
URLs (strip trackers, lowercase host, expand shorteners heuristically), language-tag,
and persist.

### 4.3 Intent Analysis
The Ollama model is prompted in **JSON mode** to return
`{intent, risk_score, category, reasoning, indicators[]}`. The composite score blends
the LLM score with deterministic signals (known-scam domains, repeated invite links,
crypto-only payment language).

### 4.4 Visualization
Streamlit app reads from SQLite, renders trend charts (events/day by platform and
intent), an event explorer with filters, and an alerts panel for `risk_score >= 70`.

---

## 5. System Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Scraper    │──▶ │  Processor   │──▶ │   Analyzer   │
│ (Telethon /  │    │  (Pandas /   │    │  (Ollama +   │
│ Playwright)  │    │  SQLite)     │    │ heuristics)  │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │ NDJSON            │ SQLite            │ enriched
       ▼                   ▼                   ▼
   data/raw/         data/osint.db       ┌──────────────┐
                                         │  Dashboard   │
                                         │ (Streamlit)  │
                                         └──────────────┘
```

A **structlog** JSON-logging layer is mounted at the entrypoint of every stage so that
events are traceable end-to-end via `trace_id`.

---

## 6. Weekly Progress Log

> Living log — updated as work is done. Each entry ends with a commit hash once GitHub
> is wired up.

### Week 1 — Planning & Bootstrap
- Wrote `implementation.md` with the full M1–M7 plan.
- Created this report skeleton and a project `README.md`.
- Bootstrapped `.gitignore` (Python, `.env`, `data/`, Playwright caches, IDE files).
- Initialized local git repo *(pending remote setup — see TODO below).*

### Week 2 — M1 Foundations *(delivered in this commit range)*
- **`pyproject.toml`** — Poetry-managed project, optional dep groups for `telegram`,
  `browser`, `scrapy`, `dashboard`, `llm`, and `all`, plus `osint-process` /
  `osint-scrape` / `osint-dashboard` console scripts. Dev group includes `pytest`,
  `pytest-cov`, and `ruff`. Tooling configured: line-length 100, target Python 3.11.
- **`.env.example`** — every config key documented (`OSINT_*`, `TELEGRAM_*`,
  `SCRAPER_*`); secrets are gitignored.
- **`src/osint/config.py`** — `Settings` dataclass loaded once via `lru_cache`;
  monkeypatchable in tests.
- **`src/osint/logging_setup.py`** — `structlog` configured to emit one JSON
  object per line to **stdout** and to mirror to the raw NDJSON audit file.
  Idempotent — safe to call from any entrypoint.
- **`src/osint/schemas.py`** — `RawEvent` and `EnrichedEvent` Pydantic v2 models
  with a stable `event_id = <platform>-<sha1[:12]>`, automatic URL extraction
  from text, and a strict `risk_score` 0–100 range on enriched events.
- **`src/osint/processing/store.py`** — dual-write store: append-only NDJSON
  audit log + idempotent SQLite (`INSERT OR IGNORE` on `event_id`).
- **`src/osint/processing/clean.py`** — Pandas-based dedupe, empty-row and
  emoji-only filtering, URL normalization (tracker stripping, host lowercasing).
- **`src/osint/cli/process.py`**, **`scrape.py`**, **`dashboard.py`** — CLI
  entry points. `osint-process --seed` inserts a representative demo set
  across all four platforms and prints a one-line JSON log per stage.
- **`tests/`** — 14 unit tests (schemas, store, cleaner), **all green**.

**Smoke verification (M1):**
- `pytest -v` → 14/14 passed in ~1s.
- `python -m osint.cli.process --seed` → 4 events written; `data/raw/events.ndjson`
  contains 4 JSON lines with URLs auto-extracted; `data/osint.db` has 4 rows.
- `osint-scrape` and `osint-dashboard` return a clear "not implemented" warning
  pointing at M2/M3/M6 — no silent stub failures.

**What I learned / decisions to remember:**
- `structlog.PrintLoggerFactory` is the cleanest way to keep one JSON object per
  line on stdout without losing the stdlib `logging.FileHandler` mirror.
- The audit log keeps every observation (duplicates included); the SQLite view
  is the deduplicated, queryable one. This split is useful when we add the
  analyzer in M5 — we can re-score every observation cheaply.
- Pydantic v2 + pandas: `model_dump()` → `DataFrame` → `model_validate()` needs
  an explicit `timestamp.to_pydatetime()` coercion. Worth remembering for M4.
- For the M1 emoji filter, "has at least one alpha char" turned out to be a
  better policy than the original "short emoji-only" rule.

### Week 2b — M1 Tweaks *(post-review upgrade)*

Four reviewer-driven upgrades landed before the first push to GitHub, in one
focused session:

- **Schema (`src/osint/schemas.py`)** — added two new fields to `RawEvent`:
  - `language: str | None` — ISO-639-1 code; stays `None` for M1, populated by
    the cleaner in M4.
  - `content_hash: str | None` — sha256 of `lower(text) + sorted(URL stems)`.
    Stable across `utm_*` tracker variations and case-only differences, so M4
    can group paraphrased scam templates cheaply.
  - `make_content_hash()` exposed at module level for direct use in tests.
  - SQLite table gained two new columns + an index on `content_hash`.

- **Cleaner (`src/osint/processing/clean.py`)** — two new rules:
  - **Min-length rule**: drop rows where stripped text is shorter than 4 chars
    *and* there are no URLs/media to anchor on. Catches `ok`, `hi`, `👍`
    that the alpha-char rule alone would let through.
  - **Shortener flag**: a `_KNOWN_SHORTENERS` set (`bit.ly`, `t.co`,
    `tinyurl.com`, `goo.gl`, `ow.ly`, `is.gd`, `buff.ly`, `rebrand.ly`,
    `cutt.ly`, `shorturl.at`, `rb.gy`). When a URL's host matches, the cleaner
    appends a `*.<host>` marker to the event's URL list. Markers start with
    `*.` so they cannot be confused with real links by downstream consumers;
    M5 heuristics will treat them as risk indicators.
  - Cleaner now logs per-step drop counts in a single `osint.cleaner.run` event.

- **Logging (`src/osint/logging_setup.py`)** — two new processors:
  - `_add_static` — stamps every line with `service: osint`. Multi-service
    log aggregators can now filter by service without parsing event names.
  - `_prefix_event_name` — auto-prefixes the `event` field with `osint.`
    unless the caller already used the full form. This means call sites can
    stay short (`log.info("store.upsert", ...)`) and the wire format is
    consistent (`osint.store.upsert`). Every log line is now self-describing.
  - All existing call sites in `clean.py`, `store.py`, and the `cli/`
    scripts updated to the new namespace.

- **Store (`src/osint/processing/store.py`)** — disk-friendly upgrades:
  - **NDJSON rotation**: `OSINT_NDJSON_ROTATE_BYTES` (default 50 MB) controls
    the threshold. When the active `events.ndjson` exceeds it, the file is
    gzipped to `events-<UTC-timestamp>.ndjson.gz` and a fresh empty file is
    started. The active file keeps streaming without blocking.
  - **`Store.export_parquet(path=None)`**: dumps the entire events table to
    a Parquet file (default: `data/osint.parquet`). The M6 dashboard will
    read this for fast columnar loads. Skips cleanly if `pyarrow` is not
    installed.

**Verification after tweaks:**
- `pytest -v` → **30/30 passed** in ~1.4s (was 14; added 16 new tests).
- Live smoke: `osint-process --seed` emits 4 events, every log line carries
  `"service": "osint"` and `osint.*` event names, SQLite has the new
  `language` and `content_hash` columns populated, and `osint.parquet` is
  written.
- `Store.export_parquet()` is round-tripped through `pd.read_parquet` in tests.

**Decisions to remember:**
- `content_hash` lowercases text and strips query strings from URLs before
  hashing. This is deliberate — paraphrase-grouping in M4 depends on it.
- Shortener *flagging* (free) vs shortener *expansion* (network calls) is a
  policy choice. We default to flagging; expansion is opt-in for M5.
- The `osint.*` event prefix is enforced by the processor, not by discipline.
  If a future contributor writes `log.info("foo")`, the wire format is
  `osint.foo` — no silent drift.
- NDJSON rotation gzips the *previous* file, not the in-flight writes.
  `iter_ndjson()` only reads the active file; reading rotated history is
  opt-in (a future method).

### Week 3 — *(planned: M2 Telegram scraper)*

### Week 4 — *(planned: M3 Instagram / X / WhatsApp scrapers)*

### Week 5 — *(planned: M4 processing pipeline + heuristics)*

### Week 6 — *(planned: M5 Ollama intent analysis)*

### Week 7 — *(planned: M6 Streamlit dashboard)*

### Week 8 — *(planned: M7 hardening + final report pass)*

---

## 7. Results *(placeholder — fill as the project matures)*

- Number of sources monitored per platform.
- Distribution of intent classes and risk-score histogram.
- Examples of surfaced scams (with anonymized screenshots / redacted text).
- Dashboard screenshots and short walkthrough.

---

## 8. Risks & Ethical Considerations

- **Platform ToS** — scrapers target only public data, with conservative rate limits and
  no login-only content. Configurable user-agent.
- **Privacy** — no scraped content is sent to third-party LLM APIs. All inference is
  local via Ollama.
- **False positives** — risk thresholds and source whitelists are exposed in the
  dashboard for analyst override.
- **Data minimization** — only fields needed for analysis are persisted; `raw` payloads
  can be optionally dropped after enrichment.

---

## 9. Conclusion *(to be written at the end)*

*(2–3 paragraphs summarising what was built, what worked, what didn't, and what the next
steps would be if the project continued beyond the internship.)*

---

## 10. References

- Telegram MTProto API — <https://my.telegram.org>
- Telethon — <https://docs.telethon.dev>
- Playwright — <https://playwright.dev/python>
- Pandas — <https://pandas.pydata.org>
- Ollama — <https://ollama.com>
- Streamlit — <https://streamlit.io>
- structlog — <https://www.structlog.org>
- *Additional academic / industry references to be added as encountered.*

---

## Appendix A — Repository Layout

```
smart-osint-fraud-intel/
├── implementation.md
├── README.md
├── .gitignore
├── report/
│   └── report.md          ← this document
├── src/osint/             ← package code (M1+)
├── data/                  ← generated at runtime, gitignored
└── tests/                 ← pytest suite (M1+)
```
