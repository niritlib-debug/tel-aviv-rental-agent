"""LLM component: Claude plans which tools to call and selects matches.

The model never produces listings itself. It can only call tools and then
submit IDs of candidates that tools returned; the agent re-validates those IDs
against the buffer and the goal.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are a rental-search agent for Tel Aviv-Yafo, Israel.

Goal: {goal}

How to work:
1. Call memory_summary to see what is already known and how recent runs went.
2. Call search_komo (verified source). Call web_search too if it is available.
   If a tool fails you may retry it once.
3. Review the candidates. Each one includes `passes_goal` and `reasons`, computed
   by code from the goal. Only candidates with passes_goal=true can be accepted.
   `tenant_fit` says whether a single tenant can rent the flat (single_ok / unknown are
   acceptable); `ad_text_excerpt` is the ad's own text, so mention in your note anything
   in it that a single tenant should know.
4. Call submit_matches exactly once with every candidate ID that satisfies the goal,
   with a short note for each (in English): e.g. "new", "price dropped from 5,000",
   "unverified: from a search snippet, check price on the site", "ad says it suits a single tenant",
   "listing page could not be checked for roommate wording".

Rules:
- Only submit IDs that appear in tool results from this run. Never invent listings,
  IDs, prices or URLs.
- Do not exclude a valid match for taste reasons; the user wants all of them.
- After submit_matches, reply with one short sentence summarizing the run."""

TOOLS_SPEC = {
    "memory_summary": {
        "name": "memory_summary",
        "description": "Summary of persistent memory: counts of active/stale listings, IDs already known, and recent runs.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "search_komo": {
        "name": "search_komo",
        "description": "Search Komo (komo.co.il) for Tel Aviv-Yafo rentals using the goal's rooms and max price. "
                       "Returns verified listings parsed from the site (first results page only).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "web_search": {
        "name": "web_search",
        "description": "Web search (Tavily) over Yad2, Madlan, Homeless, Komo and Facebook for matching rentals. "
                       "Fields are extracted from search snippets, so results are unverified.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "submit_matches": {
        "name": "submit_matches",
        "description": "Submit the final list of matching candidate IDs from this run, with a short note for each.",
        "input_schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "note": {"type": "string"}},
                        "required": ["id", "note"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["matches"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    matches: list[dict] = field(default_factory=list)  # [{"id", "note"}]
    submitted: bool = False
    summary: str = ""
    steps: int = 0


class LLMPlanner:
    def __init__(self, client: Any, model: str, max_steps: int = 8, use_fallbacks: bool = True):
        self.client = client
        self.model = model
        self.max_steps = max_steps
        self.use_fallbacks = use_fallbacks

    def _create(self, **kwargs):
        if self.use_fallbacks:
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        return self.client.beta.messages.create(**kwargs)

    def run(self, goal_text: str, tool_names: list[str], execute: Callable[[str, dict], str]) -> LLMResult:
        """Drive the tool-use loop. ``execute(name, input) -> str`` runs a tool and returns JSON text."""
        tools = [TOOLS_SPEC[n] for n in tool_names] + [TOOLS_SPEC["submit_matches"]]
        system = SYSTEM_PROMPT.format(goal=goal_text)
        messages: list[dict] = [{"role": "user", "content": "Run the scheduled search now."}]
        result = LLMResult()

        for step in range(1, self.max_steps + 1):
            result.steps = step
            try:
                response = self._create(model=self.model, max_tokens=16000, system=system, tools=tools,
                                        messages=messages, output_config={"effort": "low"})
            except Exception as exc:  # SDK raises typed APIError subclasses; any failure -> deterministic mode
                raise LLMError(f"Anthropic API call failed: {type(exc).__name__}: {exc}") from exc

            stop = getattr(response, "stop_reason", None)
            if stop == "refusal":
                raise LLMError("model declined the request (stop_reason=refusal)")
            if stop == "max_tokens":
                raise LLMError("model output hit max_tokens")

            messages.append({"role": "assistant", "content": response.content})
            if stop == "pause_turn":
                continue

            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                result.summary = " ".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
                return result

            tool_results = []
            for block in tool_uses:
                tool_input = block.input if isinstance(block.input, dict) else json.loads(block.input or "{}")
                if block.name == "submit_matches":
                    result.matches = [m for m in tool_input.get("matches", []) if isinstance(m, dict) and m.get("id")]
                    result.submitted = True
                    content, is_error = json.dumps({"received": len(result.matches)}), False
                elif block.name in tool_names:
                    try:
                        content, is_error = execute(block.name, tool_input), False
                    except Exception as exc:
                        content, is_error = f"{type(exc).__name__}: {exc}", True
                else:
                    content, is_error = f"unknown tool {block.name!r}", True
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                     "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": tool_results})

        if result.submitted:
            return result
        raise LLMError(f"step limit ({self.max_steps}) reached without submit_matches")
