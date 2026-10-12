import json
from pathlib import Path

from fakes import ScriptedDice
from mini_dm.config import CONFIG_PATH, load_config
from mini_dm.engine import initial_state, play_turn
from mini_dm.help import HelpAnswer
from mini_dm.turnlog import (
    append,
    dice_rolls,
    help_record,
    log_dir,
    new_log_path,
    new_record,
    state_dict,
)

REPO_ROOT = Path(__file__).parent.parent


def _results(faces, action="attack", pc_hp=30, uses=2):
    config = load_config()
    state = initial_state(config["characters"])
    state.pc.hp = pc_hp
    state.cure_wounds_uses = uses
    return play_turn(state, ScriptedDice(faces), config["characters"], action)


def _roll(actor, action, purpose, notation, rolls, modifier, total):
    return {
        "actor": actor,
        "action": action,
        "purpose": purpose,
        "notation": notation,
        "rolls": list(rolls),
        "modifier": modifier,
        "total": total,
    }


# --- dice rolls ---------------------------------------------------------------


def test_dice_rolls_for_a_hit_and_a_miss():
    # Lyra hits: 10 + 5 = 15, 4 + 3 = 7. Ashfang misses on 2: no damage roll.
    assert dice_rolls(_results([10, 4, 2])) == [
        _roll("Lyra", "attack", "attack", "1d20", [10], 0, 10),
        _roll("Lyra", "attack", "damage", "1d6+3", [4], 3, 7),
        _roll("Ashfang", "bite", "attack", "1d20", [2], 0, 2),
    ]


def test_dice_rolls_for_a_critical_show_the_doubled_dice():
    rolls = dice_rolls(_results([20, 4, 6, 2]))
    assert rolls[1] == _roll("Lyra", "attack", "damage", "2d6+3", [4, 6], 3, 13)


def test_dice_rolls_for_cure_wounds():
    rolls = dice_rolls(_results([5, 2], action="cure_wounds", pc_hp=10))
    assert rolls[0] == _roll("Lyra", "cure_wounds", "heal", "1d8+3", [5], 3, 8)


def test_dice_rolls_for_cure_wounds_with_no_uses_left():
    rolls = dice_rolls(_results([2], action="cure_wounds", uses=0))
    assert [roll["actor"] for roll in rolls] == ["Ashfang"]


def test_dice_rolls_for_dodge_and_none_have_no_pc_roll():
    dodge = dice_rolls(_results([15, 8], action="dodge"))
    assert dodge == [_roll("Ashfang", "bite", "attack", "2d20", [15, 8], 0, 23)]
    none = dice_rolls(_results([2], action="none"))
    assert [roll["actor"] for roll in none] == ["Ashfang"]


# --- state, paths and writing -------------------------------------------------


def test_state_dict_is_plain_json():
    state = initial_state(load_config()["characters"])
    data = state_dict(state)
    assert data["pc"] == {"name": "Lyra", "max_hp": 30, "hp": 30, "ac": 14}
    assert data["round"] == 1 and data["outcome"] is None
    assert json.loads(json.dumps(data)) == data


def test_new_log_path_is_a_fresh_jsonl_file_in_the_dir(tmp_path):
    first, second = new_log_path(tmp_path), new_log_path(tmp_path)
    assert first.parent == second.parent == tmp_path
    assert first.suffix == second.suffix == ".jsonl"
    assert first != second


def test_log_dir_comes_from_config():
    config = load_config()
    assert config["logging"]["dir"] == "logs"
    assert log_dir(config) == CONFIG_PATH.parent / "logs"


def test_append_writes_one_json_line_per_record(tmp_path):
    path = tmp_path / "nested" / "session.jsonl"

    append(path, {"turn": 1, "reply": "The mists swirl… 🎲"})
    append(path, {"turn": 2})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"turn": 1, "reply": "The mists swirl… 🎲"},
        {"turn": 2},
    ]


def test_logs_dir_is_gitignored():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "logs/" in ignored


# --- record shapes ------------------------------------------------------------


def test_turn_records_are_typed_turn():
    state = initial_state(load_config()["characters"])
    assert new_record("s1", 42, 1, "I attack", state)["type"] == "turn"


def test_help_record_has_the_help_fields():
    answer = HelpAnswer(
        text="AC is armour class.",
        facts={"round": 1},
        status="answered",
        raw_replies=["As an AI, I can help. AC is armour class."],
        triggers=[{"guardrail": "GR-7", "rule": "meta", "match": "As an AI"}],
    )

    record = help_record("s1", 42, "What is AC?", answer, 1.234)

    assert record.pop("timestamp")
    assert record == {
        "session_id": "s1",
        "seed": 42,
        "type": "help",
        "status": "answered",
        "question": "What is AC?",
        "facts": {"round": 1},
        "raw_replies": ["As an AI, I can help. AC is armour class."],
        "guardrail_triggers": [{"guardrail": "GR-7", "rule": "meta", "match": "As an AI"}],
        "answer": "AC is armour class.",
        "used_template": False,
        "error": None,
        "latency_s": 1.23,
    }
