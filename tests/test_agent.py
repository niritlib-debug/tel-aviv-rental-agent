from types import SimpleNamespace

from rental_agent.agent import Agent
from rental_agent.tools.http import SourceError
from rental_agent.tools.notify import MarkdownReportNotifier
from tests.conftest import Clock, at, details_for, make_listing


def make_agent(settings, memory, **kw):
    kw.setdefault("details_fetcher", details_for())  # never hit the network in tests
    kw.setdefault("sleep", lambda s: None)
    return Agent(settings, memory, **kw)


class ListNotifier:
    def __init__(self):
        self.reports = []

    def send(self, report):
        self.reports.append(report)


def komo_source(*listings):
    return lambda: list(listings)


def failing_source():
    raise SourceError("timeout")


GOOD = make_listing("1", price=4800)
GOOD2 = make_listing("2", price=5200)
BAD = make_listing("3", price=6000)


def test_deterministic_run_new_then_changed(settings, memory, tmp_path):
    notifier = ListNotifier()
    clock = Clock(at(2026, 10, 1))
    agent = make_agent(settings, memory, sources={"search_komo": komo_source(GOOD, BAD)},
                       notifiers=[notifier, MarkdownReportNotifier(tmp_path / "r")], now=clock)
    r1 = agent.run_once()
    assert r1.status == "ok" and [l.id for l in r1.new] == ["komo:1"]
    assert "https://www.komo.co.il/code/nadlan/details/?modaaNum=1" in r1.to_markdown()

    clock.t = at(2026, 10, 1, 20)
    agent.sources = {"search_komo": komo_source(make_listing("1", price=4500), GOOD2)}
    r2 = agent.run_once()
    assert [l.id for l in r2.new] == ["komo:2"]
    assert r2.changed[0][1] == [("price", "4800", "4500")]
    assert len(list((tmp_path / "r").glob("*.md"))) == 2
    assert memory.recent_runs(1)[0]["n_new"] == 1


def test_partial_when_one_source_fails(settings, memory):
    agent = make_agent(settings, memory, sources={"search_komo": komo_source(GOOD), "web_search": failing_source},
                  notifiers=[])
    report = agent.run_once()
    assert report.status == "partial" and len(report.new) == 1
    assert any("web_search: timeout" in e for e in report.errors)


def test_failed_when_all_sources_fail(settings, memory):
    report = make_agent(settings, memory, sources={"search_komo": failing_source}, notifiers=[]).run_once()
    assert report.status == "failed"
    assert memory.recent_runs(1)[0]["status"] == "failed"


def test_notifier_error_does_not_crash(settings, memory):
    class Boom:
        def send(self, report):
            raise RuntimeError("telegram down")
    report = make_agent(settings, memory, sources={"search_komo": komo_source(GOOD)}, notifiers=[Boom()]).run_once()
    assert report.status == "ok" and any("telegram down" in e for e in report.errors)


def test_dry_run_does_not_write(settings, memory):
    report = make_agent(settings, memory, sources={"search_komo": komo_source(GOOD)}, notifiers=[]).run_once(dry_run=True)
    assert len(report.new) == 1 and memory.listings() == []


# ---- LLM mode with a fake Anthropic client -----------------------------------

def tool_use(id_, name, input_=None):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_ or {})


def text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClient:
    """Mimics client.beta.messages.create with a scripted list of responses."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot; the loop appends later
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


def test_llm_mode_uses_tools_and_rejects_invented_ids(settings, memory):
    client = FakeClient([
        resp("tool_use", tool_use("t1", "memory_summary"), tool_use("t2", "search_komo")),
        resp("tool_use", tool_use("t3", "submit_matches", {"matches": [
            {"id": "komo:1", "note": "new, good price"},
            {"id": "komo:3", "note": "over budget"},
            {"id": "yad2:999", "note": "invented"},
        ]})),
        resp("end_turn", text("Found 1 match.")),
    ])
    agent = make_agent(settings, memory, llm_client=client, sources={"search_komo": komo_source(GOOD, BAD, GOOD2)},
                  notifiers=[])
    report = agent.run_once()
    assert report.mode == "llm"
    # komo:1 selected; komo:2 omitted by the LLM but valid -> still included; komo:3 & invented rejected
    assert sorted(l.id for l in report.new) == ["komo:1", "komo:2"]
    assert report.notes["komo:1"] == "new, good price"
    assert any("yad2:999" in e for e in report.errors)
    assert any("komo:3" in e and "fails the goal" in e for e in report.errors)
    # tool results were sent back with matching ids
    tool_results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in tool_results] == ["t1", "t2"]
    assert client.requests[0]["model"] == "claude-opus-5-5"
    assert client.requests[0]["fallbacks"] == "default"


def test_llm_api_error_falls_back_to_deterministic(settings, memory):
    client = FakeClient([RuntimeError("overloaded")])
    report = make_agent(settings, memory, llm_client=client, sources={"search_komo": komo_source(GOOD)},
                   notifiers=[]).run_once()
    assert report.mode == "llm->deterministic" and [l.id for l in report.new] == ["komo:1"]
    assert any("overloaded" in e for e in report.errors)


def test_llm_refusal_falls_back(settings, memory):
    client = FakeClient([resp("refusal")])
    report = make_agent(settings, memory, llm_client=client, sources={"search_komo": komo_source(GOOD)},
                   notifiers=[]).run_once()
    assert report.mode == "llm->deterministic" and len(report.new) == 1


def test_llm_step_limit(settings, memory):
    settings.llm_max_steps = 2
    client = FakeClient([resp("tool_use", tool_use(f"t{i}", "memory_summary")) for i in range(2)])
    report = make_agent(settings, memory, llm_client=client, sources={"search_komo": komo_source(GOOD)},
                   notifiers=[]).run_once()
    assert report.mode == "llm->deterministic" and len(report.new) == 1
    assert any("step limit" in e for e in report.errors)


def test_llm_tool_failure_is_reported_to_model(settings, memory):
    client = FakeClient([
        resp("tool_use", tool_use("t1", "web_search")),
        resp("tool_use", tool_use("t2", "submit_matches", {"matches": [{"id": "komo:1", "note": "ok"}]})),
        resp("end_turn", text("done")),
    ])
    report = make_agent(settings, memory, llm_client=client,
                   sources={"search_komo": komo_source(GOOD), "web_search": failing_source}, notifiers=[]).run_once()
    first_result = client.requests[1]["messages"][-1]["content"][0]
    assert first_result["is_error"] is True
    # The LLM never called search_komo; the deterministic gap-filler did, so the match is still found.
    assert report.status == "partial" and [l.id for l in report.new] == ["komo:1"]
