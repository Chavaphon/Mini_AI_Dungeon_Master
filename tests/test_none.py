import dataclasses

from mini_dm.config import load_config
from mini_dm.engine import Dice, initial_state, play_turn, resolve_no_action
from fakes import ScriptedDice


def _state():
    return initial_state(load_config()["characters"])


def _characters():
    return load_config()["characters"]


def _none_turn(faces, state=None):
    state = state or _state()
    dice = ScriptedDice(faces)
    results = play_turn(state, dice, _characters(), "none")
    return state, dice, results


# --- no effect, boss still acts (FR-8) ------------------------------------------


def test_none_changes_no_pc_state_and_boss_bites():
    state, dice, results = _none_turn([2])  # bite misses on 2

    lyra, bite = results
    assert (lyra.actor, lyra.action, lyra.target) == ("Lyra", "none", "")
    assert (bite.actor, bite.action) == ("Ashfang", "bite")
    assert dataclasses.replace(state, round=1) == _state()
    assert state.round == 2
    assert dice.remaining == 0


def test_none_turn_boss_damage_is_the_only_hp_change():
    state, dice, _ = _none_turn([15, 5])  # 15 + 5 = 20 hits, bite 5 + 2 = 7

    assert state.pc.hp == 23
    assert state.boss.hp == 30
    assert state.cure_wounds_uses == _state().cure_wounds_uses
    assert dice.remaining == 0


def test_resolve_no_action_touches_nothing():
    state = _state()
    result = resolve_no_action(state)

    assert state == _state()
    assert (result.actor, result.action, result.target) == ("Lyra", "none", "")


def test_boss_uses_fire_breath_on_a_none_turn_at_half_hp():
    state = _state()
    state.boss.hp = 15
    state, dice, results = _none_turn([2], state)

    assert results[1].action == "fire_breath"
    assert state.fire_breath_used
    assert dice.remaining == 0


def test_none_ends_a_previous_dodge():
    state = _state()
    dice = ScriptedDice([2, 2, 2])  # dodge turn: bite 2d20; none turn: bite 1d20

    play_turn(state, dice, _characters(), "dodge")
    bite = play_turn(state, dice, _characters(), "none")[1]

    assert not state.pc_dodging
    assert not bite.disadvantage
    assert dice.remaining == 0


def test_boss_dropping_the_pc_on_a_none_turn_is_defeat():
    state = _state()
    state.pc.hp = 3
    state, _, results = _none_turn([15, 5], state)

    assert len(results) == 2
    assert state.pc.hp == 0
    assert state.outcome == "defeat"


# --- narration facts ---------------------------------------------------------


def test_none_narration_facts():
    _, _, results = _none_turn([2])
    assert results[0].narration_facts() == {"actor": "Lyra", "action": "none", "target": ""}


# --- reproducibility ---------------------------------------------------------


def test_same_seed_and_actions_give_same_state_with_none():
    def run():
        state = _state()
        dice = Dice(seed=42)
        for action in ("none", "attack", "none", "dodge", "none", "fire_bolt"):
            if state.outcome:
                break
            play_turn(state, dice, _characters(), action)
        return state

    assert run() == run()
