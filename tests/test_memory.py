from rental_agent.memory import CHANGED, NEW, REAPPEARED, UNCHANGED, Memory
from tests.conftest import at, make_listing


def test_new_then_unchanged(memory):
    r1 = memory.start_run(at(2026, 10, 1), "deterministic")
    assert memory.upsert(make_listing("1"), r1, at(2026, 10, 1)) == (NEW, [])
    r2 = memory.start_run(at(2026, 10, 1, 20), "deterministic")
    assert memory.upsert(make_listing("1"), r2, at(2026, 10, 1, 20)) == (UNCHANGED, [])
    row = memory.get("komo:1")
    assert row["first_seen"].startswith("2026-10-01T08:00") and row["last_seen"].startswith("2026-10-01T20:00")


def test_price_change_is_tracked(memory):
    r = memory.start_run(at(2026, 10, 1), "x")
    memory.upsert(make_listing("1", price=5200), r, at(2026, 10, 1))
    status, diffs = memory.upsert(make_listing("1", price=4900), r, at(2026, 10, 2))
    assert status == CHANGED and diffs == [("price", "5200", "4900")]
    changes = memory.changes("komo:1")
    assert [(c["field"], c["old_value"], c["new_value"]) for c in changes] == [("price", "5200", "4900")]
    assert memory.get("komo:1")["price"] == 4900


def test_dedup_by_url_across_ids(memory):
    r = memory.start_run(at(2026, 10, 1), "x")
    url = "https://www.yad2.co.il/realestate/item/abc?utm_source=x#top"
    memory.upsert(make_listing("a", source="web:yad2.co.il", url=url), r, at(2026, 10, 1))
    status, _ = memory.upsert(make_listing("b", source="web:yad2.co.il", url="https://WWW.yad2.co.il/realestate/item/abc"),
                              r, at(2026, 10, 1))
    assert status in (UNCHANGED, CHANGED)
    assert len(memory.listings()) == 1


def test_stale_and_reappeared(memory):
    r = memory.start_run(at(2026, 10, 1), "x")
    memory.upsert(make_listing("1"), r, at(2026, 10, 1))
    memory.upsert(make_listing("2"), r, at(2026, 10, 9))
    assert memory.mark_stale(at(2026, 10, 9), stale_after_days=7) == 1
    assert memory.get("komo:1")["status"] == "stale" and memory.get("komo:2")["status"] == "active"
    assert memory.upsert(make_listing("1"), r, at(2026, 10, 10)) == (REAPPEARED, [])
    assert memory.get("komo:1")["status"] == "active"


def test_runs_recorded(memory):
    r = memory.start_run(at(2026, 10, 1), "llm")
    memory.finish_run(r, at(2026, 10, 1, 8, 1), "partial", mode="llm", n_candidates=5, n_matches=2,
                      n_new=1, n_changed=1, errors=["web_search: timeout"])
    run = memory.recent_runs(1)[0]
    assert run["status"] == "partial" and run["n_new"] == 1 and "timeout" in run["errors"]
    assert memory.summary()["recent_runs"][0]["id"] == r


def test_persists_on_disk(tmp_path):
    path = tmp_path / "db" / "rentals.db"
    with Memory(path) as m:
        m.upsert(make_listing("1"), m.start_run(at(2026, 10, 1), "x"), at(2026, 10, 1))
    with Memory(path) as m:
        assert m.get("komo:1")["price"] == 4800


def test_parking_stored(memory):
    r = memory.start_run(at(2026, 10, 1), "x")
    memory.upsert(make_listing("1", has_parking=True), r, at(2026, 10, 1))
    memory.upsert(make_listing("2", has_parking=None), r, at(2026, 10, 1))
    assert memory.get("komo:1")["has_parking"] == 1 and memory.get("komo:2")["has_parking"] is None


def test_migrates_v1_database(tmp_path):
    import sqlite3
    from rental_agent.memory import SCHEMA
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA user_version = 1")
    conn.close()
    with Memory(path) as m:
        assert m.conn.execute("PRAGMA user_version").fetchone()[0] == 3
        m.upsert(make_listing("1"), m.start_run(at(2026, 10, 1), "x"), at(2026, 10, 1))
        assert m.get("komo:1")["has_parking"] == 1


def test_migrates_v2_database_keeps_rows(tmp_path):
    import sqlite3
    from rental_agent.memory import SCHEMA
    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("ALTER TABLE listings ADD COLUMN has_parking INTEGER")
    conn.execute("INSERT INTO listings(id, source, source_id, url, content_hash, first_seen, last_seen, has_parking) "
                 "VALUES ('komo:9', 'komo', '9', 'https://www.komo.co.il/x', 'h', '2026-10-01', '2026-10-01', 1)")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    with Memory(path) as m:
        row = m.get("komo:9")
        assert row["has_parking"] == 1 and row["tenant_fit"] is None and row["details_checked_at"] is None


def test_tenant_fields_stored_and_tenant_change_recorded(memory):
    r = memory.start_run(at(2026, 10, 1), "x")
    memory.upsert(make_listing("1", tenant_fit="unknown", full_description="דירה", site_suits_roommates=True,
                               details_checked_at="2026-10-01T08:00:00+03:00"), r, at(2026, 10, 1))
    row = memory.get("komo:1")
    assert (row["tenant_fit"], row["full_description"], row["site_suits_roommates"]) == ("unknown", "דירה", 1)
    status, diffs = memory.upsert(make_listing("1", tenant_fit="single_ok"), r, at(2026, 10, 2))
    assert status == UNCHANGED and diffs == []  # not reported as "changed"...
    assert [(c["field"], c["old_value"], c["new_value"]) for c in memory.changes("komo:1")] == \
        [("tenant_fit", "unknown", "single_ok")]  # ...but recorded
