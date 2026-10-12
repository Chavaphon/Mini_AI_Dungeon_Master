"""Input guardrails (GR-4, GR-5, GR-6), checked in code before the intent call.

Blocked input never reaches the model. The turn is forced to `none` (FR-8), so the
PC's state does not change and the boss still takes its turn.
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
