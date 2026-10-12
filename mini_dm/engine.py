"""Rules engine: state, dice, rules and boss policy.

The engine owns all game state and has no LLM dependency. Every die roll
comes from the single seeded random.Random instance held by Dice.
"""

import copy
import random
import re
from dataclasses import dataclass, fields

_DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")

# PC actions resolved as attack rolls against Ashfang (config key = action name).
PC_ATTACKS = ("attack", "fire_bolt")
# Every PC action the engine can resolve in this build.
PC_ACTIONS = PC_ATTACKS + ("cure_wounds", "dodge", "none")
# The target allow-list (GR-2) and the correct target per action. Dodge and none ignore targets.
TARGETS = ("ashfang", "self")
CORRECT_TARGET = {"attack": "ashfang", "fire_bolt": "ashfang", "cure_wounds": "self"}


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

    def getstate(self):
        return self._rng.getstate()

    def setstate(self, state) -> None:
        self._rng.setstate(state)


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


@dataclass(frozen=True)
class TurnSnapshot:
    state: FightState
    dice_state: object


def snapshot(state: FightState, dice: Dice) -> TurnSnapshot:
    """Save the fight state and dice position, so a turn can be undone if narration fails."""
    return TurnSnapshot(copy.deepcopy(state), dice.getstate())


def restore(state: FightState, dice: Dice, saved: TurnSnapshot) -> None:
    """Put `state` (in place) and the dice back to how they were when `saved` was taken."""
    saved_state = copy.deepcopy(saved.state)
    for field in fields(FightState):
        setattr(state, field.name, getattr(saved_state, field.name))
    dice.setstate(saved.dice_state)


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
    disadvantage: bool
    damage: int
    target_hp_before: int
    target_hp_after: int
    target_max_hp: int
    target_hp_band: str
    bonus: int
    target_ac: int
    natural: int  # the d20 face used: the lower of the two under disadvantage
    attack_roll: Roll  # 1d20, or 2d20 under disadvantage (its total is not used)
    damage_roll: Roll | None

    def narration_facts(self) -> dict:
        """The FR-7 facts for narration. Dice rolls, bonus and AC stay out of it."""
        return {
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "hit": self.hit,
            "critical": self.critical,
            "disadvantage": self.disadvantage,
            "damage": self.damage,
            "target_hp_before": self.target_hp_before,
            "target_hp_after": self.target_hp_after,
            "target_max_hp": self.target_max_hp,
            "target_hp_band": self.target_hp_band,
        }


def resolve_attack(
    dice: Dice,
    attacker: Combatant,
    target: Combatant,
    action: str,
    bonus: int,
    damage: str,
    disadvantage: bool = False,
) -> ActionResult:
    """d20 + bonus >= AC hits. A natural 20 always hits and crits; a natural 1 always misses.

    With disadvantage, roll 2d20 and use the lower; the natural 20/1 rules read that die.
    """
    attack_roll = dice.roll("2d20" if disadvantage else "1d20")
    natural = min(attack_roll.rolls)
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
        disadvantage=disadvantage,
        damage=damage_roll.total if damage_roll else 0,
        target_hp_before=hp_before,
        target_hp_after=target.hp,
        target_max_hp=target.max_hp,
        target_hp_band=hp_band(target.hp, target.max_hp),
        bonus=bonus,
        target_ac=target.ac,
        natural=natural,
        attack_roll=attack_roll,
        damage_roll=damage_roll,
    )


@dataclass(frozen=True)
class HealResult:
    actor: str
    action: str
    target: str
    success: bool
    healing: int  # HP actually restored, after the max HP cap
    target_hp_before: int
    target_hp_after: int
    target_max_hp: int
    target_hp_band: str
    uses_left: int
    heal_roll: Roll | None

    def narration_facts(self) -> dict:
        """The FR-7 facts for a Cure Wounds cast. The heal roll stays out of it."""
        return {
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "success": self.success,
            "healing": self.healing,
            "target_hp_before": self.target_hp_before,
            "target_hp_after": self.target_hp_after,
            "target_max_hp": self.target_max_hp,
            "target_hp_band": self.target_hp_band,
            "uses_left": self.uses_left,
        }


def resolve_cure_wounds(
    dice: Dice, state: FightState, heal: str, target: Combatant | None = None
) -> HealResult:
    """Spend one use and heal the target (the PC by default), capped at max HP.

    With no uses left the cast fails.
    """
    target = target or state.pc
    hp_before = target.hp
    heal_roll = None
    if state.cure_wounds_uses > 0:
        state.cure_wounds_uses -= 1
        heal_roll = dice.roll(heal)
        apply_damage(target, -heal_roll.total)

    return HealResult(
        actor=state.pc.name,
        action="cure_wounds",
        target=target.name,
        success=heal_roll is not None,
        healing=target.hp - hp_before,
        target_hp_before=hp_before,
        target_hp_after=target.hp,
        target_max_hp=target.max_hp,
        target_hp_band=hp_band(target.hp, target.max_hp),
        uses_left=state.cure_wounds_uses,
        heal_roll=heal_roll,
    )


@dataclass(frozen=True)
class DodgeResult:
    actor: str
    action: str
    target: str

    def narration_facts(self) -> dict:
        """The FR-7 facts for a dodge: who acted, the action and the target."""
        return {"actor": self.actor, "action": self.action, "target": self.target}


def resolve_dodge(state: FightState) -> DodgeResult:
    """The PC dodges: attacks against her have disadvantage until her next turn starts."""
    state.pc_dodging = True
    return DodgeResult(actor=state.pc.name, action="dodge", target=state.pc.name)


@dataclass(frozen=True)
class NoActionResult:
    actor: str
    action: str
    target: str

    def narration_facts(self) -> dict:
        """The FR-7 facts for a `none` action: who acted, the action and the target."""
        return {"actor": self.actor, "action": self.action, "target": self.target}


def resolve_no_action(state: FightState) -> NoActionResult:
    """The PC talks, looks or taunts (FR-8): no roll and no change to state."""
    return NoActionResult(actor=state.pc.name, action="none", target="")


def choose_boss_action(state: FightState, trigger_hp_pct: int) -> str:
    """Boss policy, code only: Fire Breath once, when HP is at or below the trigger; else Bite."""
    if not state.fire_breath_used and state.boss.hp * 100 <= state.boss.max_hp * trigger_hp_pct:
        return "fire_breath"
    return "bite"


TurnResult = ActionResult | HealResult | DodgeResult | NoActionResult


def validate_intent(action: str, target: str) -> str | None:
    """Check a proposed action against the allow-list (GR-2). Returns the reason it is invalid.

    An allowed target on the wrong action is valid: it resolves against that combatant.
    """
    if action not in PC_ACTIONS:
        return (
            f"{action!r} is not one of Lyra's actions. Lyra knows only the spells Fire Bolt "
            f"and Cure Wounds. The actions are: {', '.join(PC_ACTIONS)}."
        )
    if action in CORRECT_TARGET and target not in TARGETS:
        return f"{target!r} is not a valid target. The targets are: {', '.join(TARGETS)}."
    return None


def _resolve_pc_action(
    state: FightState, dice: Dice, characters: dict, action: str, target: str | None
) -> TurnResult:
    if action == "none":
        return resolve_no_action(state)
    if action == "dodge":
        return resolve_dodge(state)
    if action not in CORRECT_TARGET:
        raise ValueError(f"Unknown action: {action!r}")
    # A wrong target is not refused: the action resolves against that combatant.
    combatant = state.pc if (target or CORRECT_TARGET[action]) == "self" else state.boss
    if action == "cure_wounds":
        return resolve_cure_wounds(dice, state, characters["pc"]["cure_wounds"]["heal"], combatant)
    # Sword and Fire Bolt share the attack rules; Fire Bolt has no uses to spend.
    pc_attack = characters["pc"][action]
    return resolve_attack(
        dice, state.pc, combatant, action, pc_attack["bonus"], pc_attack["damage"]
    )


def play_turn(
    state: FightState, dice: Dice, characters: dict, action: str, target: str | None = None
) -> list[TurnResult]:
    """PC acts, then the boss acts unless the fight has ended. The round advances after the boss.

    `target` is "ashfang" or "self"; None means the action's correct target.
    """
    if state.outcome:
        raise ValueError(f"The fight is over: {state.outcome}")
    state.pc_dodging = False  # a dodge ends at the start of the dodger's next turn
    results = [_resolve_pc_action(state, dice, characters, action, target)]
    if state.boss.hp == 0:
        state.outcome = "victory"
        return results
    if state.pc.hp == 0:  # Lyra struck herself down
        state.outcome = "defeat"
        return results

    boss = characters["boss"]
    boss_action = choose_boss_action(state, boss["fire_breath"]["trigger_hp_pct"])
    if boss_action == "fire_breath":
        state.fire_breath_used = True  # spent once chosen, hit or miss
    boss_attack = boss[boss_action]
    results.append(
        resolve_attack(
            dice,
            state.boss,
            state.pc,
            boss_action,
            boss_attack["bonus"],
            boss_attack["damage"],
            disadvantage=state.pc_dodging,
        )
    )
    if state.pc.hp == 0:
        state.outcome = "defeat"
    state.round += 1
    return results
