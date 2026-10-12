"""JSONL turn log (FR-11): one JSON line per player submission, one file per session.

Only records what the engine and the LLM calls already produced. Nothing here changes state.
"""

import dataclasses
import json
import uuid
from datetime import datetime
from pathlib import Path

from mini_dm.config import CONFIG_PATH
from mini_dm.engine import ActionResult, FightState, HealResult, Roll, TurnResult


def log_dir(config: dict) -> Path:
    """The log directory from config, relative to the repo root."""
    return CONFIG_PATH.parent / config["logging"]["dir"]


def new_log_path(directory: Path) -> Path:
    """A fresh file for one session. The file is created on the first append."""
    return directory / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl"


def _roll(result: TurnResult, purpose: str, roll: Roll) -> dict:
    return {
        "actor": result.actor,
        "action": result.action,
        "purpose": purpose,
        "notation": roll.notation,
        "rolls": list(roll.rolls),
        "modifier": roll.modifier,
        "total": roll.total,
    }


def dice_rolls(results: list[TurnResult]) -> list[dict]:
    """Every die rolled this turn, in order. Dodge and `none` roll nothing."""
    rolls = []
    for result in results:
        if isinstance(result, ActionResult):
            rolls.append(_roll(result, "attack", result.attack_roll))
            if result.damage_roll:
                rolls.append(_roll(result, "damage", result.damage_roll))
        elif isinstance(result, HealResult) and result.heal_roll:
            rolls.append(_roll(result, "heal", result.heal_roll))
    return rolls


def state_dict(state: FightState) -> dict:
    return dataclasses.asdict(state)


def new_record(session_id: str | None, seed: int, turn: int, text: str, state: FightState) -> dict:
    """A turn record with the FR-11 fields at their empty values, taken before the turn runs."""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "seed": seed,
        "turn": turn,
        "status": "resolved",  # or refused_rephrase, refused_spell, unavailable, fight_over
        "player_input": text,
        "raw_llm_outputs": {"intent": [], "narration": []},
        "parsed_action": None,
        "intent_source": None,  # llm, retry, fallback, or guardrail when input was blocked
        "validation": [],  # per intent attempt: why it was invalid, or None
        "dice_rolls": [],
        "facts": None,
        "state_before": state_dict(state),
        "state_after": None,
        "narration": None,
        "narration_source": None,
        "reply": None,
        "guardrail_triggers": [],
        "error": None,
    }


def append(path: Path, record: dict) -> None:
    """Append one record as a JSON line, creating the directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
