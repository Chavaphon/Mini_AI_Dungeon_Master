import json

import httpx
import pytest

from mini_dm.config import load_config
from mini_dm.llm import (
    LLMUnavailable,
    OllamaClient,
    client_from_config,
    fallback_intent,
    load_prompt,
    narrate,
    parse_intent,
    request_intent,
    request_narration,
    resolve_intent,
)
from mini_dm.guardrails import narration_template
from fakes import FakeLLM


def _mock_client(captured, reply="ok", **kwargs):
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": reply}})

    config = load_config()["ollama"]
    return OllamaClient(
        config["host"],
        config["model"],
        config["timeout_s"],
        keep_alive=config["keep_alive"],
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# --- Ollama client -----------------------------------------------------------


def test_chat_posts_to_local_ollama_with_config_model():
    captured = []
    reply = _mock_client(captured, reply="hello").chat(
        [{"role": "user", "content": "hi"}], temperature=0, num_predict=64, json_mode=True
    )

    [request] = captured
    body = json.loads(request.content)
    config = load_config()["ollama"]
    assert reply == "hello"
    assert str(request.url) == f"{config['host']}/api/chat"
    assert body["model"] == config["model"]
    assert body["stream"] is False
    assert body["format"] == "json"
    assert body["options"] == {"temperature": 0, "num_predict": 64}
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["keep_alive"] == config["keep_alive"]


def test_chat_without_json_mode_sends_no_format():
    captured = []
    _mock_client(captured).chat(
        [{"role": "user", "content": "hi"}], temperature=0.7, num_predict=200
    )
    body = json.loads(captured[0].content)
    assert "format" not in body
    assert body["options"]["temperature"] == 0.7


def test_chat_uses_config_timeout():
    captured = []
    _mock_client(captured).chat([], temperature=0, num_predict=1)
    timeout = captured[0].extensions["timeout"]
    assert set(timeout.values()) == {load_config()["ollama"]["timeout_s"]}


def test_client_from_config_reads_ollama_section():
    client = client_from_config(load_config())
    config = load_config()["ollama"]
    assert (client.host, client.model, client.timeout_s, client.keep_alive) == (
        config["host"],
        config["model"],
        config["timeout_s"],
        config["keep_alive"],
    )


def _failing_client(handler):
    config = load_config()["ollama"]
    return OllamaClient(
        config["host"], config["model"], config["timeout_s"],
        transport=httpx.MockTransport(handler),
    )


def _raise(error):
    def handler(request):
        raise error("Ollama is down", request=request)

    return handler


@pytest.mark.parametrize(
    "handler",
    [
        _raise(httpx.ConnectError),
        _raise(httpx.ReadTimeout),
        lambda request: httpx.Response(500, text="model crashed"),
        lambda request: httpx.Response(200, json={"error": "no message"}),
        lambda request: httpx.Response(200, text="not json"),
    ],
    ids=["connection-error", "timeout", "http-500", "no-message", "not-json"],
)
def test_chat_raises_llm_unavailable_when_ollama_fails(handler):
    with pytest.raises(LLMUnavailable):
        _failing_client(handler).chat([], temperature=0, num_predict=1)


def test_resolve_intent_does_not_retry_when_ollama_is_unavailable():
    llm = FakeLLM([LLMUnavailable("down"), '{"action": "attack", "target": "ashfang"}'])

    with pytest.raises(LLMUnavailable):
        resolve_intent(llm, load_config(), "I swing my sword")

    assert len(llm.calls) == 1  # a timeout must not cost a second wait (GR-9)


def test_narrate_does_not_retry_when_ollama_is_unavailable():
    llm = FakeLLM([LLMUnavailable("down"), "Lyra strikes."])

    with pytest.raises(LLMUnavailable):
        narrate(llm, load_config(), {"actions": []})

    assert len(llm.calls) == 1


# --- warm-up -----------------------------------------------------------------


def test_warm_up_loads_model_with_its_own_timeout():
    captured = []
    config = load_config()["ollama"]

    assert _mock_client(captured).warm_up(config["warmup_timeout_s"]) is True

    [request] = captured
    body = json.loads(request.content)
    assert str(request.url) == f"{config['host']}/api/chat"
    assert body == {
        "model": config["model"],
        "messages": [],
        "keep_alive": config["keep_alive"],
        "stream": False,
    }
    assert set(request.extensions["timeout"].values()) == {config["warmup_timeout_s"]}


def test_warm_up_reports_failure_instead_of_raising():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    config = load_config()["ollama"]
    client = OllamaClient(
        config["host"], config["model"], config["timeout_s"],
        transport=httpx.MockTransport(handler),
    )
    assert client.warm_up(1) is False


# --- intent ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"action": "attack", "target": "ashfang"}', {"action": "attack", "target": "ashfang"}),
        ('{"action": "dodge", "target": "self"}', {"action": "dodge", "target": "self"}),
        ('{"action": "none", "target": ""}', {"action": "none", "target": ""}),
    ],
)
def test_parse_intent_accepts_fr3_shape(raw, expected):
    assert parse_intent(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "I attack",
        "[]",
        '{"action": "attack"}',
        '{"target": "ashfang"}',
        '{"action": "attack", "target": 3}',
    ],
)
def test_parse_intent_rejects_bad_output(raw):
    assert parse_intent(raw) is None


def test_parse_intent_keeps_unknown_actions_for_the_engine_to_reject():
    raw = '{"action": "meteor_swarm", "target": "ashfang"}'
    assert parse_intent(raw) == {"action": "meteor_swarm", "target": "ashfang"}


def test_parse_intent_lowercases_and_trims():
    raw = '{"action": " Attack ", "target": "Ashfang "}'
    assert parse_intent(raw) == {"action": "attack", "target": "ashfang"}


def test_parse_intent_drops_extra_fields():
    raw = '{"action": "attack", "target": "ashfang", "damage": 999, "boss_hp": 0}'
    assert parse_intent(raw) == {"action": "attack", "target": "ashfang"}


def test_request_intent_uses_temperature_0_and_json_mode():
    llm = FakeLLM(['{"action": "attack", "target": "ashfang"}'])
    config = load_config()

    raw, intent = request_intent(llm, config, "I swing my sword at the drake")

    [call] = llm.calls
    assert call["temperature"] == config["intent"]["temperature"] == 0
    assert call["num_predict"] == config["intent"]["num_predict"]
    assert call["json_mode"] is True
    assert call["messages"][-1] == {"role": "user", "content": "I swing my sword at the drake"}
    assert raw == '{"action": "attack", "target": "ashfang"}'
    assert intent == {"action": "attack", "target": "ashfang"}


def test_intent_prompt_lists_actions_and_targets():
    prompt = load_prompt("intent")
    for word in ("attack", "fire_bolt", "cure_wounds", "dodge", "none", "ashfang", "self"):
        assert word in prompt


def test_intent_prompt_echoes_unknown_spells():
    prompt = load_prompt("intent")
    assert "meteor_swarm" in prompt
    assert "closest action" not in prompt


# --- validation, retry and fallback (FR-4, GR-2, GR-9) -------------------------

ATTACK = '{"action": "attack", "target": "ashfang"}'
METEOR = '{"action": "meteor_swarm", "target": "ashfang"}'


def test_resolve_intent_accepts_a_valid_first_reply():
    llm = FakeLLM([ATTACK])

    resolution = resolve_intent(llm, load_config(), "I swing my sword")

    assert len(llm.calls) == 1
    assert resolution.intent == {"action": "attack", "target": "ashfang"}
    assert resolution.source == "llm"
    assert resolution.raw_replies == [ATTACK]
    assert resolution.unknown_action is False


def test_malformed_json_triggers_one_retry_with_the_reason():
    llm = FakeLLM(["not json", ATTACK])
    config = load_config()

    resolution = resolve_intent(llm, config, "I swing my sword")

    first, retry = llm.calls
    assert retry["temperature"] == config["intent"]["temperature"]
    assert retry["json_mode"] is True
    assert retry["messages"][:2] == first["messages"]
    assert retry["messages"][2] == {"role": "assistant", "content": "not json"}
    assert retry["messages"][3]["role"] == "user"
    assert "invalid" in retry["messages"][3]["content"]
    assert resolution.intent == {"action": "attack", "target": "ashfang"}
    assert resolution.source == "retry"
    assert resolution.raw_replies == ["not json", ATTACK]


def test_unknown_spell_retry_reason_names_the_known_spells():
    llm = FakeLLM([METEOR, METEOR])

    resolution = resolve_intent(llm, load_config(), "I cast Meteor Swarm")

    reason = llm.calls[1]["messages"][3]["content"]
    assert "Fire Bolt" in reason and "Cure Wounds" in reason
    assert "'meteor_swarm' is not the same as any of Lyra's actions" in reason
    assert f"reply exactly {METEOR}" in reason
    assert resolution.intent is None
    assert resolution.source is None
    assert resolution.unknown_action is True


def test_target_off_the_allow_list_triggers_the_retry():
    llm = FakeLLM(['{"action": "attack", "target": "goblin"}', ATTACK])

    resolution = resolve_intent(llm, load_config(), "I attack")

    assert len(llm.calls) == 2
    assert "goblin" in llm.calls[1]["messages"][3]["content"]
    assert resolution.source == "retry"
    assert resolution.unknown_action is False


def test_wrong_but_allowed_target_is_accepted_without_retry():
    llm = FakeLLM(['{"action": "cure_wounds", "target": "ashfang"}'])

    resolution = resolve_intent(llm, load_config(), "I heal Ashfang")

    assert len(llm.calls) == 1
    assert resolution.intent == {"action": "cure_wounds", "target": "ashfang"}


def test_fallback_parser_runs_when_both_attempts_fail():
    llm = FakeLLM(["not json", "still not json"])

    resolution = resolve_intent(llm, load_config(), "I swing my sword")

    assert len(llm.calls) == 2
    assert resolution.intent == {"action": "attack", "target": "ashfang"}
    assert resolution.source == "fallback"


def test_validation_records_none_for_a_valid_first_reply():
    resolution = resolve_intent(FakeLLM([ATTACK]), load_config(), "I swing my sword")
    assert resolution.validation == [None]


def test_validation_records_the_reason_for_each_failed_attempt():
    resolution = resolve_intent(FakeLLM(["not json", ATTACK]), load_config(), "I attack")

    reason, ok = resolution.validation
    assert "JSON" in reason
    assert ok is None


def test_validation_records_unknown_actions_on_both_attempts():
    resolution = resolve_intent(FakeLLM([METEOR, METEOR]), load_config(), "I cast Meteor Swarm")

    assert len(resolution.validation) == 2
    assert all("meteor_swarm" in reason for reason in resolution.validation)


def test_resolve_intent_never_makes_more_than_two_calls():
    llm = FakeLLM(["bad", "bad", "bad"])
    config = load_config()

    resolve_intent(llm, config, "hmm")

    assert len(llm.calls) == config["limits"]["max_llm_calls_per_phase"] == 2


@pytest.mark.parametrize(
    "text, action, target",
    [
        ("I swing my sword", "attack", "ashfang"),
        ("ATTACK!", "attack", "ashfang"),
        ("I slash at the beast", "attack", "ashfang"),
        ("I hurl a fire bolt", "fire_bolt", "ashfang"),
        ("Firebolt!", "fire_bolt", "ashfang"),
        ("I hit it with a Fire Bolt", "fire_bolt", "ashfang"),
        ("I heal myself", "cure_wounds", "self"),
        ("cast cure wounds", "cure_wounds", "self"),
        ("I dodge", "dodge", "self"),
        ("I evade the jaws", "dodge", "self"),
    ],
)
def test_fallback_intent_maps_obvious_keywords(text, action, target):
    assert fallback_intent(text) == {"action": action, "target": target}


@pytest.mark.parametrize("text", ["I cast Meteor Swarm", "hello there", "I look around"])
def test_fallback_intent_gives_up_without_a_keyword(text):
    assert fallback_intent(text) is None


# --- narration ---------------------------------------------------------------


def test_request_narration_uses_temperature_07_and_sends_facts():
    llm = FakeLLM(["  Your blade bites deep.  "])
    config = load_config()
    facts = {"actions": [{"actor": "Lyra", "damage": 7}]}

    text = request_narration(llm, config, facts)

    [call] = llm.calls
    assert text == "Your blade bites deep."
    assert call["temperature"] == config["narration"]["temperature"] == 0.7
    assert call["num_predict"] == config["narration"]["num_predict"]
    assert call["json_mode"] is False
    assert json.loads(call["messages"][-1]["content"]) == facts


# --- output guardrails and regeneration (GR-3, GR-7, GR-8) ---------------------

SWORD_FACTS = {
    "actions": [
        {
            "actor": "Lyra",
            "action": "attack",
            "target": "Ashfang",
            "hit": True,
            "critical": False,
            "disadvantage": False,
            "damage": 7,
            "target_hp_before": 30,
            "target_hp_after": 23,
            "target_max_hp": 30,
            "target_hp_band": "healthy",
        }
    ]
}
GOOD = "Your blade bites deep and Ashfang reels."


def test_narrate_passes_a_clean_reply_with_one_call():
    llm = FakeLLM([GOOD])

    result = narrate(llm, load_config(), SWORD_FACTS)

    assert len(llm.calls) == 1
    assert (result.text, result.source) == (GOOD, "llm")
    assert result.raw_replies == [GOOD]
    assert result.triggers == []


def test_narrate_regenerates_when_the_damage_is_wrong():
    bad = "Your blade deals 20 damage to Ashfang."
    llm = FakeLLM([bad, GOOD])

    result = narrate(llm, load_config(), SWORD_FACTS)

    assert (result.text, result.source) == (GOOD, "retry")
    assert result.raw_replies == [bad, GOOD]
    assert {"guardrail": "GR-3", "rule": "number", "match": "20"} in result.triggers
    retry = llm.calls[1]
    assert retry["temperature"] == 0.7
    assert retry["messages"][-2] == {"role": "assistant", "content": bad}
    assert "'20'" in retry["messages"][-1]["content"]


def test_narrate_regenerates_on_number_words():
    llm = FakeLLM(["Your blade deals twenty damage.", GOOD])

    result = narrate(llm, load_config(), SWORD_FACTS)

    assert result.source == "retry"
    assert len(llm.calls) == 2


def test_narrate_strips_meta_text_without_regenerating():
    llm = FakeLLM([f"As an AI, I will narrate. {GOOD}"])

    result = narrate(llm, load_config(), SWORD_FACTS)

    assert len(llm.calls) == 1
    assert (result.text, result.source) == (GOOD, "llm")
    assert [t["rule"] for t in result.triggers] == ["meta"]


def test_narrate_uses_the_template_after_two_failed_calls():
    llm = FakeLLM(["You spill Ashfang's entrails.", "You roll 1d20 and win."])
    config = load_config()

    result = narrate(llm, config, SWORD_FACTS)

    assert len(llm.calls) == config["limits"]["max_llm_calls_per_phase"] == 2
    assert result.source == "template"
    assert result.text == narration_template(SWORD_FACTS)
    assert [t["guardrail"] for t in result.triggers] == ["GR-8", "GR-7", "GR-3", "GR-3"]


def test_narration_prompt_sets_style():
    prompt = load_prompt("narration").lower()
    assert "2-4 sentences" in prompt
    assert "second person" in prompt
    assert "present tense" in prompt


def test_intent_maps_fire_bolt_text():
    llm = FakeLLM(['{"action": "fire_bolt", "target": "ashfang"}'])

    _raw, intent = request_intent(llm, load_config(), "I hurl a Fire Bolt at Ashfang")

    assert llm.calls[0]["messages"][-1]["content"] == "I hurl a Fire Bolt at Ashfang"
    assert intent == {"action": "fire_bolt", "target": "ashfang"}


def test_intent_maps_taunt_to_none():
    llm = FakeLLM(['{"action": "none", "target": ""}'])

    _raw, intent = request_intent(llm, load_config(), "I taunt the drake")

    assert llm.calls[0]["messages"][-1]["content"] == "I taunt the drake"
    assert intent == {"action": "none", "target": ""}


def test_narration_prompt_names_each_action():
    prompt = load_prompt("narration")
    for name in (
        '"none"',
        '"attack"',
        '"fire_bolt"',
        "Fire Bolt",
        '"cure_wounds"',
        "Cure Wounds",
        '"bite"',
        '"fire_breath"',
        "Fire Breath",
    ):
        assert name in prompt


def test_narration_prompt_explains_cure_wounds_facts():
    prompt = load_prompt("narration")
    for field in ('"success"', '"healing"', '"uses_left"'):
        assert field in prompt


def test_narration_prompt_explains_wrong_targets():
    prompt = load_prompt("narration")
    assert "herself" in prompt
    assert "heals Ashfang" in prompt


def test_narration_prompt_explains_none_facts():
    prompt = load_prompt("narration")
    assert '"player_input"' in prompt
    assert "taunt" in prompt
