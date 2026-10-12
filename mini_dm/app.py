"""Gradio chat UI and status panel. Run from the repo root: python -m mini_dm.app"""

import html

import gradio as gr

from mini_dm.config import load_config
from mini_dm.engine import (
    ActionResult,
    Combatant,
    Dice,
    DodgeResult,
    FightState,
    HealResult,
    NoActionResult,
    Roll,
    TurnResult,
    hp_band,
    initial_state,
    play_turn,
)
from mini_dm.llm import client_from_config, request_narration, resolve_intent

OPENING_SCENE = (
    "Wind howls through the broken crown of the old watchtower. Charred beams and "
    "fallen stone litter the floor of Ashfang's lair, and the air tastes of smoke. "
    "The young ember drake uncoils from its nest of ash, eyes glowing like coals, "
    "and fixes its gaze on you, Lyra. What do you do?"
)

# FR-4 refusals once the retry and the fallback parser have failed; the turn does not advance.
REPHRASE_TEXT = (
    "Ashfang's roar drowns out your thoughts for a moment. What do you do, Lyra? "
    "Strike with your sword, hurl a Fire Bolt, cast Cure Wounds, dodge, or say "
    "something to the drake."
)
# When the model proposed an action or spell that is not on the allow-list (GR-2).
SPELL_REFUSAL_TEXT = (
    "The words of an unfamiliar spell die on your lips. You know only Fire Bolt and "
    "Cure Wounds. What do you do, Lyra? Strike with your sword, hurl a Fire Bolt, "
    "cast Cure Wounds, dodge, or say something to the drake."
)

# Fixed reply once the fight has ended: no model call, no state change.
FIGHT_OVER_TEXT = (
    "The smoke settles over the ruined watchtower and the lair falls silent. "
    "This fight is over. Press Restart to face Ashfang again."
)

_ACTION_LABELS = {
    "attack": "sword",
    "fire_bolt": "Fire Bolt",
    "bite": "bite",
    "fire_breath": "Fire Breath",
}

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
    """Status panel HTML: HP bars, Cure Wounds uses, round, dodge state (FR-9) and outcome."""
    status = (
        _hp_bar(state.pc)
        + _hp_bar(state.boss)
        + f"<div>Cure Wounds: {state.cure_wounds_uses}</div>"
        + f"<div>Round: {state.round}</div>"
        + f"<div>Dodging: {'Yes' if state.pc_dodging else 'No'}</div>"
    )
    if state.outcome:
        status += f"<div><strong>Outcome: {state.outcome.capitalize()}</strong></div>"
    return status


def _dice_text(roll: Roll, unit: str) -> str:
    if len(roll.rolls) == 1 and not roll.modifier:
        return f"{roll.notation}: {roll.total} {unit}"
    expression = " + ".join(str(face) for face in roll.rolls)
    if roll.modifier:
        expression += f" {'+' if roll.modifier > 0 else '-'} {abs(roll.modifier)}"
    return f"{roll.notation}: {expression} = {roll.total} {unit}"


def _heal_label(result: HealResult) -> str:
    """Names the target only when it is the wrong one (FR-13)."""
    return "Cure Wounds" if result.target == result.actor else f"Cure Wounds on {result.target}"


def _heal_line(result: HealResult) -> str:
    if not result.heal_roll:
        return f"🎲 {result.actor}, {_heal_label(result)}: no uses left"
    text = _dice_text(result.heal_roll, "healing")
    if result.heal_roll.total > result.healing:
        text += f" (capped at {result.target_max_hp})"
    return f"🎲 {result.actor}, {_heal_label(result)}: {text}"


def _attack_text(result: ActionResult) -> str:
    natural = result.natural
    if result.disadvantage:
        faces = ", ".join(str(face) for face in result.attack_roll.rolls)
        prefix = f"2d20 {faces} (disadvantage) → "
        if natural in (1, 20):
            return f"{prefix}natural {natural}"
        return f"{prefix}{natural} + {result.bonus} = {natural + result.bonus}"
    if natural in (1, 20):
        return f"d20 {natural} (natural {natural})"
    return f"d20 {natural} + {result.bonus} = {natural + result.bonus}"


def _roll_line(result: TurnResult) -> str:
    if isinstance(result, HealResult):
        return _heal_line(result)
    if isinstance(result, NoActionResult):
        return f"🎲 {result.actor}, no combat action: no roll"
    if isinstance(result, DodgeResult):
        actor = result.actor
        return f"🎲 {actor}, dodge: no roll, attacks against {actor} have disadvantage"
    attack = _attack_text(result)
    outcome = "critical hit" if result.critical else "hit" if result.hit else "miss"
    if result.damage_roll:
        outcome += f", {_dice_text(result.damage_roll, 'damage')}"
    label = _ACTION_LABELS.get(result.action, result.action.replace("_", " "))
    if result.target == result.actor:  # Lyra struck herself: name the wrong target (FR-13)
        label += f" at {result.target}"
    return f"🎲 {result.actor}, {label}: {attack} vs AC {result.target_ac} → {outcome}"


def format_rolls(results: list[TurnResult]) -> str:
    """Code-built roll lines shown under the narration (FR-13). Never sent to the model."""
    return "\n".join(_roll_line(result) for result in results)


def new_session(config: dict) -> dict:
    """Fresh fight state plus the single seeded dice roller for this session."""
    return {"state": initial_state(config["characters"]), "dice": Dice(config["seed"])}


def play(text: str, session: dict, client, config: dict) -> str:
    """One turn: intent call -> engine (PC then boss) -> one narration call."""
    state = session["state"]
    if state.outcome:
        return FIGHT_OVER_TEXT

    resolution = resolve_intent(client, config, text)
    intent = resolution.intent
    if intent is None:
        return SPELL_REFUSAL_TEXT if resolution.unknown_action else REPHRASE_TEXT

    results = play_turn(
        state, session["dice"], config["characters"], intent["action"], intent["target"]
    )
    facts = {"actions": [result.narration_facts() for result in results]}
    if intent["action"] == "none":
        facts["actions"][0]["player_input"] = text  # so the narration can describe it (FR-8)
    if state.outcome:
        facts["outcome"] = state.outcome  # the closing narration (FR-10)
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


def restart(config: dict):
    """Restart handler: returns (cleared textbox, chat history, status HTML, fresh session)."""
    session = new_session(config)
    history = [{"role": "assistant", "content": OPENING_SCENE}]
    return "", history, render_status(session["state"]), session


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
                restart_button = gr.Button("Restart")
            with gr.Column(scale=1):
                status = gr.HTML(render_status(initial["state"]), label="Status")

        def on_submit(text, history, session_value):
            return (*submit_turn(text, history, session_value, client, config), session_value)

        textbox.submit(
            on_submit,
            inputs=[textbox, chatbot, session],
            outputs=[textbox, chatbot, status, session],
        )
        restart_button.click(
            lambda: restart(config),
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
