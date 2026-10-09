import gradio as gr

from mini_dm.app import OPENING_SCENE, build_ui, render_status
from mini_dm.config import load_config
from mini_dm.engine import initial_state


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
    demo = build_ui(load_config())

    assert isinstance(demo, gr.Blocks)
    [chatbot] = _components(demo, gr.Chatbot)
    assert OPENING_SCENE in str(chatbot.value)
    [status] = _components(demo, gr.HTML)
    assert "30/30" in status.value
