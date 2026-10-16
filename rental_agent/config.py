"""Configuration: TOML file + environment variables (secrets only from env)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .goal import SearchGoal
from .tenant import TenantRules


class ConfigError(ValueError):
    pass


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); never overrides existing env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    goal: SearchGoal = field(default_factory=SearchGoal)
    timezone: str = "Asia/Jerusalem"
    times: tuple[str, ...] = ("08:00", "20:00")
    db_path: str = "data/rentals.db"
    stale_after_days: int = 7
    llm_enabled: bool = True
    llm_model: str = "claude-opus-5-5"
    llm_max_steps: int = 8
    komo_enabled: bool = True
    web_search_enabled: bool = True
    report_dir: str = "reports"
    details_delay_seconds: float = 1.5
    user_agent: str = "tel-aviv-rental-agent/0.1 (+https://github.com/niritlib-debug/tel-aviv-rental-agent)"

    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def use_llm(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)

    @property
    def use_web_search(self) -> bool:
        return self.web_search_enabled and bool(self.tavily_api_key)

    @property
    def schedule_hours_minutes(self) -> list[tuple[int, int]]:
        out = []
        for t in self.times:
            try:
                h, m = (int(x) for x in t.split(":"))
            except ValueError as exc:
                raise ConfigError(f"bad schedule time {t!r}, expected HH:MM") from exc
            if not (0 <= h < 24 and 0 <= m < 60):
                raise ConfigError(f"bad schedule time {t!r}")
            out.append((h, m))
        return out


def _tenant_rules(data) -> TenantRules:
    try:
        return TenantRules.from_config(data)
    except (ValueError, TypeError) as exc:
        raise ConfigError(str(exc)) from exc


def load_settings(path: str | os.PathLike | None = None, env: dict | None = None) -> Settings:
    if env is None:
        _load_dotenv(Path(".env"))
        env = dict(os.environ)
    path = Path(path or env.get("RENTAL_AGENT_CONFIG", "config.toml"))
    data: dict = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    g = data.get("goal", {})
    defaults = SearchGoal()
    goal = SearchGoal(
        city=g.get("city", defaults.city),
        rooms=float(g.get("rooms", defaults.rooms)),
        max_price=int(g.get("max_price", defaults.max_price)),
        allowed_property_types=tuple(g.get("allowed_property_types", defaults.allowed_property_types)),
        excluded_keywords=tuple(g.get("excluded_keywords", defaults.excluded_keywords)),
        require_parking=bool(g.get("require_parking", defaults.require_parking)),
        single_tenant_only=bool(g.get("single_tenant_only", defaults.single_tenant_only)),
        unchecked_policy=str(g.get("unchecked_policy", defaults.unchecked_policy)),
        tenant_rules=_tenant_rules(g.get("tenant")),
    )
    if goal.unchecked_policy not in ("warn", "skip"):
        raise ConfigError('goal.unchecked_policy must be "warn" or "skip"')
    if goal.max_price <= 0 or goal.rooms <= 0:
        raise ConfigError("goal.max_price and goal.rooms must be positive")

    s, m, llm, src, rep = (data.get(k, {}) for k in ("schedule", "memory", "llm", "sources", "report"))
    settings = Settings(
        goal=goal,
        timezone=s.get("timezone", "Asia/Jerusalem"),
        times=tuple(s.get("times", ("08:00", "20:00"))),
        db_path=m.get("db_path", "data/rentals.db"),
        stale_after_days=int(m.get("stale_after_days", 7)),
        llm_enabled=bool(llm.get("enabled", True)),
        llm_model=llm.get("model", "claude-opus-5-5"),
        llm_max_steps=int(llm.get("max_steps", 8)),
        komo_enabled=bool(src.get("komo", True)),
        web_search_enabled=bool(src.get("web_search", True)),
        report_dir=rep.get("dir", "reports"),
        details_delay_seconds=float(g.get("details_delay_seconds", 1.5)),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
        tavily_api_key=env.get("TAVILY_API_KEY") or None,
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
    )
    settings.schedule_hours_minutes  # validate early
    return settings
