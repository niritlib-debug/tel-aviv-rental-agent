"""Static dashboard export (Architecture.md §4.5): listings.json + runs.json + index.html.

The page is plain HTML/JS with no build step and no external requests, so it can be
served by GitHub Pages and works offline once loaded.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import Settings
from .memory import Memory

STALE_AFTER_HOURS = 13  # two slots 12 h apart + slack: older than this means a run was missed


def build_data(memory: Memory, settings: Settings, now: datetime) -> tuple[dict, dict]:
    listings = []
    for row in memory.listings():
        listings.append({
            "id": row["id"], "url": row["url"], "title": row["title"], "neighborhood": row["neighborhood"],
            "street": row["street"], "price": row["price"], "rooms": row["rooms"], "size_sqm": row["size_sqm"],
            "floor": row["floor"], "property_type": row["property_type"],
            "has_parking": None if row["has_parking"] is None else bool(row["has_parking"]),
            "tenant_fit": row["tenant_fit"], "verified": bool(row["verified"]),
            "listing_page_checked": bool(row["details_checked_at"]),
            "first_seen": row["first_seen"], "last_seen": row["last_seen"],
            "price_history": memory.price_history(row["id"]),
        })
    goal = settings.goal
    last_ok = memory.last_success()
    meta = {
        "generated_at": now.isoformat(),
        "timezone": settings.timezone,
        "schedule": list(settings.times),
        "stale_after_hours": STALE_AFTER_HOURS,
        "last_success_at": (last_ok or {}).get("finished_at") or (last_ok or {}).get("started_at"),
        "goal": {"city": goal.city, "rooms": goal.rooms, "max_price": goal.max_price,
                 "require_parking": goal.require_parking, "single_tenant_only": goal.single_tenant_only},
    }
    runs = [{k: r[k] for k in ("id", "started_at", "finished_at", "status", "mode", "slot", "n_candidates",
                               "n_matches", "n_new", "n_changed")}
            | {"errors": json.loads(r["errors"] or "[]")} for r in memory.recent_runs(30)]
    return {"meta": meta, "listings": listings}, {"runs": runs}


def export_dashboard(memory: Memory, settings: Settings, out_dir: str | Path, now: datetime) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    listings, runs = build_data(memory, settings, now)
    (out / "listings.json").write_text(json.dumps(listings, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is on GitHub Pages
    return out


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tel Aviv Rentals</title>
<meta name="description" content="3-room flats with parking in Tel Aviv up to 5,200 NIS, found twice a day by the rental agent.">
<style>
:root {
  --bg: #f6f5f2; --surface: #ffffff; --text: #1d1c1a; --muted: #6b6862; --border: #e3e0da;
  --accent: #1f6f5c; --accent-soft: #e3f1ec; --warn: #9a5b00; --warn-soft: #fbf0dc;
  --bad: #b3261e; --bad-soft: #fbe6e4; --ok: #1f6f5c;
  --radius: 12px; --font: system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans Hebrew", Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141412; --surface: #1d1d1a; --text: #ecebe7; --muted: #a29f98; --border: #33322e;
    --accent: #6fd0b4; --accent-soft: #17332b; --warn: #f0b45a; --warn-soft: #3a2b12;
    --bad: #ff8a80; --bad-soft: #3b1a17; --ok: #6fd0b4;
  }
}
:root[data-theme="dark"] {
  --bg: #141412; --surface: #1d1d1a; --text: #ecebe7; --muted: #a29f98; --border: #33322e;
  --accent: #6fd0b4; --accent-soft: #17332b; --warn: #f0b45a; --warn-soft: #3a2b12;
  --bad: #ff8a80; --bad-soft: #3b1a17; --ok: #6fd0b4;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 var(--font); }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 16px; margin: 32px 0 12px; }
.sub { color: var(--muted); margin: 0 0 16px; }
.health { display: flex; gap: 10px; align-items: center; padding: 12px 14px; border-radius: var(--radius);
  background: var(--accent-soft); color: var(--ok); font-weight: 600; }
.health.bad { background: var(--bad-soft); color: var(--bad); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: currentColor; flex: none; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 16px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; }
.stat b { display: block; font-size: 22px; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); font-size: 13px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
select, button { font: inherit; color: var(--text); background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; }
button { cursor: pointer; }
button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
.cards { display: grid; gap: 10px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px;
  display: grid; grid-template-columns: 1fr auto; gap: 4px 16px; }
.card.new { border-color: var(--accent); }
.addr { font-weight: 600; overflow-wrap: anywhere; text-align: left; }
.price { font-weight: 700; font-size: 18px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.meta { color: var(--muted); font-size: 13px; grid-column: 1 / -1; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; grid-column: 1 / -1; margin-top: 4px; }
.tag { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }
.tag.warn { background: var(--warn-soft); color: var(--warn); }
.history { font-size: 13px; color: var(--muted); grid-column: 1 / -1; }
.history .down { color: var(--ok); font-weight: 600; }
.history .up { color: var(--bad); font-weight: 600; }
a.open { grid-column: 1 / -1; color: var(--accent); font-weight: 600; text-decoration: none; margin-top: 4px; }
a.open:hover { text-decoration: underline; }
.empty { padding: 24px; text-align: center; color: var(--muted); background: var(--surface);
  border: 1px dashed var(--border); border-radius: var(--radius); }
.runs-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; }
tr:last-child td { border-bottom: none; }
.st-ok { color: var(--ok); } .st-partial { color: var(--warn); } .st-failed { color: var(--bad); }
footer { margin-top: 32px; color: var(--muted); font-size: 13px; }
footer a { color: inherit; }
</style>
</head>
<body>
<main>
  <h1>Tel Aviv Rentals</h1>
  <p class="sub" id="goal">Loading…</p>
  <div class="health" id="health" role="status"><span class="dot"></span><span id="health-text">Loading…</span></div>
  <div class="stats" id="stats"></div>

  <h2>Current matches</h2>
  <div class="controls">
    <select id="hood" aria-label="Neighborhood"><option value="">All neighborhoods</option></select>
    <select id="sort" aria-label="Sort">
      <option value="new">Newest first</option><option value="price">Cheapest first</option>
    </select>
    <button id="only-new" aria-pressed="false">New since my last visit</button>
  </div>
  <div class="cards" id="cards"></div>

  <h2>Run health (last 30 runs)</h2>
  <div class="runs-wrap"><table>
    <thead><tr><th>Run</th><th>Started</th><th>Status</th><th>Mode</th><th>Matches</th><th>New</th><th>Changed</th><th>Errors</th></tr></thead>
    <tbody id="runs"></tbody>
  </table></div>

  <footer>Data refreshes after every run. Read each ad before contacting the landlord.
    · <a href="https://github.com/niritlib-debug/tel-aviv-rental-agent">Source and design</a></footer>
</main>
<script>
const $ = (id) => document.getElementById(id);
const nis = (n) => n == null ? "—" : "₪" + Number(n).toLocaleString("en-US");
const fmt = (iso) => iso ? new Date(iso).toLocaleString("en-GB", {timeZone: "Asia/Jerusalem", day: "numeric",
  month: "short", hour: "2-digit", minute: "2-digit"}) : "—";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function store(key, value) { try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { return null; } }

let listings = [], lastVisit = store("lastVisit");
const t = (iso) => new Date(iso).getTime();
const isNewer = (l) => !!lastVisit && t(l.first_seen) > t(lastVisit);
let onlyNew = false;

function render() {
  const hood = $("hood").value, sort = $("sort").value;
  let rows = listings.filter((l) => !hood || l.neighborhood === hood);
  if (onlyNew && lastVisit) rows = rows.filter(isNewer);
  rows.sort(sort === "price" ? (a, b) => (a.price ?? 1e9) - (b.price ?? 1e9)
                             : (a, b) => t(b.first_seen) - t(a.first_seen));
  $("cards").innerHTML = rows.length ? rows.map(card).join("") :
    `<div class="empty">${onlyNew ? "Nothing new since your last visit." : "No matching flats right now."}</div>`;
}

function card(l) {
  const isNew = isNewer(l);
  const tags = [];
  if (isNew) tags.push(`<span class="tag">New</span>`);
  if (l.has_parking) tags.push(`<span class="tag">Parking</span>`);
  if (l.tenant_fit === "single_ok") tags.push(`<span class="tag">Suits a single tenant</span>`);
  if (!l.verified) tags.push(`<span class="tag warn">Unverified: from search snippet</span>`);
  if (l.id.startsWith("komo:") && !l.listing_page_checked) tags.push(`<span class="tag warn">Not checked for roommates</span>`);
  const details = [l.rooms && `${l.rooms} rooms`, l.size_sqm && `${l.size_sqm} m²`, l.floor && `floor ${l.floor}`,
    l.property_type].filter(Boolean).map(esc).join(" · ");
  const hist = (l.price_history || []).map((h) => {
    const cls = Number(h.new_value) < Number(h.old_value) ? "down" : "up";
    return `${fmt(h.changed_at)}: ${nis(h.old_value)} → <span class="${cls}">${nis(h.new_value)}</span>`;
  }).join(" · ");
  return `<article class="card${isNew ? " new" : ""}">
    <div class="addr" dir="auto">${esc([l.neighborhood, l.street].filter(Boolean).join(", ") || l.title)}</div>
    <div class="price">${nis(l.price)}</div>
    <div class="meta">${details} · first seen ${fmt(l.first_seen)}</div>
    ${hist ? `<div class="history">Price history: ${hist}</div>` : ""}
    <div class="tags">${tags.join("")}</div>
    <a class="open" href="${esc(l.url)}" target="_blank" rel="noopener">Open the ad →</a>
  </article>`;
}

function renderRuns(runs) {
  $("runs").innerHTML = runs.map((r) => `<tr>
    <td>#${r.id}</td><td>${fmt(r.started_at)}</td><td class="st-${esc(r.status)}">${esc(r.status)}</td>
    <td>${esc(r.mode)}</td><td>${r.n_matches}</td><td>${r.n_new}</td><td>${r.n_changed}</td>
    <td title="${esc(r.errors.join("\n"))}">${r.errors.length}</td></tr>`).join("");
}

async function main() {
  try {
    const [l, r] = await Promise.all([fetch("listings.json", {cache: "no-store"}).then((x) => x.json()),
                                      fetch("runs.json", {cache: "no-store"}).then((x) => x.json())]);
    listings = l.listings;
    const m = l.meta, g = m.goal;
    $("goal").textContent = `${g.rooms}-room flats in Tel Aviv-Yafo up to ${nis(g.max_price)}` +
      (g.require_parking ? ", with parking" : "") + (g.single_tenant_only ? ", for a single tenant" : "") +
      `. Searched at ${m.schedule.join(" and ")} Israel time.`;
    const ageH = m.last_success_at ? (Date.now() - new Date(m.last_success_at)) / 36e5 : Infinity;
    const healthy = ageH <= m.stale_after_hours;
    $("health").classList.toggle("bad", !healthy);
    $("health-text").textContent = m.last_success_at
      ? `Last successful run: ${fmt(m.last_success_at)}` + (healthy ? "" : ` — more than ${m.stale_after_hours} h ago, a run was missed`)
      : "No successful run yet";
    const newCount = lastVisit ? listings.filter(isNewer).length : listings.length;
    const prices = listings.map((x) => x.price).filter((x) => x != null);
    $("stats").innerHTML = [
      [listings.length, "current matches"], [newCount, lastVisit ? "new since last visit" : "new to you"],
      [prices.length ? nis(Math.min(...prices)) : "—", "cheapest"],
      [r.runs.filter((x) => x.status === "failed").length, "failed runs (last 30)"],
    ].map(([v, t]) => `<div class="stat"><b>${v}</b><span>${t}</span></div>`).join("");
    const hoods = [...new Set(listings.map((x) => x.neighborhood).filter(Boolean))].sort();
    $("hood").insertAdjacentHTML("beforeend", hoods.map((h) => `<option dir="auto">${esc(h)}</option>`).join(""));
    render(); renderRuns(r.runs);
    store("lastVisit", new Date().toISOString());
  } catch (e) {
    $("health").classList.add("bad");
    $("health-text").textContent = "Could not load data: " + e.message;
  }
}
$("hood").onchange = render; $("sort").onchange = render;
$("only-new").onclick = (e) => { onlyNew = !onlyNew; e.currentTarget.setAttribute("aria-pressed", onlyNew); render(); };
main();
</script>
</body>
</html>
"""
