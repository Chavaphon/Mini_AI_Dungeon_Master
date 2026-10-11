from mini_dm.config import load_config
from mini_dm.engine import Dice, initial_state, play_turn, resolve_cure_wounds
from fakes import ScriptedDice

HEAL_FACT_KEYS = {
    "actor",
    "action",
    "target",
    "success",
    "healing",
    "target_hp_before",
    "target_hp_after",
    "target_max_hp",
    "target_hp_band",
    "uses_left",
}


def _state():
    return initial_state(load_config()["characters"])


def _characters():
    return load_config()["characters"]


# --- the heal ----------------------------------------------------------------


def test_heal_adds_the_roll():
    state = _state()
    state.pc.hp = 10
    result = resolve_cure_wounds(ScriptedDice([5]), state, "1d8+3")

    assert result.success
    assert result.healing == 8
    assert (result.target_hp_before, result.target_hp_after) == (10, 18)
    assert state.pc.hp == 18
    assert state.cure_wounds_uses == 1
    assert result.uses_left == 1


def test_heal_is_capped_at_max_hp():
    state = _state()
    state.pc.hp = 28
    result = resolve_cure_wounds(ScriptedDice([5]), state, "1d8+3")

    assert result.heal_roll.total == 8
    assert result.healing == 2
    assert result.target_hp_after == 30
    assert state.pc.hp == 30


def test_heal_at_full_hp_still_spends_a_use():
    state = _state()
    result = resolve_cure_wounds(ScriptedDice([4]), state, "1d8+3")

    assert result.success and result.healing == 0
    assert state.pc.hp == 30
    assert state.cure_wounds_uses == 1


def test_each_cast_spends_one_use():
    state = _state()
    dice = ScriptedDice([3, 2, 3, 2])  # heal, boss misses, heal, boss misses

    play_turn(state, dice, _characters(), "cure_wounds")
    assert state.cure_wounds_uses == 1
    play_turn(state, dice, _characters(), "cure_wounds")
    assert state.cure_wounds_uses == 0


# --- no uses left ------------------------------------------------------------


def test_cast_at_zero_uses_fails_turn_counts_and_boss_acts():
    state = _state()
    state.pc.hp = 20
    state.cure_wounds_uses = 0
    dice = ScriptedDice([15, 5])  # no heal dice; boss bites for 5 + 2 = 7

    results = play_turn(state, dice, _characters(), "cure_wounds")

    heal, bite = results
    assert (heal.actor, heal.action, heal.target) == ("Lyra", "cure_wounds", "Lyra")
    assert not heal.success
    assert heal.healing == 0
    assert heal.heal_roll is None
    assert (heal.target_hp_before, heal.target_hp_after) == (20, 20)
    assert heal.uses_left == 0
    assert (bite.actor, bite.action) == ("Ashfang", "bite")
    assert state.pc.hp == 13
    assert state.cure_wounds_uses == 0
    assert state.round == 2
    assert dice.remaining == 0


def test_turn_heal_then_boss_bites():
    state = _state()
    state.pc.hp = 10
    # Heal d8 5 -> 8. Ashfang: d20 12 hits (17), d8 5 -> 7.
    results = play_turn(state, ScriptedDice([5, 12, 5]), _characters(), "cure_wounds")

    assert [(r.actor, r.action) for r in results] == [("Lyra", "cure_wounds"), ("Ashfang", "bite")]
    assert results[0].target_hp_after == 18
    assert state.pc.hp == 11
    assert state.round == 2


# --- narration facts ---------------------------------------------------------


def test_heal_narration_facts():
    state = _state()
    state.pc.hp = 28
    facts = resolve_cure_wounds(ScriptedDice([5]), state, "1d8+3").narration_facts()

    assert set(facts) == HEAL_FACT_KEYS
    assert facts == {
        "actor": "Lyra",
        "action": "cure_wounds",
        "target": "Lyra",
        "success": True,
        "healing": 2,
        "target_hp_before": 28,
        "target_hp_after": 30,
        "target_max_hp": 30,
        "target_hp_band": "healthy",
        "uses_left": 1,
    }


def test_failed_heal_narration_facts():
    state = _state()
    state.pc.hp = 7
    state.cure_wounds_uses = 0
    facts = resolve_cure_wounds(ScriptedDice([]), state, "1d8+3").narration_facts()

    assert facts == {
        "actor": "Lyra",
        "action": "cure_wounds",
        "target": "Lyra",
        "success": False,
        "healing": 0,
        "target_hp_before": 7,
        "target_hp_after": 7,
        "target_max_hp": 30,
        "target_hp_band": "critical",
        "uses_left": 0,
    }


# --- reproducibility ---------------------------------------------------------


def test_same_seed_and_actions_give_same_state_with_heals():
    def run():
        state = _state()
        dice = Dice(seed=42)
        for action in ("attack", "cure_wounds", "fire_bolt", "cure_wounds", "cure_wounds"):
            if state.outcome:
                break
            play_turn(state, dice, _characters(), action)
        return state

    assert run() == run()
