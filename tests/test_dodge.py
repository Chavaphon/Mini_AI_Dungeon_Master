from mini_dm.config import load_config
from mini_dm.engine import Combatant, Dice, initial_state, play_turn, resolve_attack, resolve_dodge
from fakes import ScriptedDice


def _state():
    return initial_state(load_config()["characters"])


def _characters():
    return load_config()["characters"]


def _dodge_turn(faces):
    state = _state()
    dice = ScriptedDice(faces)
    results = play_turn(state, dice, _characters(), "dodge")
    return state, dice, results


# --- disadvantage --------------------------------------------------------------


def test_dodge_turn_sets_dodging_and_bite_uses_lower_d20():
    state, dice, results = _dodge_turn([15, 8])  # lower 8 + 5 = 13 < 14

    dodge, bite = results
    assert (dodge.actor, dodge.action, dodge.target) == ("Lyra", "dodge", "Lyra")
    assert state.pc_dodging
    assert bite.disadvantage
    assert bite.attack_roll.rolls == (15, 8)
    assert bite.natural == 8
    assert not bite.hit
    assert state.pc.hp == 30
    assert state.round == 2
    assert dice.remaining == 0


def test_bite_with_disadvantage_hits_when_lower_die_meets_ac():
    state, dice, results = _dodge_turn([18, 12, 5])  # lower 12 + 5 = 17, bite 5 + 2 = 7

    bite = results[1]
    assert bite.hit and bite.natural == 12
    assert state.pc.hp == 23
    assert dice.remaining == 0


def test_natural_20_on_the_dropped_die_does_not_crit():
    _, _, results = _dodge_turn([20, 3])  # 3 + 5 = 8 misses

    bite = results[1]
    assert bite.natural == 3
    assert not bite.hit and not bite.critical


def test_natural_1_on_the_used_die_misses():
    state = _state()
    state.pc.ac = 5  # 1 + 5 = 6 would hit without the natural 1 rule
    play_turn(state, ScriptedDice([1, 15]), _characters(), "dodge")

    assert state.pc.hp == 30


def test_double_natural_20_with_disadvantage_crits():
    state, dice, results = _dodge_turn([20, 20, 3, 4])  # crit: 3 + 4 + 2 = 9

    bite = results[1]
    assert bite.natural == 20
    assert bite.hit and bite.critical
    assert bite.damage_roll.notation == "2d8+2"
    assert state.pc.hp == 21
    assert dice.remaining == 0


def test_resolve_attack_records_disadvantage_and_natural():
    ashfang, lyra = Combatant("Ashfang", 30, 30, 14), Combatant("Lyra", 30, 30, 14)
    dice = ScriptedDice([9, 16, 4])
    result = resolve_attack(dice, ashfang, lyra, "bite", 5, "1d8+2", disadvantage=True)

    assert result.disadvantage
    assert result.attack_roll.rolls == (9, 16)
    assert result.natural == 9
    assert result.hit  # 9 + 5 = 14
    assert lyra.hp == 24


def test_attack_without_disadvantage_rolls_one_d20():
    lyra, ashfang = Combatant("Lyra", 30, 30, 14), Combatant("Ashfang", 30, 30, 14)
    result = resolve_attack(ScriptedDice([12, 3]), lyra, ashfang, "attack", 5, "1d6+3")

    assert not result.disadvantage
    assert result.attack_roll.rolls == (12,)
    assert result.natural == 12


# --- expiry ------------------------------------------------------------------


def test_dodge_expires_at_start_of_pcs_next_turn():
    state = _state()
    dice = ScriptedDice([2, 2, 2, 2])  # dodge turn: bite 2d20; attack turn: miss, bite 1d20

    play_turn(state, dice, _characters(), "dodge")
    assert state.pc_dodging

    results = play_turn(state, dice, _characters(), "attack")
    bite = results[1]
    assert not state.pc_dodging
    assert not bite.disadvantage
    assert bite.attack_roll.rolls == (2,)
    assert dice.remaining == 0


def test_dodging_twice_keeps_disadvantage_on_both_bites():
    state = _state()
    dice = ScriptedDice([3, 2, 4, 2])

    first = play_turn(state, dice, _characters(), "dodge")[1]
    second = play_turn(state, dice, _characters(), "dodge")[1]

    assert first.disadvantage and second.disadvantage
    assert state.pc_dodging
    assert dice.remaining == 0


def test_resolve_dodge_sets_dodging():
    state = _state()
    result = resolve_dodge(state)

    assert state.pc_dodging
    assert (result.actor, result.action, result.target) == ("Lyra", "dodge", "Lyra")


# --- narration facts ---------------------------------------------------------


def test_dodge_turn_narration_facts():
    _, _, results = _dodge_turn([15, 8])

    dodge, bite = (result.narration_facts() for result in results)
    assert dodge == {"actor": "Lyra", "action": "dodge", "target": "Lyra"}
    assert bite["disadvantage"] is True
    assert "natural" not in bite


# --- reproducibility ---------------------------------------------------------


def test_same_seed_and_actions_give_same_state_with_dodges():
    def run():
        state = _state()
        dice = Dice(seed=42)
        for action in ("dodge", "attack", "dodge", "fire_bolt", "cure_wounds", "dodge"):
            if state.outcome:
                break
            play_turn(state, dice, _characters(), action)
        return state

    assert run() == run()
