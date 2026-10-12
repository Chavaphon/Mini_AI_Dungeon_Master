"""Ollama client plus the intent and narration calls.

The model only proposes an action and narrates resolved facts. Nothing it
returns is written into game state.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from mini_dm.engine import CORRECT_TARGET, PC_ACTIONS, validate_intent

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Keyword fallback (FR-4), checked in order: spells first, so "hit it with a fire bolt" is a bolt.
_FALLBACK_KEYWORDS = (
    ("fire_bolt", re.compile(r"\bfire\s*bolt\b", re.IGNORECASE)),
    ("cure_wounds", re.compile(r"\b(heal|cure)", re.IGNORECASE)),
    ("dodge", re.compile(r"\b(dodge|evade)", re.IGNORECASE)),
    ("attack", re.compile(r"\b(sword|attack|slash|stab|strike)", re.IGNORECASE)),
)


class OllamaClient:
    """Minimal client for a local Ollama server's /api/chat endpoint."""

    def __init__(
        self, host: str, model: str, timeout_s: float, keep_alive: str | None = None, transport=None
    ):
        self.host = host
        self.model = model
        self.timeout_s = timeout_s
        self.keep_alive = keep_alive
        self._http = httpx.Client(base_url=host, timeout=timeout_s, transport=transport)

    def warm_up(self, timeout_s: float) -> bool:
        """Load the model into memory before the first turn. Returns False if it fails.

        A cold load can take longer than the per-call timeout, so it gets its own.
        """
        body = {"model": self.model, "messages": [], "keep_alive": self.keep_alive, "stream": False}
        try:
            self._http.post("/api/chat", json=body, timeout=timeout_s).raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    def chat(self, messages, *, temperature, num_predict, json_mode=False) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if json_mode:
            body["format"] = "json"
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        response = self._http.post("/api/chat", json=body)
        response.raise_for_status()
        return response.json()["message"]["content"]


def client_from_config(config: dict) -> OllamaClient:
    ollama = config["ollama"]
    return OllamaClient(
        ollama["host"], ollama["model"], ollama["timeout_s"], keep_alive=ollama["keep_alive"]
    )


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def parse_intent(raw: str) -> dict | None:
    """Return {"action", "target"}, lowercased and trimmed, if raw has the FR-3 shape, else None.

    Only those two fields are read. Whether the action is allowed is the engine's call.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    action, target = data.get("action"), data.get("target")
    if not isinstance(action, str) or not isinstance(target, str):
        return None
    return {"action": action.strip().lower(), "target": target.strip().lower()}


def request_intent(
    client, config: dict, text: str, retry: tuple[str, str] | None = None
) -> tuple[str, dict | None]:
    """Intent call (FR-3): temperature 0, JSON mode. Returns the raw reply and the parsed intent.

    `retry` is the previous (raw reply, reason it was invalid), sent back for the FR-4 retry.
    """
    messages = [
        {"role": "system", "content": load_prompt("intent")},
        {"role": "user", "content": text},
    ]
    if retry:
        raw, reason = retry
        messages += [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": f"That reply was invalid: {reason} "
                'Reply with one JSON object: {"action": "<action>", "target": "<target>"}.',
            },
        ]
    raw = client.chat(
        messages,
        temperature=config["intent"]["temperature"],
        num_predict=config["intent"]["num_predict"],
        json_mode=True,
    )
    return raw, parse_intent(raw)


def fallback_intent(text: str) -> dict | None:
    """Keyword fallback parser (FR-4) for when the model fails. Never returns `none`."""
    for action, pattern in _FALLBACK_KEYWORDS:
        if pattern.search(text):
            return {"action": action, "target": CORRECT_TARGET.get(action, "self")}
    return None


@dataclass
class IntentResolution:
    intent: dict | None  # None: refuse and ask to rephrase; the turn does not advance
    raw_replies: list[str] = field(default_factory=list)
    source: str | None = None  # "llm", "retry" or "fallback"
    unknown_action: bool = False  # some attempt proposed an action not on the allow-list


def resolve_intent(client, config: dict, text: str) -> IntentResolution:
    """Intent call, validated by the engine, with one retry and then the keyword fallback.

    At most `max_llm_calls_per_phase` calls (GR-9). The model's reply is only a proposal.
    """
    resolution = IntentResolution(intent=None)
    retry = None
    for attempt in range(config["limits"]["max_llm_calls_per_phase"]):
        raw, intent = request_intent(client, config, text, retry)
        resolution.raw_replies.append(raw)
        if intent is None:
            reason = 'It must be JSON with string fields "action" and "target".'
        else:
            reason = validate_intent(intent["action"], intent["target"])
            if reason is None:
                resolution.intent = intent
                resolution.source = "llm" if attempt == 0 else "retry"
                return resolution
            if intent["action"] not in PC_ACTIONS:
                resolution.unknown_action = True
                # Keep the model from swapping in an allowed action for a spell Lyra lacks:
                # without this, the 8B model turned "fireball" into "fire_bolt" on the retry.
                action = intent["action"]
                reason += (
                    f" {action!r} is not the same as any of Lyra's actions. If the player "
                    f"asked for {action!r}, reply exactly {json.dumps(intent)}."
                )
        retry = (raw, reason)

    resolution.intent = fallback_intent(text)
    if resolution.intent:
        resolution.source = "fallback"
    return resolution


def request_narration(client, config: dict, facts: dict) -> str:
    """Narration call (FR-7): the resolved facts only, at the narration temperature."""
    text = client.chat(
        [
            {"role": "system", "content": load_prompt("narration")},
            {"role": "user", "content": json.dumps(facts)},
        ],
        temperature=config["narration"]["temperature"],
        num_predict=config["narration"]["num_predict"],
    )
    return text.strip()
