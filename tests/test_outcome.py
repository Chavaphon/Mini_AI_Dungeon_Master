import copy

import pytest

from fakes import ScriptedDice
from mini_dm.config import load_config
from mini_dm.engine import initial_state, play_turn


def _characters():
    return load_config()["characters"]


def _state():
    return initial_state(_characters())


def test_fire_bolt_dropping_the_boss_is_victory_and_boss_does_not_act():
    state = _state()
    state.boss.hp = 5
    dice = ScriptedDice([12, 6])  # 12 + 5 = 17 hits, d10 6

    results = play_turn(state, dice, _characters(), "fire_bolt")

    assert [r.actor for r in results] == ["Lyra"]
    assert (state.boss.hp, state.outcome) == (0, "victory")
    assert dice.remaining == 0


def test_fire_breath_dropping_the_pc_is_defeat():
    state = _state()
    state.boss.hp = 15  # at the trigger, so Ashfang breathes fire
    state.pc.hp = 4
    # Lyra misses on 2. Fire Breath: d20 15 + 5 = 20 hits, 2d6 3 + 4 = 7.
    play_turn(state, ScriptedDice([2, 15, 3, 4]), _characters(), "attack")

    assert (state.pc.hp, state.outcome) == (0, "defeat")


@pytest.mark.parametrize("outcome", ["victory", "defeat"])
def test_play_turn_after_the_fight_ends_changes_nothing(outcome):
    state = _state()
    state.outcome = outcome
    state.pc_dodging = True
    before = copy.deepcopy(state)
    dice = ScriptedDice([10, 4, 12, 5])

    with pytest.raises(ValueError):
        play_turn(state, dice, _characters(), "attack")

    assert state == before
    assert dice.remaining == 4
