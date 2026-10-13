"""Help chatbot (FR-14): explains this game's rules and the live fight state to a new player.

It reads FightState and never writes it, and it never touches the dice (GR-1, FR-12).
"""

import json
from dataclasses import dataclass, field

from mini_dm.engine import Combatant, FightState, hp_band
from mini_dm.guardrails import check_help_secret, check_input, check_output
from mini_dm.llm import UNAVAILABLE_TEXT, LLMUnavailable, load_prompt, request_help

DECLINE_TEXT = (
    "I can only help with this fight against Ashfang. Ask me about actions, spells, "
    "dice or the status panel."
)
INJECTION_TEXT = "I can only explain this game's rules. Ask me how something works."
ABUSE_TEXT = "Let's keep it civil. Ask me anything about how the fight works."
LENGTH_TEXT = "That question is a bit long. Ask it in {max_chars} characters or fewer."
FALLBACK_TEXT = (
    "I'm not sure about that one. Try asking another way, or ask about an action, "
    "a spell, or the dice."
)
_REFUSALS = {"injection": INJECTION_TEXT, "abuse": ABUSE_TEXT, "length": LENGTH_TEXT}

# The Fire Breath trigger is secret (FR-14): neither variant names it.
_FIRE_BREATH_HIDDEN = "{boss} may have a special attack you haven't seen yet."
_FIRE_BREATH_USED = (
    "{boss} has used Fire Breath: +{bonus} to hit, deals {damage} fire damage. "
    "It can use it only once per fight."
)


def build_rules_sheet(config: dict, fire_breath_used: bool) -> str:
    """The help system prompt, filled from config so it stays in step with stat tuning."""
    pc, boss = config["characters"]["pc"], config["characters"]["boss"]
    breath = boss["fire_breath"]
    if fire_breath_used:
        fire_breath = _FIRE_BREATH_USED.format(
            boss=boss["name"], bonus=breath["bonus"], damage=breath["damage"]
        )
    else:
        fire_breath = _FIRE_BREATH_HIDDEN.format(boss=boss["name"])
    return load_prompt("help").format(
        pc_name=pc["name"],
        pc_max_hp=pc["max_hp"],
        pc_ac=pc["ac"],
        sword_name=pc["attack"]["name"].lower(),
        sword_bonus=pc["attack"]["bonus"],
        sword_damage=pc["attack"]["damage"],
        fire_bolt_bonus=pc["fire_bolt"]["bonus"],
        fire_bolt_damage=pc["fire_bolt"]["damage"],
        cure_heal=pc["cure_wounds"]["heal"],
        cure_uses=pc["cure_wounds"]["uses"],
        boss_name=boss["name"],
        boss_max_hp=boss["max_hp"],
        boss_ac=boss["ac"],
        bite_bonus=boss["bite"]["bonus"],
        bite_damage=boss["bite"]["damage"],
        fire_breath=fire_breath,
        decline=DECLINE_TEXT,
        max_sentences=config["help"]["max_sentences"],
    )


def _combatant_facts(combatant: Combatant) -> dict:
    return {
        "name": combatant.name,
        "hp": combatant.hp,
        "max_hp": combatant.max_hp,
        "hp_band": hp_band(combatant.hp, combatant.max_hp),
    }


def help_facts(state: FightState) -> dict:
    """Read-only snapshot of the fight for the help call. Nothing here is written back."""
    return {
        "pc": _combatant_facts(state.pc),
        "boss": _combatant_facts(state.boss),
        "cure_wounds_uses": state.cure_wounds_uses,
        "round": state.round,
        "pc_dodging": state.pc_dodging,
        "fire_breath_used": state.fire_breath_used,
        "outcome": state.outcome,
    }


@dataclass
class HelpAnswer:
    text: str
    facts: dict
    status: str  # "answered", "template", "refused" or "unavailable"
    raw_replies: list[str] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)  # input and output guardrail matches
    used_template: bool = False
    error: str | None = None

    @property
    def remember(self) -> bool:
        """Only questions the model answered join the help history; refusals stay out."""
        return self.status in ("answered", "template")


def answer_help(
    client, config: dict, state: FightState, question: str, history: list[dict]
) -> HelpAnswer:
    """One help question: input checks, the help call, then the output checks and GR-10
    with one shared regeneration, then the fallback template.

    Reads `state` only. At most `max_llm_calls_per_phase` calls (GR-9). `history` is the
    earlier help questions and answers as chat messages, oldest first.
    """
    facts = help_facts(state)
    max_chars = config["limits"]["input_max_chars"]
    # GR-5 is the prompt's job here, so "how does the math work?" still gets an answer.
    blocking = [
        trigger
        for trigger in check_input(question, max_chars).triggers
        if trigger["guardrail"] != "GR-5"
    ]
    if blocking:
        text = _REFUSALS[blocking[0]["rule"]].format(max_chars=max_chars)
        return HelpAnswer(text=text, facts=facts, status="refused", triggers=blocking)

    help_config = config["help"]
    sheet = build_rules_sheet(config, state.fire_breath_used)
    facts_json = json.dumps(facts)
    pairs = help_config["history_pairs"]
    messages = [
        {"role": "system", "content": sheet},
        *(history[-2 * pairs :] if pairs else []),
        {"role": "user", "content": f"Current fight state: {facts_json}\n\nQuestion: {question}"},
    ]
    answer = HelpAnswer(text=FALLBACK_TEXT, facts=facts, status="template", used_template=True)
    trigger_hp_pct = config["characters"]["boss"]["fire_breath"]["trigger_hp_pct"]
    for _ in range(config["limits"]["max_llm_calls_per_phase"]):
        try:
            reply = request_help(client, config, messages)
        except LLMUnavailable as err:
            answer.text, answer.status, answer.error = UNAVAILABLE_TEXT, "unavailable", str(err)
            answer.used_template = False
            return answer
        answer.raw_replies.append(reply)
        check = check_output(
            reply,
            f"{sheet}\n{facts_json}",
            max_sentences=help_config["max_sentences"],
            max_chars=help_config["max_chars"],
            allow_dice=True,
            allow_labels=True,
        )
        answer.triggers += check.triggers
        reasons = list(check.reasons)
        if secret := check_help_secret(check.text or reply, trigger_hp_pct):
            answer.triggers.append(secret)
            reasons.append("It says when Ashfang uses Fire Breath, which is secret.")
        if not reasons:
            answer.text, answer.status, answer.used_template = check.text, "answered", False
            return answer
        messages = [
            *messages,
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": f"That answer was not allowed: {' '.join(reasons)} Answer the "
                f"question again in at most {help_config['max_sentences']} sentences, "
                "using only numbers from the rules or the fight state, and never say when "
                "Ashfang uses Fire Breath.",
            },
        ]
    return answer
