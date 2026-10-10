"""Ollama client plus the intent and narration calls.

The model only proposes an action and narrates resolved facts. Nothing it
returns is written into game state.
"""

import json
from pathlib import Path

import httpx

PROMPTS_DIR = Path(__file__).parent / "prompts"
ACTIONS = ("attack", "fire_bolt", "cure_wounds", "dodge", "none")


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
    """Return {"action", "target"} if raw is a valid FR-3 intent, else None."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    action, target = data.get("action"), data.get("target")
    if action not in ACTIONS or not isinstance(target, str):
        return None
    return {"action": action, "target": target}


def request_intent(client, config: dict, text: str) -> tuple[str, dict | None]:
    """Intent call (FR-3): temperature 0, JSON mode. Returns the raw reply and the parsed intent."""
    raw = client.chat(
        [
            {"role": "system", "content": load_prompt("intent")},
            {"role": "user", "content": text},
        ],
        temperature=config["intent"]["temperature"],
        num_predict=config["intent"]["num_predict"],
        json_mode=True,
    )
    return raw, parse_intent(raw)


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
