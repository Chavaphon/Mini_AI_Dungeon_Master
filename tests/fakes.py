"""Test doubles: scripted dice and a fake LLM client. Tests never call the real model."""

from mini_dm.engine import Dice, Roll, parse_dice


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

    @property
    def remaining(self) -> int:
        return len(self._faces)


class FakeLLM:
    """Records every chat call and returns queued replies in order."""

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
        return self._replies.pop(0)
