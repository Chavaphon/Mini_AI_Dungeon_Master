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


def roll_damage(dice: Dice, notation: str, critical: bool) -> Roll:
    """Roll damage. A critical rolls the damage dice twice and adds the modifier once."""
    if not critical:
        return dice.roll(notation)
    spec = parse_dice(notation)
    modifier = f"{spec.modifier:+d}" if spec.modifier else ""
    return dice.roll(f"{spec.count * 2}d{spec.sides}{modifier}")


def apply_damage(target: Combatant, amount: int) -> None:
    """Change HP by -amount, clamped to [0, max]."""
    target.hp = max(0, min(target.max_hp, target.hp - amount))


@dataclass(frozen=True)
class ActionResult:
    actor: str
    action: str
    target: str
    hit: bool
    critical: bool
    damage: int
    target_hp_before: int
    target_hp_after: int
    target_max_hp: int
    target_hp_band: str
    bonus: int
    target_ac: int
    attack_roll: Roll
    damage_roll: Roll | None

    def narration_facts(self) -> dict:
        """The FR-7 facts for narration. Dice rolls, bonus and AC stay out of it."""
        return {
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "hit": self.hit,
            "critical": self.critical,
            "damage": self.damage,
            "target_hp_before": self.target_hp_before,
            "target_hp_after": self.target_hp_after,
            "target_max_hp": self.target_max_hp,
            "target_hp_band": self.target_hp_band,
        }


def resolve_attack(
    dice: Dice, attacker: Combatant, target: Combatant, action: str, bonus: int, damage: str
) -> ActionResult:
    """d20 + bonus >= AC hits. A natural 20 always hits and crits; a natural 1 always misses."""
    attack_roll = dice.roll("1d20")
    natural = attack_roll.rolls[0]
    critical = natural == 20
    hit = critical or (natural != 1 and natural + bonus >= target.ac)

    hp_before = target.hp
    damage_roll = roll_damage(dice, damage, critical) if hit else None
    if damage_roll:
        apply_damage(target, damage_roll.total)

    return ActionResult(
        actor=attacker.name,
        action=action,
        target=target.name,
        hit=hit,
        critical=critical,
        damage=damage_roll.total if damage_roll else 0,
        target_hp_before=hp_before,
        target_hp_after=target.hp,
        target_max_hp=target.max_hp,
        target_hp_band=hp_band(target.hp, target.max_hp),
        bonus=bonus,
        target_ac=target.ac,
        attack_roll=attack_roll,
        damage_roll=damage_roll,
    )


def choose_boss_action(state: FightState) -> str:
    """Boss policy, code only. Fire Breath arrives in a later slice; for now, Bite."""
    return "bite"


def play_turn(state: FightState, dice: Dice, characters: dict, action: str) -> list[ActionResult]:
    """PC acts, then the boss acts unless the fight has ended. The round advances after the boss."""
    if action != "attack":
        raise ValueError(f"Action not supported yet: {action!r}")

    sword = characters["pc"]["attack"]
    results = [resolve_attack(dice, state.pc, state.boss, "attack", sword["bonus"], sword["damage"])]
    if state.boss.hp == 0:
        state.outcome = "victory"
        return results

    boss_action = choose_boss_action(state)
    bite = characters["boss"][boss_action]
    results.append(
        resolve_attack(dice, state.boss, state.pc, boss_action, bite["bonus"], bite["damage"])
    )
    if state.pc.hp == 0:
        state.outcome = "defeat"
    state.round += 1
    return results
