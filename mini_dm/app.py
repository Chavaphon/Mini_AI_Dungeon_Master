"""Gradio chat UI and status panel. Run from the repo root: python -m mini_dm.app"""

import html

import gradio as gr

from mini_dm.config import load_config
from mini_dm.engine import Combatant, FightState, hp_band, initial_state

OPENING_SCENE = (
    "Wind howls through the broken crown of the old watchtower. Charred beams and "
    "fallen stone litter the floor of Ashfang's lair, and the air tastes of smoke. "
    "The young ember drake uncoils from its nest of ash, eyes glowing like coals, "
    "and fixes its gaze on you, Lyra. What do you do?"
)

_BAND_COLOURS = {
    "healthy": "#3a9d5d",
    "bloodied": "#d9a227",
    "critical": "#c8372d",
    "down": "#6b6b6b",
}


def _hp_bar(combatant: Combatant) -> str:
    band = hp_band(combatant.hp, combatant.max_hp)
    percent = 100 * combatant.hp / combatant.max_hp
    return (
        f"<div><strong>{html.escape(combatant.name)}</strong> "
        f"{combatant.hp}/{combatant.max_hp} HP ({band})</div>"
        '<div style="background:#ddd;border-radius:4px;height:12px;margin:4px 0 10px">'
        f'<div style="background:{_BAND_COLOURS[band]};width:{percent:.0f}%;'
        'height:100%;border-radius:4px"></div></div>'
    )


def render_status(state: FightState) -> str:
    """Status panel HTML: HP bars, Cure Wounds uses, round and dodge state (FR-9)."""
    return (
        _hp_bar(state.pc)
        + _hp_bar(state.boss)
        + f"<div>Cure Wounds: {state.cure_wounds_uses}</div>"
        + f"<div>Round: {state.round}</div>"
        + f"<div>Dodging: {'Yes' if state.pc_dodging else 'No'}</div>"
    )


def build_ui(config: dict) -> gr.Blocks:
    state = initial_state(config["characters"])

    with gr.Blocks(title="Mini AI Dungeon Master") as demo:
        gr.Markdown("# Mini AI Dungeon Master: Lyra vs. Ashfang")
        with gr.Row():
            with gr.Column(scale=3):
                gr.Chatbot(
                    value=[{"role": "assistant", "content": OPENING_SCENE}],
                    label="The fight",
                    height=420,
                )
                gr.Textbox(
                    placeholder="Actions arrive in the next build.",
                    show_label=False,
                    interactive=False,
                )
            with gr.Column(scale=1):
                gr.HTML(render_status(state), label="Status")
    return demo


def main() -> None:
    build_ui(load_config()).launch(server_name="127.0.0.1")


if __name__ == "__main__":
    main()
