import json

import gradio as gr
import pytest

from fakes import FakeLLM, ScriptedDice
from mini_dm.app import (
    NOT_YET_TEXT,
    OPENING_SCENE,
    build_ui,
    format_rolls,
    new_session,
    play,
    render_status,
    submit_turn,
)
from mini_dm.config import load_config
from mini_dm.engine import Dice, initial_state, play_turn


def _components(demo, kind):
    return [block for block in demo.blocks.values() if isinstance(block, kind)]


def test_render_status_shows_initial_state():
    status = render_status(initial_state(load_config()["characters"]))

    assert "Lyra" in status and "Ashfang" in status
    assert status.count("30/30") == 2
    assert status.count("healthy") == 2
    assert "Cure Wounds: 2" in status
    assert "Round: 1" in status
    assert "Dodging: No" in status


def test_render_status_reflects_changes():
    state = initial_state(load_config()["characters"])
    state.pc.hp = 7
    state.cure_wounds_uses = 0
    state.round = 4
    state.pc_dodging = True

    status = render_status(state)

    assert "7/30" in status and "critical" in status
    assert "Cure Wounds: 0" in status
    assert "Round: 4" in status
    assert "Dodging: Yes" in status


def test_build_ui_opens_with_opening_scene_and_status_panel():
    demo = build_ui(load_config(), client=FakeLLM([]))

    assert isinstance(demo, gr.Blocks)
    [chatbot] = _components(demo, gr.Chatbot)
    assert OPENING_SCENE in str(chatbot.value)
    [status] = _components(demo, gr.HTML)
    assert "30/30" in status.value


# --- turn wiring (fake LLM, scripted dice) ------------------------------------

ATTACK = '{"action": "attack", "target": "ashfang"}'
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


def _session(faces):
    config = load_config()
    session = new_session(config)
    session["dice"] = ScriptedDice(faces)
    return config, session


def test_new_session_has_initial_state_and_seeded_dice():
    config = load_config()
    session = new_session(config)
    assert session["state"] == initial_state(config["characters"])
    assert session["dice"].roll("1d20") == Dice(config["seed"]).roll("1d20")


def test_attack_turn_makes_exactly_two_llm_calls():
    config, session = _session([10, 4, 12, 5])
    llm = FakeLLM([ATTACK, "Your blade bites; Ashfang bites back."])

    reply = play("I swing my sword at the drake", session, llm, config)

    assert reply.startswith("Your blade bites; Ashfang bites back.\n\n🎲 Lyra")
    intent_call, narration_call = llm.calls
    assert intent_call["temperature"] == 0 and intent_call["json_mode"] is True
    assert narration_call["temperature"] == 0.7 and narration_call["json_mode"] is False
    assert session["state"].boss.hp == 23
    assert session["state"].pc.hp == 23
    assert session["state"].round == 2


def test_narration_gets_both_actions_as_facts_only():
    config, session = _session([10, 4, 12, 5])
    llm = FakeLLM([ATTACK, "Narration."])

    play("I swing my sword at the drake", session, llm, config)

    facts = json.loads(llm.calls[1]["messages"][-1]["content"])
    assert list(facts) == ["actions"]
    lyra, ashfang = facts["actions"]
    assert set(lyra) == set(ashfang) == FACT_KEYS
    assert (lyra["actor"], lyra["action"], lyra["damage"]) == ("Lyra", "attack", 7)
    assert (ashfang["actor"], ashfang["action"], ashfang["damage"]) == ("Ashfang", "bite", 7)


@pytest.mark.parametrize(
    "intent_reply",
    ['{"action": "fire_bolt", "target": "ashfang"}', '{"action": "none", "target": ""}', "not json"],
)
def test_other_intents_get_stub_and_turn_does_not_advance(intent_reply):
    config, session = _session([])
    llm = FakeLLM([intent_reply])

    reply = play("I cast Fire Bolt", session, llm, config)

    assert reply == NOT_YET_TEXT
    assert len(llm.calls) == 1
    assert session["state"] == initial_state(config["characters"])


def test_submit_turn_updates_chat_and_status():
    config, session = _session([10, 4, 12, 5])
    llm = FakeLLM([ATTACK, "Steel meets scale."])
    history = [{"role": "assistant", "content": OPENING_SCENE}]

    textbox, history, status = submit_turn("I attack", history, session, llm, config)

    assert textbox == ""
    assert history[-2] == {"role": "user", "content": "I attack"}
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"].startswith("Steel meets scale.\n\n🎲 Lyra")
    assert "23/30" in status and "Round: 2" in status


def test_submit_turn_ignores_blank_input():
    config, session = _session([])
    llm = FakeLLM([])
    history = [{"role": "assistant", "content": OPENING_SCENE}]

    _, new_history, _ = submit_turn("   ", history, session, llm, config)

    assert new_history == history
    assert llm.calls == []


def test_build_ui_input_is_enabled():
    demo = build_ui(load_config(), client=FakeLLM([]))
    [textbox] = _components(demo, gr.Textbox)
    assert textbox.interactive is True


# --- roll display (FR-13) -----------------------------------------------------


def _turn(faces, boss_hp=30):
    config, session = _session(faces)
    session["state"].boss.hp = boss_hp
    return play_turn(session["state"], session["dice"], config["characters"], "attack")


def test_roll_lines_for_miss_and_hit():
    # Lyra misses (8 + 5 = 13 < 14); Ashfang hits (15 + 5 = 20), bite 5 + 2 = 7.
    assert format_rolls(_turn([8, 15, 5])) == (
        "🎲 Lyra, sword: d20 8 + 5 = 13 vs AC 14 → miss\n"
        "🎲 Ashfang, bite: d20 15 + 5 = 20 vs AC 14 → hit, 1d8+2: 5 + 2 = 7 damage"
    )


def test_roll_line_for_natural_20_shows_doubled_dice():
    lines = format_rolls(_turn([20, 4, 6, 2])).splitlines()  # crit 4 + 6 + 3; boss misses on 2
    assert lines[0] == (
        "🎲 Lyra, sword: d20 20 (natural 20) vs AC 14 → critical hit, 2d6+3: 4 + 6 + 3 = 13 damage"
    )


def test_roll_line_for_natural_1():
    lines = format_rolls(_turn([1, 2])).splitlines()
    assert lines[0] == "🎲 Lyra, sword: d20 1 (natural 1) vs AC 14 → miss"


def test_roll_lines_on_victory_turn_show_only_lyra():
    lines = format_rolls(_turn([15, 6], boss_hp=3)).splitlines()
    assert lines == ["🎲 Lyra, sword: d20 15 + 5 = 20 vs AC 14 → hit, 1d6+3: 6 + 3 = 9 damage"]


def test_play_appends_rolls_after_narration_and_keeps_them_from_the_model():
    config, session = _session([8, 15, 5])
    llm = FakeLLM([ATTACK, "Narration."])

    reply = play("I attack", session, llm, config)

    narration, rolls = reply.split("\n\n")
    assert narration == "Narration."
    assert rolls.startswith("🎲 Lyra, sword: d20 8 + 5 = 13")
    sent = llm.calls[1]["messages"][-1]["content"]
    assert "🎲" not in sent and "d20" not in sent


def test_stub_reply_has_no_rolls():
    config, session = _session([])
    reply = play("I cast Fire Bolt", session, FakeLLM(['{"action": "fire_bolt", "target": "ashfang"}']), config)
    assert "🎲" not in reply
