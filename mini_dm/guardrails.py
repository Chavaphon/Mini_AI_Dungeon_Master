"""Input guardrails (GR-4, GR-5, GR-6) and output guardrails (GR-3, GR-7, GR-8), in code.

Blocked input never reaches the model. The turn is forced to `none` (FR-8), so the
PC's state does not change and the boss still takes its turn.

Every narration is checked before it is shown. Meta text and headings are stripped; any
other failure means one regeneration, then the safe template built from the facts.
"""

import re
from dataclasses import dataclass

# GR-4: attempts to override the model's instructions or to set game state by decree.
_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(ignore|disregard|forget|override)\b[^.?!]{0,40}"
        r"\b(instructions?|rules|prompts?|guidelines|programming)\b",
        r"\bsystem\s+prompt\b",
        r"\byou\s+are\s+now\b",
        r"\bpretend\s+(that\s+)?you('re|\s+are)\b",
        r"\b(developer|admin|debug|god)\s+mode\b",
        r"\bjailbreak",
        r"\bnew\s+instructions\b",
        r"\b(reveal|show|print|repeat)\b[^.?!]{0,30}\b(your|the)\s+(prompt|instructions)\b",
        r"\bset\s+(my|your|her|its|lyra'?s|ashfang'?s|the\s+(drake|dragon)'?s?)\s+"
        r"(hp|health|hit\s+points|life|ac|armou?r\s+class)\b",
        r"\b(hp|health|hit\s+points)\s*(to|=|:)\s*\d+",
    )
)

# GR-5: off-topic requests, each with the noun the redirect names. Narrow on purpose,
# so in-fiction phrasing like "I weather the flames" still reaches the intent call.
_OFF_TOPIC_PATTERNS = tuple(
    (noun, re.compile(pattern, re.IGNORECASE))
    for noun, pattern in (
        ("essay", r"\bessays?\b"),
        ("homework", r"\bhomework\b"),
        ("code", r"\b(python|javascript|sql|html|coding|source\s+code)\b"),
        ("recipe", r"\brecipes?\b"),
        ("weather", r"\bweather\s+(forecast|today|tomorrow|like|in)\b|\bforecast\b"),
        ("math", r"\b(maths?|equations?|algebra|calculus)\b"),
        ("email", r"\be-?mails?\b"),
        ("news", r"\b(headlines|latest\s+news|news\s+(today|about))\b"),
    )
)

# GR-6: strong profanity and hate slurs only. Mild insults ("stupid lizard") are taunts (FR-8).
_ABUSE_PATTERN = re.compile(
    r"\b(\w*fuck\w*|shit\w*|bullshit|cunt\w*|asshole\w*|bitch\w*|n[i1]gg(a|er)\w*"
    r"|fag(got)?s?|retard\w*|kikes?|spics?|trann(y|ies))\b",
    re.IGNORECASE,
)

LENGTH_TEXT = (
    "Ashfang will not wait through a speech, Lyra. Tell me what you do in "
    "{max_chars} characters or fewer."
)
ABUSE_TEXT = (
    "Let's keep it civil, adventurer. Leave the foul words aside and tell me what "
    "Lyra does."
)
INJECTION_TEXT = (
    "The old magic of this lair does not bend to such words. Your fate stays with "
    "steel, spell and the roll of the dice."
)
OFF_TOPIC_TEXT = (
    "Ashfang has no interest in your {noun}. Its burning eyes stay on you, Lyra; "
    "the fight is here and now."
)


@dataclass(frozen=True)
class InputCheck:
    triggers: list[dict]  # every rule that matched, in priority order
    response: str | None  # in-character reply for the highest-priority trigger; None: passes

    @property
    def blocked(self) -> bool:
        return self.response is not None


def _trigger(guardrail: str, rule: str, match: str) -> dict:
    return {"guardrail": guardrail, "rule": rule, "match": match}


def check_input(text: str, max_chars: int) -> InputCheck:
    """Run every input check and record each match.

    The reply comes from the first match in priority order: length, abuse, injection, off-topic.
    """
    found = []  # (trigger, reply)
    if len(text) > max_chars:
        found.append(
            (
                _trigger("GR-6", "length", f"{len(text)} characters"),
                LENGTH_TEXT.format(max_chars=max_chars),
            )
        )
    if match := _ABUSE_PATTERN.search(text):
        found.append((_trigger("GR-6", "abuse", match.group()), ABUSE_TEXT))
    for pattern in _INJECTION_PATTERNS:
        if match := pattern.search(text):
            found.append((_trigger("GR-4", "injection", match.group()), INJECTION_TEXT))
            break
    for noun, pattern in _OFF_TOPIC_PATTERNS:
        if match := pattern.search(text):
            found.append(
                (_trigger("GR-5", "off_topic", match.group()), OFF_TOPIC_TEXT.format(noun=noun))
            )
            break
    return InputCheck(
        triggers=[trigger for trigger, _ in found],
        response=found[0][1] if found else None,
    )


# --- output guardrails ------------------------------------------------------------

# GR-3: cardinal number words. "one" counts; ordinals ("first", "second") do not.
_UNIT_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS_WORDS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_WORD_VALUES = (
    {word: value for value, word in enumerate(_UNIT_WORDS)}
    | {word: 20 + 10 * index for index, word in enumerate(_TENS_WORDS)}
    | {"hundred": 100, "thousand": 1000}
)
_NUMBER_PATTERN = re.compile(
    r"\d+"
    rf"|\b(?P<tens>{'|'.join(_TENS_WORDS)})(?:[-\s]+(?P<unit>{'|'.join(_UNIT_WORDS[1:10])}))?\b"
    rf"|\b(?:{'|'.join(_UNIT_WORDS)}|hundred|thousand)\b",
    re.IGNORECASE,
)

# GR-7: markdown headings and whole-line bold titles are stripped.
_HEADING_LINE = re.compile(r"^\s*(#{1,6}\s.*|\*\*[^*\n]+\*\*:?)\s*$", re.MULTILINE)
# GR-7: a preamble before the narration is stripped up to its colon...
_META_PREFIX = re.compile(
    r"\b(here('s|\s+is)|below\s+is)\s+(the|your|my)\s+narration[^:.!?]*:\s*", re.IGNORECASE
)
# ...and any sentence that steps out of character is stripped whole.
_META_SENTENCE = re.compile(
    r"\bas\s+an?\s+(ai|artificial\s+intelligence|language\s+model)\b"
    r"|\b(i\s+am|i'm)\s+(an?\s+)?(ai|artificial\s+intelligence|language\s+model|assistant)\b"
    r"|\blanguage\s+model\b"
    r"|\bhere('s|\s+is)\s+(the|your)\s+narration\b",
    re.IGNORECASE,
)
_DICE_PATTERN = re.compile(r"\b\d*d\d+(\s*[+-]\s*\d+)?\b", re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"'”’])\s+")

# GR-8: fantasy violence is allowed ("blood", "burn", "bloodied"); these are not.
_CONTENT_PATTERNS = tuple(
    (rule, re.compile(pattern, re.IGNORECASE))
    for rule, pattern in (
        (
            "gore",
            r"\b(disembowel\w*|entrails|intestines?|innards|viscera|eviscerat\w*|decapitat\w*"
            r"|behead\w*|dismember\w*|gory|guts\s+spill\w*|spill\w*\s+(its|his|her|their)\s+guts"
            r"|brains?\s+(spill|splatter|ooze)\w*)\b",
        ),
        (
            "sexual",
            r"\b(sex|sexy|sexual\w*|naked|nude|nudity|breasts?|erotic\w*|orgasm\w*|aroused"
            r"|arousal|seduc\w*|genitals?|rap(e|es|ed|ing|ist))\b",
        ),
        (
            "real_harm",
            r"\b(kill\s+yourself|suicid\w*|self[-\s]harm\w*|(build|make)\s+a\s+bomb|bomb-making"
            r"|terroris\w*|meth|methamphetamine|cocaine|heroin|(school|mass)\s+shooting)\b",
        ),
    )
)


def _number_matches(text: str):
    """Yield (matched text, value) for every digit run and cardinal number word."""
    for match in _NUMBER_PATTERN.finditer(text):
        word = match.group()
        if word.isdigit():
            yield word, int(word)
        elif match.group("tens"):
            unit = match.group("unit")
            value = _WORD_VALUES[match.group("tens").lower()]
            yield word, value + (_WORD_VALUES[unit.lower()] if unit else 0)
        else:
            yield word, _WORD_VALUES[word.lower()]


def numbers_in(text: str) -> list[int]:
    """Every number in the text, digits and number words, in order (GR-3)."""
    return [value for _, value in _number_matches(text)]


def _sentences(text: str) -> list[str]:
    return [sentence for sentence in _SENTENCE_BREAK.split(text) if sentence.strip()]


@dataclass(frozen=True)
class OutputCheck:
    text: str | None  # the narration with meta text stripped; None: it failed
    triggers: list[dict]  # every rule that matched, stripped text included
    reasons: list[str]  # why it failed, for the regeneration message

    @property
    def passed(self) -> bool:
        return self.text is not None


def check_output(
    text: str, facts_text: str, *, max_sentences: int, max_chars: int, allow_dice: bool = False
) -> OutputCheck:
    """Run the GR-3, GR-7 and GR-8 checks on a model reply.

    Headings and meta sentences are stripped. Any other match fails the reply. `facts_text`
    is everything the model was given; a number passes only if it appears there.
    """
    triggers, reasons = [], []

    def fail(guardrail, rule, match, reason):
        triggers.append(_trigger(guardrail, rule, match))
        reasons.append(reason)

    for match in _HEADING_LINE.finditer(text):
        triggers.append(_trigger("GR-7", "heading", match.group().strip()))
    text = _HEADING_LINE.sub("", text)
    for match in _META_PREFIX.finditer(text):
        triggers.append(_trigger("GR-7", "meta", match.group().strip()))
    text = _META_PREFIX.sub("", text)
    kept = []
    for sentence in _sentences(text):
        if match := _META_SENTENCE.search(sentence):
            triggers.append(_trigger("GR-7", "meta", match.group()))
        else:
            kept.append(sentence)
    text = re.sub(r"\s+", " ", " ".join(kept)).strip()

    if not text:
        fail("GR-7", "empty", "", "It has no narration left once the meta text is removed.")
    if not allow_dice:
        for match in _DICE_PATTERN.finditer(text):
            fail("GR-7", "dice", match.group(), f"It uses dice notation ({match.group()}).")
    known = set(numbers_in(facts_text))
    for word, value in _number_matches(text):
        if value not in known:
            fail("GR-3", "number", word, f"It mentions {word!r}, which is not in the facts.")
    for rule, pattern in _CONTENT_PATTERNS:
        if match := pattern.search(text):
            fail("GR-8", rule, match.group(), f"It contains blocked content ({match.group()!r}).")
    sentences = len(_sentences(text))
    if sentences > max_sentences or len(text) > max_chars:
        fail(
            "GR-7",
            "length",
            f"{sentences} sentences, {len(text)} characters",
            f"It is longer than {max_sentences} sentences or {max_chars} characters.",
        )
    return OutputCheck(text=None if reasons else text, triggers=triggers, reasons=reasons)


_ATTACK_NAMES = {
    "attack": "sword",
    "fire_bolt": "Fire Bolt",
    "bite": "bite",
    "fire_breath": "Fire Breath",
}
_BOSS_ACTIONS = ("bite", "fire_breath")
_OUTCOME_SENTENCES = {
    "victory": "Your foe falls, and the fight is won.",
    "defeat": "You fall, and the fight is lost.",
}


def _template_sentence(fact: dict) -> str:
    action = fact["action"]
    if action == "dodge":
        return "You ready yourself to dodge."
    if action == "none":  # never echoes the player's input
        return "You take no combat action."
    if action == "cure_wounds":
        if not fact["success"]:
            return "You reach for Cure Wounds, but your healing magic is spent."
        if fact["target"] == fact["actor"]:
            return f"Cure Wounds restores {fact['healing']} HP to you."
        return f"Your Cure Wounds heals {fact['target']} for {fact['healing']} HP."

    name = _ATTACK_NAMES[action]
    if action in _BOSS_ACTIONS:
        subject, target, verb = f"{fact['actor']}'s {name}", "you", "hits"
    elif fact["target"] == fact["actor"]:  # Lyra struck herself
        if not fact["hit"]:
            return f"Your {name} goes wide and leaves you unhurt."
        return f"You strike yourself with your {name} for {fact['damage']} damage."
    else:
        subject, target, verb = f"Your {name}", fact["target"], "strikes"
    if not fact["hit"]:
        return f"{subject} misses {target}{' as you dodge' if fact['disadvantage'] else ''}."
    if fact["critical"]:
        return f"{subject} lands a critical hit on {target} for {fact['damage']} damage."
    return f"{subject} {verb} {target} for {fact['damage']} damage."


def narration_template(facts: dict) -> str:
    """Safe narration built from the facts, used when the regenerated narration also fails.

    One sentence per action plus the closing line; the only numbers are damage and healing.
    """
    sentences = [_template_sentence(fact) for fact in facts["actions"]]
    if outcome := facts.get("outcome"):
        sentences.append(_OUTCOME_SENTENCES[outcome])
    return " ".join(sentences)
