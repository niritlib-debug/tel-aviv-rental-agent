# SPEC — Tel Aviv Rental Agent

Status: v0.3 · Last updated 2026-10-16

| Version | Change | Implemented |
|---|---|---|
| v0.1 | Initial agent | ✅ |
| v0.2 | Parking required; only ads that state a price | ✅ |
| v0.3 | Single tenant only (no roommates); long‑term rentals only; listing‑page check (F2b–F2d) | ✅ |

## 1. Purpose

An autonomous agent that searches, twice a day, for **entire apartments for rent in Tel Aviv‑Yafo** that **a single tenant can rent on their own (not roommate arrangements)**, with **exactly 3 rooms**, **a parking space** and a **monthly rent of at most ₪5,200**, remembers what it has already seen, detects changes, and reports new and changed listings **with direct links**.

## 2. Requirements

### 2.1 Functional

| ID | Requirement |
|----|-------------|
| F1 | Search only in the city of Tel Aviv‑Yafo. Listings from any other city are rejected, even if a source returns them. |
| F2 | Accept only entire apartments (property types דירה, דירת גן, דופלקס, פנטהאוז, גג/פנטהאוז, טריפלקס, מרתף/פרטר, יחידת דיור — configurable). Reject sublets (סאבלט) and any other property type. Roommate ads are covered by F2b. |
| F2b | **Single tenant only.** Accept only ads where one person can rent the whole flat. Reject ads that look for a roommate or offer a room in a shared flat (`roommates_wanted`), and ads aimed only at roommates (`roommates_only`). An ad for a whole flat that says it *also* suits roommates (e.g. "מושלמת לשותפים או לזוגות") is still accepted, because a single tenant can rent it. Classification rules are in §4.6. Controlled by `goal.single_tenant_only` (default `true`). |
| F2c | **Long‑term monthly rentals only.** Reject short‑term or per‑night ads (e.g. "ללילה", "לטווח קצר", "per night"), because their price is not a monthly rent. |
| F2d | F2b and F2c are decided from the **full listing page**, not the result card: Komo cards show only type, rooms, size and floor. Each candidate that passes the card‑level checks has its listing page fetched and parsed (§4.2 `fetch_komo_details`). |
| F3 | Accept only listings with exactly 3 rooms (3.0). 2.5 and 3.5 are rejected. |
| F4 | Accept only ads that state a monthly price, and only if it is ≤ ₪5,200. Ads without a price are always rejected (Komo is also queried with `priceOnly=1`). |
| F4a | Accept only apartments with a parking space (`goal.require_parking`, default `true`). Komo is queried with its `yesParking=1` filter (verified 2026‑10‑16: 40 → 7 results; the listing page shows "חניות 1"). Web‑search candidates need a positive parking mention (חניה/חנייה/parking) and are rejected on "ללא/אין/בלי חניה". Unknown parking is rejected. |
| F5 | Run automatically twice a day at 08:00 and 20:00 in the `Asia/Jerusalem` time zone (configurable). Also runnable on demand. |
| F6 | Every reported listing includes a link to the original listing page. |
| F7 | Persist all seen listings in SQLite; never report the same listing as "new" twice. |
| F8 | Detect and record changes to a known listing (price, address/title, description) and report them as "changed". |
| F9 | Track listing lifecycle: `first_seen`, `last_seen`, and `stale` when not seen for N days (default 7). |
| F10 | Produce a report per run (console + Markdown file); optional Telegram notification. |
| F11 | Never invent listings, prices, or URLs. Every reported listing must come verbatim from a tool result fetched during that run. |
| F12 | Reports mark single‑tenant‑friendly ads ("suits a single tenant") and ads whose listing page could not be checked ("⚠ not checked for roommates"). |

### 2.2 Non‑functional

| ID | Requirement |
|----|-------------|
| N1 | Python ≥ 3.11 (uses `tomllib`). |
| N2 | Respect each site's `robots.txt`; identify with an honest User‑Agent; no CAPTCHA solving, no bot‑protection bypass, no login. |
| N3 | Network failures, parsing failures, LLM failures and notifier failures must not crash the scheduler; each run is recorded with status and error. |
| N4 | Works without an LLM key (deterministic mode) and without a web‑search key (Komo only). |
| N5 | All thresholds and schedule are configuration, not code. Secrets come only from environment variables. |
| N6 | Unit tests run fully offline (no network, no API keys). |

## 3. Data‑source verification (done 2026‑10‑16)

Each candidate source was probed from this machine with plain HTTP before design. Results:

| Source | Result | Decision |
|--------|--------|----------|
| **Yad2** (`www.yad2.co.il`, `gw.yad2.co.il/feed-search-legacy/...`) | Radware/ShieldSquare bot challenge (HTTP 200 "Radware Page" / 302 to `validate.perfdrive.com`). | **Not used directly.** Bypassing bot protection is out of scope (N2). Yad2 links may still appear via the web‑search tool. |
| **Madlan** (`www.madlan.co.il`) | HTTP 403. | Not used directly. |
| **Homeless** (`www.homeless.co.il`) | HTTP 403. | Not used directly. |
| **Komo** (`www.komo.co.il/code/nadlan/apartments-for-rent.asp`) | HTTP 200, server‑rendered HTML. Query params `cityName`, `fromRooms`, `toRooms`, `toPrice` verified to filter correctly (page header "נדל"ן להשכרה בתל אביב יפו, 3 - 3 חדרים", "עד ₪5,200"). `robots.txt` for `User-agent: *` disallows only `/api/` (except picture list). | **Primary source.** |
| Komo pagination (`currPage=2+`) | Redirects to `account.komo.co.il` (login required). | Only page 1 (≈20 newest listings) is fetched. Twice‑daily runs + memory compensate. No login. |
| **Tavily Search API** (`POST https://api.tavily.com/search`) | Documented at docs.tavily.com (Bearer auth, `query`, `max_results`, `include_domains`). | **Optional secondary source**, enabled when `TAVILY_API_KEY` is set. Results are snippets, so they are marked `verified=false`. |
| **Anthropic Messages API** | Official `anthropic` Python SDK. | LLM component (optional). |
| **Telegram Bot API** (`https://api.telegram.org/bot<token>/sendMessage`) | Public documented API. | Optional notifier. |

Komo listing card structure (verified):

```html
<div id="modaaRowDv4941056" class="modaaRowAd ... modaa__box" key="4941056">
  <a href="/code/nadlan/details/?modaaNum=4941056"><h2 class="title">תל אביב יפו, <neighborhood>[, <street>]</h2></a>
  <div class="price">4,000&nbsp;₪</div>
  <div class="description">&nbsp;דירה&nbsp;3.0 חדרים (60 מ"ר) <br> קומה:3 מתוך 3</div>
```

If the site changes its markup, the parser returns zero listings and the run is recorded with a `parse_warning`; it never guesses.

Komo listing page (`/code/nadlan/details/?modaaNum=<id>`, verified 2026‑10‑16; allowed by `robots.txt` for `User-agent: *`):

- **Free text** after the label "תיאור הנכס:". This is where tenant wording appears ("דרוש שותף", "מתאימה ליחיד או לזוג", "מחיר ללילה"). The exact element selector is pinned during implementation and covered by a fixture.
- **Amenity list** `<li class='<key> [add]'>`: every page lists every amenity label, and only those with class `add` apply. So the text "מותאם לשותפים" appears on *every* page and must never be matched as plain text. The relevant keys are `shutafim` (suits roommates), `longRent` (long‑term) and `pets`.
- The `shutafim` tick is **informational only**. Listing 4941056 ticks it, yet its text says "מתאימה ליחיד או לזוג".

Acceptance examples taken from the live parking‑filtered results on 2026‑10‑16 (become test fixtures, with personal details removed):

| Komo id | Ad text (excerpt) | Expected |
|---|---|---|
| 4930853 | "דרוש שותף לדירת‑גג…" | reject: `roommates_wanted` |
| 4938846 | "מחפשת שותפה ל…" | reject: `roommates_wanted` |
| 4931095 | "…לטווח קצר… מחיר ללילה" | reject: short‑term (F2c) |
| 4941056 | "…מתאימה ליחיד או לזוג" | accept: `single_ok` |
| 4913610 | "…מושלמת לשותפים או לזוגות צעירים" | accept: `unknown` (whole flat; also suits roommates) |

## 4. Architecture — the five agent components

```
                 ┌──────────── Loop (scheduler.py) ─────────────┐
                 │  APScheduler CronTrigger 08:00,20:00          │
                 │  tz=Asia/Jerusalem  →  agent.run_once()       │
                 └──────────────────────┬────────────────────────┘
                                        ▼
 ┌─ Goal (goal.py) ─┐     ┌──────── Agent run (agent.py) ────────┐
 │ city, rooms,     │────▶│ inner loop: LLM ⇄ tools, ≤ N steps   │
 │ price, parking,  │     │ fallback: deterministic plan          │
 │ tenant, types    │     └───┬──────────────┬──────────────┬─────┘
 └──────────────────┘         ▼              ▼              ▼
                      ┌─ LLM (llm.py) ┐ ┌─ Tools ───────┐ ┌─ Memory (memory.py) ─┐
                      │ Claude via    │ │ search_komo   │ │ SQLite: listings,    │
                      │ anthropic SDK │ │ web_search    │ │ listing_changes,     │
                      │ tool use      │ │ komo_details  │ │ runs                 │
                      │               │ │ memory_summary│ │                      │
                      └───────────────┘ │ submit_matches│ └──────────────────────┘
                                        │ notifiers     │
                                        └───────────────┘
```

### 4.1 Goal (`rental_agent/goal.py`)
A frozen dataclass `SearchGoal(city, rooms, max_price, allowed_property_types, excluded_keywords, require_parking, single_tenant_only, tenant_rules)` built from config. `goal.check(listing) -> (ok, reasons)` is the **single source of truth** for criteria and is applied in code to every candidate — the LLM can never relax it. `goal.describe()` renders the goal text given to the LLM.

### 4.2 Tools (`rental_agent/tools/`)
| Tool | Purpose | Output |
|------|---------|--------|
| `search_komo(goal)` | GET the filtered Komo page, parse cards with BeautifulSoup, normalise. Checks `robots.txt` first. | `list[Listing]` (`verified=True`) |
| `web_search(goal)` | Tavily search restricted to `yad2.co.il`, `madlan.co.il`, `homeless.co.il`, `komo.co.il`, `facebook.com`. Extracts price/rooms/city from title+snippet with regexes; candidates lacking any field are dropped. | `list[Listing]` (`verified=False`) |
| `fetch_komo_details(listing)` | GET the listing page of a Komo candidate that passed the card‑level checks. Returns the free text, the ticked amenity keys and the parking count. Sequential, with `details_delay_seconds` (default 1.5 s) between requests. Same robots/bot‑wall/redirect rules as `search_komo`. | `ListingDetails(full_text, amenities, parking_spaces)` |
| `memory_summary()` | Last runs, counts of active/stale listings. | dict |
| `submit_matches(ids, notes)` | LLM declares which candidate IDs are matches. IDs not present in this run's candidate buffer are rejected. | accepted/rejected IDs |
| Notifiers | `ConsoleNotifier`, `MarkdownReportNotifier`, `TelegramNotifier` (optional). | side effects |

Listing pages are fetched only when needed: for a new listing, when the card's `content_hash` changed, or when `details_checked_at` is older than 24 h. A run typically fetches at most about 20 pages.

Shared HTTP layer (`tools/http.py`): `requests.Session`, honest User‑Agent, timeout (20 s), retries with exponential backoff on 429/5xx/connection errors (3 attempts), `robots.txt` cache via `urllib.robotparser`.

### 4.3 Memory (`rental_agent/memory.py`) — SQLite

```sql
CREATE TABLE listings (
  id            TEXT PRIMARY KEY,      -- "<source>:<source_id>"  e.g. "komo:4941056"
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  url           TEXT NOT NULL,
  title         TEXT, city TEXT, neighborhood TEXT, street TEXT,
  price         INTEGER, rooms REAL, size_sqm INTEGER, floor TEXT,
  property_type TEXT, description TEXT,
  has_parking   INTEGER,               -- 1 / 0 / NULL (unknown); added in schema v2
  tenant_fit    TEXT,                  -- single_ok | unknown | roommates_wanted | roommates_only | short_term; v3
  full_description TEXT,               -- text from the listing page; v3
  site_suits_roommates INTEGER,        -- Komo `shutafim` tick, informational; v3
  details_checked_at TEXT,             -- last successful listing-page fetch; v3
  verified      INTEGER NOT NULL DEFAULT 1,
  content_hash  TEXT NOT NULL,         -- sha256 of tracked fields
  status        TEXT NOT NULL DEFAULT 'active',   -- active | stale
  first_seen    TEXT NOT NULL,         -- ISO-8601, Asia/Jerusalem
  last_seen     TEXT NOT NULL,
  last_run_id   INTEGER
);
CREATE UNIQUE INDEX ux_listings_url ON listings(url);
CREATE TABLE listing_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id TEXT NOT NULL REFERENCES listings(id),
  run_id INTEGER, field TEXT NOT NULL, old_value TEXT, new_value TEXT,
  changed_at TEXT NOT NULL
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL,              -- running | ok | partial | failed
  mode TEXT,                         -- llm | deterministic
  n_candidates INTEGER DEFAULT 0, n_matches INTEGER DEFAULT 0,
  n_new INTEGER DEFAULT 0, n_changed INTEGER DEFAULT 0,
  errors TEXT                        -- JSON list
);
```

- **Deduplication:** primary key `source:source_id`; secondary unique URL (normalised: lower‑case host, no fragment, tracking params removed). Within one run, duplicates are collapsed before upsert.
- **Change tracking:** tracked fields = `price, title, description, size_sqm, floor`. A different `content_hash` writes one `listing_changes` row per changed field and marks the listing "changed" for the report. A listing that went `stale` and reappears becomes `active` again (reported as "reappeared").
- **Staleness:** after a successful run, active listings with `last_seen` older than `stale_after_days` become `stale`.
- WAL mode, one connection per run, schema versioned with `PRAGMA user_version`. v1 → v2 adds `listings.has_parking`; v2 → v3 adds `tenant_fit`, `full_description`, `site_suits_roommates`, `details_checked_at`. All migrations use `ALTER TABLE`, and existing databases are upgraded in place. A change of `tenant_fit` is written to `listing_changes`. `full_description` is not part of `content_hash`, so the upgrade does not mark every listing as changed.

### 4.4 LLM (`rental_agent/llm.py`)
- Anthropic Python SDK, default model `claude-opus-5-5` (configurable), `effort: low` (routine orchestration), server‑side refusal fallback (`fallbacks: "default"`).
- Manual tool‑use loop: system prompt = goal + rules ("only submit IDs returned by tools"). Tools exposed: `search_komo`, `web_search` (only if key present), `memory_summary`, `submit_matches`. The candidate rows the LLM sees include `tenant_fit` and a short excerpt of the ad text, so its notes can explain the tenant decision. The LLM cannot override the code's `tenant_fit` decision.
- The LLM decides which sources to query, may re‑query, and selects/annotates matches (e.g. "price dropped ₪300", "verify on site: from search snippet").
- Guardrails: max 8 iterations; every submitted ID must exist in the run's candidate buffer and pass `goal.check`; on API error/refusal/iteration cap the agent switches to deterministic mode for that run and records the error.

### 4.5 Loop
- **Inner loop** (per run, `agent.py`): plan → act (tools) → observe → decide, until `submit_matches` or the step cap.
- **Outer loop** (`scheduler.py`): APScheduler `BlockingScheduler` with `CronTrigger(hour="8,20", minute=0, timezone=ZoneInfo("Asia/Jerusalem"))`, `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1`. Exceptions inside a run are caught and logged; the scheduler keeps running.

### 4.6 Tenant classification (`rental_agent/tenant.py`, new)
`classify_tenant(text, amenities) -> (tenant_fit, evidence)` runs on title + card description + listing‑page text (or title + snippet for web‑search candidates). Hebrew is normalised first (niqqud and geresh removed, ־ treated as a space). Rules are checked **in this order**, and the first match wins:

1. **`short_term`** (reject, F2c): "ללילה", "לטווח קצר", "per night", "short term", "airbnb".
2. **Negated roommate wording → `single_ok`**: "לא לשותפים", "ללא שותפים", "לא מתאים(ה) לשותפים", "no roommates". This check runs before rule 3, so a negated mention is never read as a roommate ad.
3. **`roommates_wanted`** (reject): "דרוש/ה שותף/ה", "מחפש/ת/ים שותף/ה", "שותף/ה לדירה", "חדר בדירת שותפים", "חדר להשכרה", "להשכרה חדר", "roommate wanted", "looking for a roommate", "room in a shared".
4. **`roommates_only`** (reject): "לשותפים בלבד", "רק לשותפים", "מיועדת לשותפים".
5. **`single_ok`** (accept, highlighted): "ליחיד/ה", "לרווק/ה", "לאדם אחד", "single tenant", "for a single".
6. Otherwise **`unknown`** (accept). This covers whole‑flat ads that say they also suit roommates or couples.

Each pattern list is configurable (§6). `evidence` stores the matched phrase, which is shown in DEBUG logs and passed to the LLM. The Komo `shutafim` tick never changes the result; it is only stored.

If the listing page cannot be fetched (network error, bot wall, redirect), the card text alone is classified. The listing then follows `unchecked_policy`: `warn` (default) reports it with "⚠ not checked for roommates", while `skip` holds it back until a later run checks it.

## 5. Workflow of one run

1. Open memory; insert `runs` row (`running`).
2. Build candidate buffer:
   - LLM mode: Claude calls tools; tool results are added to the buffer.
   - Deterministic mode: call `search_komo` and, if configured, `web_search`.
3. Filter and classify:
   - Apply the card‑level part of `goal.check` (city, rooms, price, parking, property type).
   - For Komo candidates that pass, fetch the listing page when needed (§4.2) and run `classify_tenant`. Web‑search candidates are classified from their snippet.
   - Apply the full `goal.check`, including F2b/F2c; drop non‑matches (reasons logged at DEBUG).
4. Matches = LLM‑submitted IDs ∩ goal‑valid candidates (LLM mode) or all goal‑valid candidates (deterministic). If the LLM submitted nothing usable, fall back to all goal‑valid candidates.
5. Upsert each match → `new` / `changed` / `reappeared` / `unchanged`.
6. Mark stale listings.
7. Notify: report with sections *New*, *Changed*, *Still available* (count + links), tagging "suits a single tenant" and "⚠ not checked for roommates" (F12). Notifier errors are recorded, not raised.
8. Close `runs` row with status `ok` (no errors), `partial` (some tool failed but ≥1 source succeeded) or `failed`.

## 6. Configuration

`config.toml` (copy from `config.example.toml`), overridable by env vars; secrets only in env / `.env`.

```toml
[goal]
city = "תל אביב יפו"
rooms = 3
max_price = 5200
allowed_property_types = ["דירה", "דירת גן", "דופלקס", "פנטהאוז", "גג/פנטהאוז", "טריפלקס", "מרתף/פרטר", "יחידת דיור"]
excluded_keywords = ["סאבלט"]          # roommate wording moved to [goal.tenant]
require_parking = true
single_tenant_only = true
unchecked_policy = "warn"              # warn | skip
details_delay_seconds = 1.5

[goal.tenant]                          # §4.6; defaults shown in code, override here
short_term = ["ללילה", "לטווח קצר", "per night", "short term", "airbnb"]
negated_roommates = ["לא לשותפים", "ללא שותפים", "לא מתאים לשותפים", "לא מתאימה לשותפים", "no roommates"]
roommates_wanted = ["דרוש שותף", "דרושה שותפה", "מחפש שותף", "מחפשת שותפה", "מחפשים שותף", "שותף לדירה", "שותפה לדירה", "חדר בדירת שותפים", "חדר להשכרה", "להשכרה חדר", "roommate wanted", "looking for a roommate", "room in a shared"]
roommates_only = ["לשותפים בלבד", "רק לשותפים", "מיועדת לשותפים"]
single_ok = ["ליחיד", "ליחידה", "לרווק", "לרווקה", "לאדם אחד", "single tenant", "for a single"]

[schedule]
timezone = "Asia/Jerusalem"
times = ["08:00", "20:00"]

[memory]
db_path = "data/rentals.db"
stale_after_days = 7

[llm]
enabled = true            # still requires ANTHROPIC_API_KEY
model = "claude-opus-5-5"
max_steps = 8

[sources]
komo = true
web_search = true         # still requires TAVILY_API_KEY

[report]
dir = "reports"
```

| Env var | Purpose |
|---------|---------|
| `ANTHROPIC_API_KEY` | Enables LLM mode. |
| `TAVILY_API_KEY` | Enables web search tool. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Enables Telegram notifications. |
| `RENTAL_AGENT_CONFIG` | Path to config file (default `config.toml`). |

## 7. CLI

```
python -m rental_agent run-once [--no-llm] [--dry-run]
python -m rental_agent schedule          # blocking; 08:00 & 20:00 Asia/Jerusalem
python -m rental_agent list [--all]      # listings in memory
python -m rental_agent history [--limit N]
python -m rental_agent next-runs         # show next scheduled times
```

## 8. Error handling

| Failure | Behaviour |
|---------|-----------|
| HTTP timeout / 5xx / 429 | 3 retries, exponential backoff; then tool raises `SourceError`; run continues with other sources → `partial`. |
| robots.txt disallows | `SourceError("blocked by robots.txt")`, no request made. |
| Bot challenge / login redirect detected | `SourceError`, no retry, no bypass. |
| Markup changed (0 cards parsed on a 200 page) | Warning recorded in `runs.errors`. |
| Listing page fails or has no "תיאור הנכס" text | Classified from card text only; follows `unchecked_policy`; warning recorded. |
| LLM API error / refusal / step cap | Switch to deterministic mode for this run; error recorded. |
| Invalid IDs from LLM | Ignored and recorded. |
| SQLite error | Run fails, transaction rolled back, scheduler continues. |
| Notifier error | Recorded; other notifiers still run. |

## 9. Testing

`pytest`, fully offline:
- `test_goal.py` — criteria boundaries (5,200 ok / 5,201 rejected, 3 vs 3.5 rooms, other city, missing price, parking required / optional, `single_tenant_only` on / off).
- `test_tenant.py` — every rule in §4.6, rule order (negation beats "שותפים", short‑term beats everything), the five acceptance examples from §3, and that amenity labels without `add` are ignored.
- `test_komo_details.py` — listing‑page parser on a fixture (free text, ticked amenities, parking count), refetch policy (new / changed / older than 24 h), `unchecked_policy` warn vs skip.
- `test_komo.py` — parser on an HTML fixture mirroring the verified markup; bot‑challenge and login‑redirect detection; robots handling.
- `test_web_search.py` — snippet extraction and Tavily request shape (mocked session).
- `test_memory.py` — new / unchanged / changed / reappeared / stale, dedup by URL, change rows, v2 → v3 migration, `tenant_fit` change recorded.
- `test_agent.py` — deterministic run end‑to‑end with fake tools; LLM run with a fake client (including an invented ID that must be rejected and an API error that must fall back).
- `test_scheduler_config.py` — trigger fires at 08:00 and 20:00 Asia/Jerusalem across a DST boundary.

CI: GitHub Actions runs the suite on Python 3.11–3.13.

## 10. Out of scope / known limitations
- Komo shows only the first ~20 results without login; older matching listings may be missed on the first run.
- Yad2/Madlan/Homeless are reachable only indirectly through search snippets (unverified prices).
- No automatic contact with landlords.
- Tenant classification is phrase‑based. Unusual wording can slip through as `unknown`; the LLM's notes and the "suits a single tenant" tag help, but the listing should still be read before contacting the landlord.

## 11. Publishing
Public GitHub repository `tel-aviv-rental-agent` created with `gh repo create --public --source . --push`; verified with `gh repo view --json visibility,url`.
