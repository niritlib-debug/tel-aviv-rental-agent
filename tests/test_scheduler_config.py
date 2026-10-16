import pytest

from rental_agent.config import ConfigError, Settings, load_settings
from rental_agent.scheduler import next_run_times, safe_job
from tests.conftest import at


def test_twice_daily_in_jerusalem():
    times = next_run_times(Settings(), 4, start=at(2026, 10, 16, 21, 0))
    assert [t.strftime("%Y-%m-%d %H:%M") for t in times] == [
        "2026-10-17 08:00", "2026-10-17 20:00", "2026-10-18 08:00", "2026-10-18 20:00"]
    assert all(t.tzinfo.key == "Asia/Jerusalem" for t in times)


def test_dst_boundary_keeps_local_time():
    # Israel leaves DST on Sunday 2026-10-25 (02:00 IDT -> 01:00 IST).
    times = next_run_times(Settings(), 4, start=at(2026, 10, 24, 21, 0))
    assert [t.strftime("%H:%M %Z") for t in times] == ["08:00 IST", "20:00 IST", "08:00 IST", "20:00 IST"]
    assert times[0].utcoffset().total_seconds() == 2 * 3600


def test_summer_offset():
    t = next_run_times(Settings(), 1, start=at(2026, 7, 1, 7, 0))[0]
    assert t.strftime("%H:%M") == "08:00" and t.utcoffset().total_seconds() == 3 * 3600


def test_safe_job_swallows_errors():
    def boom():
        raise RuntimeError("x")
    safe_job(boom)()  # must not raise


def test_load_settings_from_toml(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('[goal]\nmax_price = 5000\n[schedule]\ntimes = ["09:30"]\n[llm]\nmodel = "claude-sonnet-5-5"\n',
                   encoding="utf-8")
    s = load_settings(cfg, env={"ANTHROPIC_API_KEY": "k"})
    assert s.goal.max_price == 5000 and s.goal.rooms == 3 and s.times == ("09:30",)
    assert s.llm_model == "claude-sonnet-5-5" and s.use_llm and not s.use_web_search
    assert s.goal.require_parking is True


def test_defaults_without_file(tmp_path):
    s = load_settings(tmp_path / "missing.toml", env={})
    assert s.goal.max_price == 5200 and s.timezone == "Asia/Jerusalem" and not s.use_llm


@pytest.mark.parametrize("body", ['[schedule]\ntimes = ["25:00"]\n', '[goal]\nmax_price = -1\n', "not toml ["])
def test_invalid_config(tmp_path, body):
    cfg = tmp_path / "c.toml"
    cfg.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(cfg, env={})


def test_parking_can_be_disabled(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[goal]\nrequire_parking = false\n", encoding="utf-8")
    assert load_settings(cfg, env={}).goal.require_parking is False
