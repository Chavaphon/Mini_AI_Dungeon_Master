from mini_dm.config import load_config
from mini_dm.engine import Dice, choose_boss_action, initial_state, play_turn
from fakes import ScriptedDice


def _characters():
    return load_config()["characters"]


def _state(boss_hp=30):
    state = initial_state(_characters())
    state.boss.hp = boss_hp
    return state


def _trigger_pct():
    return _characters()["boss"]["fire_breath"]["trigger_hp_pct"]


# --- policy ------------------------------------------------------------------


def test_boss_bites_above_half_hp():
    assert choose_boss_action(_state(16), _trigger_pct()) == "bite"


def test_boss_breathes_at_half_hp():
    assert choose_boss_action(_state(15), _trigger_pct()) == "fire_breath"


def test_boss_breathes_below_half_hp():
    assert choose_boss_action(_state(5), _trigger_pct()) == "fire_breath"


def test_boss_bites_once_fire_breath_is_used():
    state = _state(5)
    state.fire_breath_used = True
    assert choose_boss_action(state, _trigger_pct()) == "bite"


def test_policy_reads_trigger_percentage():
    assert choose_boss_action(_state(13), 40) == "bite"
    assert choose_boss_action(_state(12), 40) == "fire_breath"


# --- turn --------------------------------------------------------------------


def test_fire_breath_on_same_round_pc_drops_boss_to_half():
    state = _state(20)
    # Lyra: d20 15 hits, d6 2 -> 5, boss 20 -> 15. Ashfang: d20 15 hits (20), 2d6 3 + 4 = 7.
    dice = ScriptedDice([15, 2, 15, 3, 4])
    results = play_turn(state, dice, _characters(), "attack")

    breath = results[1]
    assert (breath.actor, breath.action, breath.target) == ("Ashfang", "fire_breath", "Lyra")
    assert breath.hit and not breath.critical
    assert breath.damage_roll.notation == "2d6"
    assert breath.damage == 7
    assert state.pc.hp == 23
    assert state.fire_breath_used
    assert dice.remaining == 0


def test_fire_breath_when_boss_already_at_half_or_below():
    state = _state(10)
    dice = ScriptedDice([2, 12, 1, 1])  # Lyra misses; breath 12 + 5 = 17 hits for 2

    breath = play_turn(state, dice, _characters(), "attack")[1]
    assert breath.action == "fire_breath"
    assert state.pc.hp == 28
    assert dice.remaining == 0


def test_fire_breath_fires_exactly_once():
    state = _state(15)
    dice = ScriptedDice([2, 12, 3, 4, 2, 2])  # turn 1: miss, breath hits; turn 2: miss, bite misses

    first = play_turn(state, dice, _characters(), "attack")[1]
    second = play_turn(state, dice, _characters(), "attack")[1]

    assert first.action == "fire_breath"
    assert second.action == "bite"
    assert dice.remaining == 0


def test_missed_fire_breath_is_still_spent():
    state = _state(15)
    dice = ScriptedDice([2, 3, 2, 2])  # breath 3 + 5 = 8 misses; next turn bite misses

    first = play_turn(state, dice, _characters(), "attack")[1]
    assert first.action == "fire_breath" and not first.hit
    assert state.fire_breath_used

    second = play_turn(state, dice, _characters(), "attack")[1]
    assert second.action == "bite"


def test_fire_breath_misses_when_total_below_ac():
    state = _state(15)
    breath = play_turn(state, ScriptedDice([2, 8]), _characters(), "attack")[1]  # 8 + 5 = 13

    assert not breath.hit
    assert breath.damage == 0
    assert state.pc.hp == 30


def test_fire_breath_natural_1_misses():
    state = _state(15)
    state.pc.ac = 5  # 1 + 5 = 6 would hit without the natural 1 rule
    breath = play_turn(state, ScriptedDice([2, 1]), _characters(), "attack")[1]

    assert breath.natural == 1
    assert not breath.hit
    assert state.pc.hp == 30


def test_fire_breath_critical_doubles_2d6():
    state = _state(15)
    dice = ScriptedDice([2, 20, 1, 2, 3, 4])  # crit: 4d6 = 10
    breath = play_turn(state, dice, _characters(), "attack")[1]

    assert breath.hit and breath.critical
    assert breath.damage_roll.notation == "4d6"
    assert breath.damage == 10
    assert state.pc.hp == 20
    assert dice.remaining == 0


def test_dodge_gives_fire_breath_disadvantage():
    state = _state(15)
    dice = ScriptedDice([15, 8])  # lower 8 + 5 = 13 misses
    breath = play_turn(state, dice, _characters(), "dodge")[1]

    assert breath.action == "fire_breath"
    assert breath.disadvantage
    assert breath.attack_roll.rolls == (15, 8)
    assert breath.natural == 8
    assert not breath.hit
    assert state.fire_breath_used
    assert dice.remaining == 0


def test_no_fire_breath_on_victory_turn():
    state = _state(3)
    results = play_turn(state, ScriptedDice([15, 1]), _characters(), "attack")  # hit for 4

    assert [r.actor for r in results] == ["Lyra"]
    assert state.outcome == "victory"
    assert not state.fire_breath_used


# --- narration facts ---------------------------------------------------------


def test_fire_breath_narration_facts_identify_action():
    state = _state(20)
    breath = play_turn(state, ScriptedDice([15, 2, 15, 3, 4]), _characters(), "attack")[1]

    assert breath.narration_facts() == {
        "actor": "Ashfang",
        "action": "fire_breath",
        "target": "Lyra",
        "hit": True,
        "critical": False,
        "disadvantage": False,
        "damage": 7,
        "target_hp_before": 30,
        "target_hp_after": 23,
        "target_max_hp": 30,
        "target_hp_band": "healthy",
    }


# --- reproducibility ---------------------------------------------------------


def test_same_seed_and_actions_give_same_fight_through_fire_breath():
    def run():
        state = _state(16)
        dice = Dice(seed=42)
        boss_actions = []
        while not state.outcome:
            results = play_turn(state, dice, _characters(), "attack")
            boss_actions += [r.action for r in results if r.actor == "Ashfang"]
        return state, boss_actions

    state, boss_actions = run()
    assert (state, boss_actions) == run()
    assert boss_actions.count("fire_breath") == 1
