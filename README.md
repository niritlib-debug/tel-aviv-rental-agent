# tel-aviv-rental-agent

An AI agent that searches **twice a day** for **entire 3-room apartments for rent in Tel Aviv‑Yafo** at **up to ₪5,200/month**, remembers what it has seen in SQLite, tracks changes (for example, price drops), and reports new listings **with direct links**.

The full design is in [SPEC.md](SPEC.md).

## How it works

| Agent component | Where it lives | What it does |
|---|---|---|
| **Goal** | `rental_agent/goal.py` | Criteria (Tel Aviv only, exactly 3 rooms, ≤ ₪5,200, entire apartment). The code checks every listing against them, and the LLM can't loosen them. |
| **Tools** | `rental_agent/tools/` | `search_komo` (Komo listings, verified), `web_search` (Tavily, optional, unverified snippets), `memory_summary`, `submit_matches`, notifiers (console, Markdown, Telegram). |
| **Memory** | `rental_agent/memory.py` | SQLite: `listings` (dedup by ID and normalized URL), `listing_changes` (field-level history), `runs` (audit log). |
| **LLM** | `rental_agent/llm.py` | Claude (`claude-opus-5-5` by default) runs a tool-use loop. It picks which tools to call, reviews candidates and submits IDs with notes. It can only submit IDs that a tool returned during the run. |
| **Loop** | `rental_agent/agent.py`, `scheduler.py` | Inner loop: plan, call tools, observe, submit (at most 8 steps). Outer loop: APScheduler cron at 08:00 and 20:00 **Asia/Jerusalem**. |

Without `ANTHROPIC_API_KEY` the agent runs in **deterministic mode**, which uses the same tools, memory and goal check with a fixed plan. If the LLM fails during a run (API error, refusal, step limit), that run switches to deterministic mode automatically.

### Data sources (verified 2026‑10‑16)

| Source | Status |
|---|---|
| **Komo** (komo.co.il) | ✅ Primary source. The listing page is server-rendered, robots.txt allows it, and the filters work. Only page 1 (about 20 newest listings) is public; later pages need a login, which the agent does not attempt. |
| **Yad2** | ❌ Blocked by Radware bot protection. The agent does not bypass it. Yad2 links can still appear through `web_search`. |
| **Madlan, Homeless** | ❌ HTTP 403 to automated clients. They can appear through `web_search`. |
| **Tavily Search API** | Optional (`TAVILY_API_KEY`). Results come from search snippets and are marked **[unverified]**, so check the price on the site. |

The agent never makes up listings. Every reported link comes from a page or API response fetched during that run.

## Setup

Requires Python 3.11 or newer.

```bash
git clone https://github.com/niritlib-debug/tel-aviv-rental-agent.git
```

```bash
cd tel-aviv-rental-agent
```

```bash
python3 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -e ".[dev]"
```

```bash
cp config.example.toml config.toml && cp .env.example .env
```

Then edit `.env` (all keys are optional):

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Turns on LLM mode (Claude decides which tools to call and adds notes) |
| `TAVILY_API_KEY` | Adds the web-search source (Yad2, Madlan, Homeless, Facebook through search results) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Sends a Telegram message when there are new or changed listings |

## Usage

Run one search now:

```bash
python -m rental_agent run-once
```

Run a search without the LLM and without saving to memory, to try it out:

```bash
python -m rental_agent run-once --no-llm --dry-run
```

Run on schedule (08:00 and 20:00 Israel time; blocks the terminal):

```bash
python -m rental_agent schedule --run-now
```

Show the next scheduled times, the saved listings, and the run history:

```bash
python -m rental_agent next-runs
```

```bash
python -m rental_agent list
```

```bash
python -m rental_agent history
```

Each run prints a report and saves it to `reports/YYYY-MM-DD_HHMM_runN.md`, with these sections: **New**, **Changed** (with old → new values), **Reappeared** and **Still available**. Every entry has a link.

### Running it 24/7

- **Long-running process** (recommended): run `python -m rental_agent schedule` under `tmux`, `systemd`, `launchd` or Docker. APScheduler handles the time zone and daylight saving time.
- **System cron instead**: on Linux with cronie, `CRON_TZ` pins the time zone.

  ```
  CRON_TZ=Asia/Jerusalem
  0 8,20 * * * cd /path/to/tel-aviv-rental-agent && .venv/bin/python -m rental_agent run-once >> data/cron.log 2>&1
  ```

  macOS cron ignores `CRON_TZ`, so there use the built-in scheduler or launchd.

## Tests

```bash
pytest -q
```

The 78 tests run offline (no network, no API keys). They cover goal edge cases, the Komo parser (against a fixture that mirrors the real markup), robots.txt handling, bot-wall and login-redirect detection, retries, Tavily snippet extraction, SQLite deduplication, change and stale tracking, the LLM loop with a fake client (including rejecting made-up IDs and falling back after an error), and scheduling around Israel's daylight saving change. GitHub Actions runs them on Python 3.11 to 3.13.

## Project layout

```
rental_agent/
  goal.py        Goal component
  llm.py         LLM component (Claude tool-use loop)
  memory.py      Memory component (SQLite)
  agent.py       Agent run + ToolBox (inner loop)
  scheduler.py   Outer loop (Asia/Jerusalem cron)
  config.py      TOML + env configuration
  models.py      Listing model, URL normalization, content hash
  cli.py         Command line
  tools/         http (polite client), komo, web_search, notify
tests/           pytest suite + HTML fixture
SPEC.md          Requirements and design
```

## Limitations

- Komo shows only its first results page to anonymous users, so the first run may miss older listings. Running twice a day with memory picks up new ones.
- Yad2 and Madlan have no public API, and their bot protection is respected, so they appear only through optional web search, without verified prices.
- The agent does not contact landlords.

## License

MIT
