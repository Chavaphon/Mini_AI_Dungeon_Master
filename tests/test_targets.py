import pytest

from mini_dm.engine import Dice, initial_state, play_turn, validate_intent
from fakes import ScriptedDice, rules_config


def _state():
    return initial_state(rules_config()["characters"])


def _characters():
    return rules_config()["characters"]


def _turn(action, target, faces, state=None):
    state = state or _state()
    dice = ScriptedDice(faces)
    results = play_turn(state, dice, _characters(), action, target)
    return state, dice, results


# --- allow-list (GR-2) -------------------------------------------------------


@pytest.mark.parametrize(
    "action, target",
    [
        ("attack", "ashfang"),
        ("fire_bolt", "ashfang"),
        ("cure_wounds", "self"),
        # An allowed target on the wrong action is valid: it resolves against that combatant.
        ("attack", "self"),
        ("fire_bolt", "self"),
        ("cure_wounds", "ashfang"),
        # Dodge and none ignore their target.
        ("dodge", "self"),
        ("dodge", "ashfang"),
        ("dodge", "goblin"),
        ("none", ""),
        ("none", "the moon"),
    ],
)
def test_validate_intent_accepts_allowed_actions_and_targets(action, target):
    assert validate_intent(action, target) is None


def test_validate_intent_rejects_unknown_spell_naming_the_known_ones():
    reason = validate_intent("meteor_swarm", "ashfang")
    assert "meteor_swarm" in reason
    assert "Fire Bolt" in reason and "Cure Wounds" in reason


@pytest.mark.parametrize("target", ["goblin", "the drake", ""])
def test_validate_intent_rejects_targets_off_the_allow_list(target):
    reason = validate_intent("attack", target)
    assert "ashfang" in reason and "self" in reason


# --- attack and Fire Bolt aimed at self ---------------------------------------


def test_sword_aimed_at_self_hits_lyra_against_her_own_ac():
    # d20 10 + 5 = 15 vs Lyra's AC 14 hits, 1d6+3: 4 + 3 = 7. Ashfang misses on 2.
    state, dice, results = _turn("attack", "self", [10, 4, 2])

    sword, bite = results
    assert (sword.actor, sword.action, sword.target) == ("Lyra", "attack", "Lyra")
    assert (sword.target_ac, sword.damage, sword.target_hp_after) == (14, 7, 23)
    assert bite.action == "bite"
    assert (state.pc.hp, state.boss.hp, state.round) == (23, 30, 2)
    assert dice.remaining == 0


def test_fire_bolt_aimed_at_self_burns_lyra():
    state, dice, results = _turn("fire_bolt", "self", [9, 7, 2])  # 9 + 5 = 14 hits, d10 7

    assert (results[0].action, results[0].target, results[0].damage) == ("fire_bolt", "Lyra", 7)
    assert (state.pc.hp, state.boss.hp) == (23, 30)
    assert dice.remaining == 0


def test_natural_20_aimed_at_self_is_a_critical():
    state, _, results = _turn("attack", "self", [20, 4, 6, 2])  # 2d6+3: 4 + 6 + 3 = 13

    assert results[0].critical
    assert state.pc.hp == 17


def test_dropping_herself_to_0_is_defeat_and_the_boss_does_not_act():
    state = _state()
    state.pc.hp = 3
    state, dice, results = _turn("attack", "self", [15, 6], state)  # 6 + 3 = 9 damage

    assert len(results) == 1
    assert state.pc.hp == 0
    assert state.outcome == "defeat"
    assert state.round == 1
    assert dice.remaining == 0


# --- Cure Wounds aimed at Ashfang ---------------------------------------------


def test_cure_wounds_aimed_at_ashfang_heals_the_drake_and_spends_a_use():
    state = _state()
    state.boss.hp = 20
    state, dice, results = _turn("cure_wounds", "ashfang", [5, 2], state)  # heal 5 + 3 = 8

    heal, bite = results
    assert (heal.actor, heal.target, heal.success, heal.healing) == ("Lyra", "Ashfang", True, 8)
    assert (heal.target_hp_before, heal.target_hp_after, heal.target_max_hp) == (20, 28, 30)
    assert heal.uses_left == 1
    assert bite.action == "bite"
    assert (state.boss.hp, state.pc.hp, state.cure_wounds_uses, state.round) == (28, 30, 1, 2)
    assert dice.remaining == 0


def test_healing_ashfang_is_capped_at_its_max_hp():
    state = _state()
    state.boss.hp = 28
    state, _, results = _turn("cure_wounds", "ashfang", [5, 2], state)

    assert results[0].healing == 2
    assert state.boss.hp == 30


def test_cure_wounds_aimed_at_ashfang_with_no_uses_fails():
    state = _state()
    state.boss.hp = 20
    state.cure_wounds_uses = 0
    state, dice, results = _turn("cure_wounds", "ashfang", [2], state)

    assert results[0].success is False
    assert (results[0].target, results[0].healing) == ("Ashfang", 0)
    assert state.boss.hp == 20
    assert dice.remaining == 0


def test_healing_ashfang_above_half_hp_holds_off_fire_breath():
    state = _state()
    state.boss.hp = 14  # at or below 50%: Fire Breath would trigger
    state, _, results = _turn("cure_wounds", "ashfang", [5, 2], state)  # back up to 22

    assert results[1].action == "bite"
    assert not state.fire_breath_used


# --- dodge ignores its target -------------------------------------------------


@pytest.mark.parametrize("target", ["ashfang", "goblin"])
def test_dodge_always_applies_to_lyra(target):
    # Ashfang rolls 2d20 15, 8 and uses 8: 8 + 5 = 13 misses.
    state, dice, results = _turn("dodge", target, [15, 8])

    dodge, bite = results
    assert dodge.narration_facts() == {"actor": "Lyra", "action": "dodge", "target": "Lyra"}
    assert bite.disadvantage
    assert state.pc_dodging
    assert dice.remaining == 0


def test_none_ignores_its_target():
    _, _, results = _turn("none", "ashfang", [2])
    assert results[0].narration_facts() == {"actor": "Lyra", "action": "none", "target": ""}


# --- reproducibility ---------------------------------------------------------


def test_same_seed_and_targets_give_same_state():
    def run():
        state = _state()
        dice = Dice(seed=42)
        turns = [
            ("attack", "self"),
            ("cure_wounds", "ashfang"),
            ("fire_bolt", "ashfang"),
            ("dodge", "ashfang"),
            ("cure_wounds", "self"),
        ]
        for action, target in turns:
            if state.outcome:
                break
            play_turn(state, dice, _characters(), action, target)
        return state

    assert run() == run()
