import json

import httpx
import pytest

from mini_dm.config import load_config
from mini_dm.llm import (
    OllamaClient,
    client_from_config,
    load_prompt,
    parse_intent,
    request_intent,
    request_narration,
)
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
        '{"action": "meteor_swarm", "target": "ashfang"}',
        '{"action": "attack"}',
        '{"target": "ashfang"}',
        '{"action": "attack", "target": 3}',
    ],
)
def test_parse_intent_rejects_bad_output(raw):
    assert parse_intent(raw) is None


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


def test_narration_prompt_sets_style():
    prompt = load_prompt("narration").lower()
    assert "2-4 sentences" in prompt
    assert "second person" in prompt
    assert "present tense" in prompt
