# Lead Qualification Agent

A command-line tool that takes a spreadsheet of company domains plus a plain-text
description of what you sell, then for each company:

1. **Researches the company** — reads its website (homepage + key pages) and
   summarises what it does, its industry, products/services, and size/stage.
2. **Researches hiring signals** — finds the careers page, detects the ATS
   (Greenhouse, Lever, Ashby, Workable, Recruitee), pulls current openings,
   normalises and groups them by function, and tracks ~6-month momentum.
3. **Qualifies** — uses Claude to score fit **1–10** against your offer, decide
   qualify/disqualify against a threshold, and write a rationale that explicitly
   cites the hiring signals.
4. **Assembles** — for qualified leads, writes a research brief with 2–3 outreach
   hooks plus a personalised **AIDA cold email** and an open-optimised subject.

You get **two separate spreadsheets** (qualified vs. unqualified), one markdown
brief per qualified company, a snapshots datastore, and a run summary.

---

## Quick start

```bash
cd lead-qualifier
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only needed for JS-heavy sites

cp .env.example .env                 # then edit .env and add your key
cp offer_template.md offer.md        # then describe what you sell (free text)
```

Edit `offer.md` — just explain, in plain words, what you offer. You don't need
to define your ICP or scoring rules; the tool infers them from your description.
See `offer_example.md` for a filled-in example.

Prepare your leads file (CSV or XLSX). The only required column is a company
domain; a name column is optional. Column names are auto-detected (see below).
`leads_template.csv` shows the format.

### Validate first (no API credits spent)

```bash
python -m lead_qualifier.main --validate -i leads_template.csv -o offer.md
```

This checks your leads file, offer file, and API key without calling any API.

### Run

```bash
python -m lead_qualifier.main -i tests/sample_leads.csv -o offer.md --limit 3
```

---

## CLI reference

```
python -m lead_qualifier.main [OPTIONS]

  -i, --input PATH            Leads file (CSV or XLSX).            [required]
  -o, --offer PATH            Free-text file describing what you sell. [required]
      --output-dir PATH       Output directory.                   [default: output]
  -t, --threshold INT         Qualify score threshold, 1–10. Overrides .env.
      --draft-emails/--no-draft-emails
                              Draft AIDA cold emails for qualified leads. [default: on]
      --history-provider TEXT 'none' (free snapshots) or 'api' (paid).  [default: none]
      --limit INT             Process only the first N leads (for testing).
      --workers INT           Parallel workers. Overrides .env MAX_WORKERS.
      --no-cache              Disable cache + checkpoints (re-fetch everything).
      --env-file PATH         Path to .env (default: auto-discover).
      --validate              Dry-run: check inputs + keys, spend nothing.
  -v, --verbose               Verbose console logging.
```

---

## Inputs

### Leads file (CSV/XLSX)

Required: a column with the company domain. Optional: a company name column.
Matching is **case-insensitive** and accepts common aliases:

| Field  | Accepted column names (any of) |
|--------|--------------------------------|
| Domain | `domain`, `website`, `url`, `company url`, `company domain`, `site`, `web`, `homepage`, `link` |
| Name   | `company`, `company name`, `name`, `account`, `account name`, `organization`, `business` |

Domains/URLs/emails are normalised to a bare domain (`https://www.Acme.com/` →
`acme.com`). Invalid or duplicate rows are skipped with a clear message; the run
never crashes on a bad row.

### Offer file

A plain markdown/text file describing what you sell. Free-form — see
`offer_template.md` (blank with prompts) and `offer_example.md` (filled in).

---

## Outputs (in `output/`)

| File | Contents |
|------|----------|
| `qualified_leads.csv`   | Qualified companies: domain, openings, functions hiring, score, rationale, email subject, brief path. |
| `unqualified_leads.csv` | Disqualified/errored companies with the reason. |
| `all_results.csv`       | Every company in one file (same schema). |
| `briefs/<domain>.md`    | One research brief per qualified company. |
| `snapshots.db`          | SQLite job-history datastore (accrues across runs). |
| `cache.db`              | HTTP + LLM response cache and per-company checkpoints. |
| `run_summary.json/.md`  | Counts (qualified/disqualified/errors) + companies with no careers page. |
| `run.log`               | Full run log. |

The spreadsheet schema is **stable** — same columns every run.

---

## AI provider — a free key works fine

The qualifier needs **one** AI key. Choose the provider with `LLM_PROVIDER`:

| Provider | `LLM_PROVIDER` | Key env var | Cost | Get a key |
|----------|----------------|-------------|------|-----------|
| Google Gemini | `gemini` | `GEMINI_API_KEY` | **Free** tier | aistudio.google.com |
| Groq | `groq` | `GROQ_API_KEY` | **Free** tier | console.groq.com |
| OpenAI | `openai` | `OPENAI_API_KEY` | Paid | platform.openai.com |
| Anthropic (Claude) | `anthropic` *(default)* | `ANTHROPIC_API_KEY` | Paid | console.anthropic.com |

Only the key for your chosen provider is needed (a generic `LLM_API_KEY` also
works). Everything except Anthropic talks to each provider's **OpenAI-compatible
endpoint**, so other OpenAI-compatible gateways work too via `LLM_BASE_URL`.

The free models (Gemini Flash, Llama 3.3 70B) are very usable here; Claude/GPT-class
models write somewhat sharper emails. Free tiers rate-limit — calls retry with
backoff automatically, but if you still hit limits, lower `MAX_WORKERS` (e.g. `2`).

## Environment variables (`.env`)

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `LLM_PROVIDER` | No | `gemini` \| `groq` \| `openai` \| `anthropic` (default). |
| `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | **One** | Key for the provider you picked — scoring + brief/email generation. |
| `LLM_API_KEY`       | No | Generic fallback key if the provider-specific one isn't set. |
| `LLM_MODEL`         | No | Override the model (blank = best default per provider). |
| `LLM_BASE_URL`      | No | Advanced: custom OpenAI-compatible endpoint. |
| `SCORE_THRESHOLD`   | No | Qualify threshold on the 1–10 scale (default 6). |
| `REQUEST_DELAY`     | No | Polite delay between requests to a host (default 1.0s). |
| `MAX_WORKERS`       | No | Parallel company workers (default 4; lower on free tiers). |
| `THEIRSTACK_API_KEY`| No | Only for `--history-provider api` (paid 6-month history). |
| `SCRAPER_API_KEY`   | No | Only if you wire in a hosted scraper; plain Playwright needs no key. |

Missing the required key fails at startup with a clear message naming the
variable. **Current openings require no paid key** — only the optional
retroactive 6-month history does.

---

## How "last 6 months" works

Careers pages and ATS feeds only show *currently open* roles, so there's no
built-in history. Two interchangeable providers sit behind one interface:

- **Snapshot-and-track (free, default).** Each run stores the company's current
  openings to `snapshots.db` keyed by company + date. History accrues from your
  first run onward (no retroactive backfill). The brief shows the trend once you
  have 2+ runs.
- **Historical jobs API (paid, optional).** With `--history-provider api` and a
  `THEIRSTACK_API_KEY`, real ~6-month posting history is available immediately.
  The source is swappable without touching the pipeline.

---

## Architecture

```
lead_qualifier/
  main.py             CLI + orchestrator (parallel, checkpointed)
  config.py           .env loading + validation; prompt loader
  models.py           dataclasses shared across the pipeline
  ingest.py           CSV/XLSX load, forgiving column mapping, validation
  company_research.py Step 1: fetch pages + summarise (Claude)
  hiring_signals.py   Step 2: careers discovery, ATS detect, normalise, history
  qualify.py          Step 3: 1–10 fit score + rationale (Claude)
  assemble.py         Step 4: brief + AIDA email (Claude)
  output.py           two CSVs + briefs + run summary
  ats/                modular ATS providers (+ HTML scraper fallback)
  job_history/        snapshot (free) + theirstack (paid) behind one interface
  utils/              fetcher (requests→Playwright), cache, logger
prompts/              editable prompt templates (company_summary, qualify, brief)
```

### Extending ATS support

Add a module under `ats/`, subclass `ATSProvider` (implement `detect` and
`fetch_openings`), then register the class in `ats/__init__.py`'s
`PROVIDER_CLASSES`. No other code changes needed.

---

## Robustness

- Per-company `try/except` — one failure never kills the run.
- Retries with exponential backoff on network calls.
- Polite crawling: robots.txt respected, real User-Agent, per-host delays.
- Cache + checkpoints: re-runs skip already-fetched pages and already-processed
  companies (and won't re-spend API credits). Use `--no-cache` to force fresh.

---

## Tests

```bash
pip install pytest
pytest -q
```

Covers ingest column-mapping and domain normalisation (no API calls).
