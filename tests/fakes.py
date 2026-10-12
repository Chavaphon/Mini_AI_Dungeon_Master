"""Test doubles: scripted dice, a fake LLM client and pinned stats. Tests never call the real model."""

import copy

from mini_dm.config import load_config
from mini_dm.engine import Dice, Roll, parse_dice

# Fixed stats for rule tests, so tuning the stats in config.json (section 5) does not
# change their expected numbers. test_config and test_state check config against section 5.
RULES_CHARACTERS = {
    "pc": {
        "name": "Lyra",
        "max_hp": 30,
        "ac": 14,
        "attack": {"name": "Short sword", "bonus": 5, "damage": "1d6+3"},
        "fire_bolt": {"bonus": 5, "damage": "1d10"},
        "cure_wounds": {"heal": "1d8+3", "uses": 2},
    },
    "boss": {
        "name": "Ashfang",
        "max_hp": 30,
        "ac": 14,
        "bite": {"bonus": 5, "damage": "1d8+2"},
        "fire_breath": {"bonus": 5, "damage": "2d6", "trigger_hp_pct": 50},
    },
}


def rules_config() -> dict:
    """config.json with the character stats swapped for RULES_CHARACTERS."""
    config = load_config()
    config["characters"] = copy.deepcopy(RULES_CHARACTERS)
    return config


class ScriptedDice(Dice):
    """Dice that return preset faces in order, one face per die rolled."""

    def __init__(self, faces):
        super().__init__(seed=0)
        self._faces = list(faces)

    def roll(self, notation: str) -> Roll:
        spec = parse_dice(notation)
        rolls = []
        for _ in range(spec.count):
            if not self._faces:
                raise AssertionError(f"ScriptedDice ran out of faces rolling {notation}")
            face = self._faces.pop(0)
            if not 1 <= face <= spec.sides:
                raise AssertionError(f"Face {face} is impossible on a d{spec.sides}")
            rolls.append(face)
        return Roll(notation, tuple(rolls), spec.modifier, sum(rolls) + spec.modifier)

    def getstate(self):
        return list(self._faces)

    def setstate(self, state) -> None:
        self._faces = list(state)

    @property
    def remaining(self) -> int:
        return len(self._faces)


class FakeLLM:
    """Records every chat call and returns queued replies in order. A queued exception is raised."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def chat(self, messages, *, temperature, num_predict, json_mode=False):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "num_predict": num_predict,
                "json_mode": json_mode,
            }
        )
        if not self._replies:
            raise AssertionError("FakeLLM got more calls than queued replies")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
