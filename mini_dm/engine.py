"""Rules engine: state, dice, rules and boss policy.

The engine owns all game state and has no LLM dependency. Every die roll
comes from the single seeded random.Random instance held by Dice.
"""

import random
import re
from dataclasses import dataclass

_DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


@dataclass(frozen=True)
class DiceSpec:
    count: int
    sides: int
    modifier: int


@dataclass(frozen=True)
class Roll:
    notation: str
    rolls: tuple[int, ...]
    modifier: int
    total: int


def parse_dice(notation: str) -> DiceSpec:
    """Parse XdY, XdY+Z or XdY-Z notation. Raises ValueError if invalid."""
    match = _DICE_RE.match(re.sub(r"\s+", "", notation))
    if not match:
        raise ValueError(f"Invalid dice notation: {notation!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    if count < 1 or sides < 1:
        raise ValueError(f"Invalid dice notation: {notation!r}")
    return DiceSpec(count, sides, int(match.group(3) or 0))


class Dice:
    """Seeded dice roller. Same seed and same calls give the same rolls."""

    def __init__(self, seed: int):
        self._rng = random.Random(seed)

    def roll(self, notation: str) -> Roll:
        spec = parse_dice(notation)
        rolls = tuple(self._rng.randint(1, spec.sides) for _ in range(spec.count))
        return Roll(notation, rolls, spec.modifier, sum(rolls) + spec.modifier)


@dataclass
class Combatant:
    name: str
    max_hp: int
    hp: int
    ac: int


@dataclass
class FightState:
    pc: Combatant
    boss: Combatant
    cure_wounds_uses: int
    fire_breath_used: bool = False
    pc_dodging: bool = False
    round: int = 1
    outcome: str | None = None  # None while fighting, then "victory" or "defeat"


def initial_state(characters: dict) -> FightState:
    """Build the starting fight state from the `characters` section of config."""
    pc, boss = characters["pc"], characters["boss"]
    return FightState(
        pc=Combatant(pc["name"], pc["max_hp"], pc["max_hp"], pc["ac"]),
        boss=Combatant(boss["name"], boss["max_hp"], boss["max_hp"], boss["ac"]),
        cure_wounds_uses=pc["cure_wounds"]["uses"],
    )


def hp_band(hp: int, max_hp: int) -> str:
    """healthy above 50% of max HP, bloodied 26-50%, critical 1-25%, down at 0."""
    if hp <= 0:
        return "down"
    if hp * 2 > max_hp:
        return "healthy"
    if hp * 4 > max_hp:
        return "bloodied"
    return "critical"
