"""Gradio chat UI and status panel. Run from the repo root: python -m mini_dm.app"""

import html

import gradio as gr

from mini_dm.config import load_config
from mini_dm.engine import (
    ActionResult,
    Combatant,
    Dice,
    FightState,
    Roll,
    hp_band,
    initial_state,
    play_turn,
)
from mini_dm.llm import client_from_config, request_intent, request_narration

OPENING_SCENE = (
    "Wind howls through the broken crown of the old watchtower. Charred beams and "
    "fallen stone litter the floor of Ashfang's lair, and the air tastes of smoke. "
    "The young ember drake uncoils from its nest of ash, eyes glowing like coals, "
    "and fixes its gaze on you, Lyra. What do you do?"
)

# Placeholder until the other actions land: only the sword works in this build.
NOT_YET_TEXT = (
    "Your hand tightens on the hilt of your short sword. For now, steel is your "
    "only answer. Strike at Ashfang!"
)

_ACTION_LABELS = {"attack": "sword", "bite": "bite"}

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


def _damage_text(roll: Roll) -> str:
    if len(roll.rolls) == 1 and not roll.modifier:
        return f"{roll.notation}: {roll.total} damage"
    expression = " + ".join(str(face) for face in roll.rolls)
    if roll.modifier:
        expression += f" {'+' if roll.modifier > 0 else '-'} {abs(roll.modifier)}"
    return f"{roll.notation}: {expression} = {roll.total} damage"


def _roll_line(result: ActionResult) -> str:
    natural = result.attack_roll.rolls[0]
    if natural in (1, 20):
        attack = f"d20 {natural} (natural {natural})"
    else:
        attack = f"d20 {natural} + {result.bonus} = {natural + result.bonus}"
    outcome = "critical hit" if result.critical else "hit" if result.hit else "miss"
    if result.damage_roll:
        outcome += f", {_damage_text(result.damage_roll)}"
    label = _ACTION_LABELS.get(result.action, result.action.replace("_", " "))
    return f"🎲 {result.actor}, {label}: {attack} vs AC {result.target_ac} → {outcome}"


def format_rolls(results: list[ActionResult]) -> str:
    """Code-built roll lines shown under the narration (FR-13). Never sent to the model."""
    return "\n".join(_roll_line(result) for result in results)


def new_session(config: dict) -> dict:
    """Fresh fight state plus the single seeded dice roller for this session."""
    return {"state": initial_state(config["characters"]), "dice": Dice(config["seed"])}


def play(text: str, session: dict, client, config: dict) -> str:
    """One turn: intent call -> engine (PC then boss) -> one narration call."""
    _raw, intent = request_intent(client, config, text)
    if intent is None or intent["action"] != "attack":
        return NOT_YET_TEXT

    results = play_turn(session["state"], session["dice"], config["characters"], "attack")
    facts = {"actions": [result.narration_facts() for result in results]}
    return f"{request_narration(client, config, facts)}\n\n{format_rolls(results)}"


def submit_turn(text: str, history: list, session: dict, client, config: dict):
    """Gradio submit handler: returns (cleared textbox, chat history, status HTML)."""
    if not text.strip():
        return text, history, render_status(session["state"])
    reply = play(text, session, client, config)
    history = history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply},
    ]
    return "", history, render_status(session["state"])


def build_ui(config: dict, client=None) -> gr.Blocks:
    client = client or client_from_config(config)
    initial = new_session(config)

    with gr.Blocks(title="Mini AI Dungeon Master") as demo:
        session = gr.State(initial)
        gr.Markdown("# Mini AI Dungeon Master: Lyra vs. Ashfang")
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[{"role": "assistant", "content": OPENING_SCENE}],
                    label="The fight",
                    height=420,
                )
                textbox = gr.Textbox(
                    placeholder="What do you do?",
                    show_label=False,
                    interactive=True,
                )
            with gr.Column(scale=1):
                status = gr.HTML(render_status(initial["state"]), label="Status")

        def on_submit(text, history, session_value):
            return (*submit_turn(text, history, session_value, client, config), session_value)

        textbox.submit(
            on_submit,
            inputs=[textbox, chatbot, session],
            outputs=[textbox, chatbot, status, session],
        )
    return demo


def main() -> None:
    config = load_config()
    client = client_from_config(config)
    print("Loading the model...", flush=True)
    if not client.warm_up(config["ollama"]["warmup_timeout_s"]):
        print("Warning: the model did not load. Is Ollama running?", flush=True)
    build_ui(config, client).launch(server_name="127.0.0.1")


if __name__ == "__main__":
    main()
