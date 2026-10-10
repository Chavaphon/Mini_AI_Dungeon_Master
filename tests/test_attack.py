import pytest

from mini_dm.config import load_config
from mini_dm.engine import (
    Combatant,
    Dice,
    apply_damage,
    choose_boss_action,
    initial_state,
    play_turn,
    resolve_attack,
    roll_damage,
)
from fakes import ScriptedDice

FACT_KEYS = {
    "actor",
    "action",
    "target",
    "hit",
    "critical",
    "damage",
    "target_hp_before",
    "target_hp_after",
    "target_max_hp",
    "target_hp_band",
}


def _pair():
    return Combatant("Lyra", 30, 30, 14), Combatant("Ashfang", 30, 30, 14)


def _state():
    return initial_state(load_config()["characters"])


def _characters():
    return load_config()["characters"]


# --- attack roll -----------------------------------------------------------


def test_hit_when_total_meets_ac():
    lyra, ashfang = _pair()
    result = resolve_attack(ScriptedDice([9, 4]), lyra, ashfang, "attack", 5, "1d6+3")

    assert result.hit and not result.critical
    assert result.damage == 7
    assert (result.target_hp_before, result.target_hp_after) == (30, 23)
    assert ashfang.hp == 23


def test_miss_when_total_below_ac():
    lyra, ashfang = _pair()
    dice = ScriptedDice([8])
    result = resolve_attack(dice, lyra, ashfang, "attack", 5, "1d6+3")

    assert not result.hit and not result.critical
    assert result.damage == 0
    assert result.damage_roll is None
    assert ashfang.hp == 30
    assert dice.remaining == 0  # no damage dice rolled on a miss


def test_natural_20_always_hits_and_crits():
    lyra, ashfang = _pair()
    ashfang.ac = 30  # 20 + 5 = 25 would miss without the natural 20 rule
    result = resolve_attack(ScriptedDice([20, 2, 5]), lyra, ashfang, "attack", 5, "1d6+3")

    assert result.hit and result.critical
    assert result.damage == 2 + 5 + 3


def test_natural_1_always_misses():
    lyra, ashfang = _pair()
    ashfang.ac = 5  # 1 + 5 = 6 would hit without the natural 1 rule
    result = resolve_attack(ScriptedDice([1]), lyra, ashfang, "attack", 5, "1d6+3")

    assert not result.hit and not result.critical
    assert ashfang.hp == 30


def test_attack_records_the_d20():
    lyra, ashfang = _pair()
    result = resolve_attack(ScriptedDice([12, 3]), lyra, ashfang, "attack", 5, "1d6+3")

    assert result.attack_roll.rolls == (12,)
    assert result.damage_roll.rolls == (3,)


# --- damage ------------------------------------------------------------------


def test_critical_damage_doubles_dice_not_modifier():
    roll = roll_damage(ScriptedDice([6, 6, 4, 1]), "2d6+3", critical=True)

    assert roll.rolls == (6, 6, 4, 1)
    assert roll.modifier == 3
    assert roll.total == 6 + 6 + 4 + 1 + 3


def test_normal_damage_rolls_dice_once():
    roll = roll_damage(ScriptedDice([5]), "1d8+2", critical=False)

    assert roll.rolls == (5,)
    assert roll.total == 7


def test_critical_damage_is_reproducible_with_seed():
    a = roll_damage(Dice(seed=7), "1d6+3", critical=True)
    b = roll_damage(Dice(seed=7), "1d6+3", critical=True)
    assert a == b and len(a.rolls) == 2


def test_hp_clamped_at_zero():
    target = Combatant("Ashfang", 30, 3, 14)
    apply_damage(target, 10)
    assert target.hp == 0


def test_hp_never_exceeds_max():
    target = Combatant("Ashfang", 30, 30, 14)
    apply_damage(target, -5)
    assert target.hp == 30


def test_overkill_attack_reports_clamped_hp():
    lyra, ashfang = _pair()
    ashfang.hp = 2
    result = resolve_attack(ScriptedDice([15, 6]), lyra, ashfang, "attack", 5, "1d6+3")

    assert result.damage == 9
    assert result.target_hp_after == 0
    assert result.target_hp_band == "down"


# --- narration facts ---------------------------------------------------------


def test_narration_facts_are_fr7_fields_only():
    lyra, ashfang = _pair()
    result = resolve_attack(ScriptedDice([20, 6, 6]), lyra, ashfang, "attack", 5, "1d6+3")

    facts = result.narration_facts()

    assert set(facts) == FACT_KEYS
    assert facts == {
        "actor": "Lyra",
        "action": "attack",
        "target": "Ashfang",
        "hit": True,
        "critical": True,
        "damage": 15,
        "target_hp_before": 30,
        "target_hp_after": 15,
        "target_max_hp": 30,
        "target_hp_band": "bloodied",
    }


# --- turn order and boss policy ----------------------------------------------


def test_boss_bites_in_this_slice():
    assert choose_boss_action(_state()) == "bite"


def test_turn_pc_attacks_then_boss_bites():
    state = _state()
    # Lyra: d20 10 hits (15 >= 14), d6 4 -> 7. Ashfang: d20 12 hits (17), d8 5 -> 7.
    results = play_turn(state, ScriptedDice([10, 4, 12, 5]), _characters(), "attack")

    assert [(r.actor, r.action, r.target) for r in results] == [
        ("Lyra", "attack", "Ashfang"),
        ("Ashfang", "bite", "Lyra"),
    ]
    assert state.boss.hp == 23
    assert state.pc.hp == 23


def test_round_advances_after_boss_acts():
    state = _state()
    play_turn(state, ScriptedDice([2, 3]), _characters(), "attack")  # both miss
    assert state.round == 2
    assert state.outcome is None


def test_boss_does_not_act_at_zero_hp_and_victory_is_set():
    state = _state()
    state.boss.hp = 3
    dice = ScriptedDice([15, 1])  # hit for 4
    results = play_turn(state, dice, _characters(), "attack")

    assert [r.actor for r in results] == ["Lyra"]
    assert state.boss.hp == 0
    assert state.outcome == "victory"
    assert state.round == 1
    assert dice.remaining == 0


def test_pc_at_zero_hp_is_defeat():
    state = _state()
    state.pc.hp = 2
    play_turn(state, ScriptedDice([2, 15, 3]), _characters(), "attack")  # miss, bite for 5

    assert state.pc.hp == 0
    assert state.outcome == "defeat"


def test_play_turn_rejects_unbuilt_actions():
    with pytest.raises(ValueError):
        play_turn(_state(), ScriptedDice([]), _characters(), "fire_bolt")


def test_same_seed_and_actions_give_same_state():
    def run():
        state = _state()
        dice = Dice(seed=42)
        for _ in range(5):
            if state.outcome:
                break
            play_turn(state, dice, _characters(), "attack")
        return state

    assert run() == run()


def test_result_records_bonus_and_ac_for_roll_display():
    lyra, ashfang = _pair()
    result = resolve_attack(ScriptedDice([8]), lyra, ashfang, "attack", 5, "1d6+3")

    assert (result.bonus, result.target_ac) == (5, 14)
    assert "bonus" not in result.narration_facts()
    assert "target_ac" not in result.narration_facts()
