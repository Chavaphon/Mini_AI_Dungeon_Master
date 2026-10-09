from pathlib import Path

from mini_dm.config import load_config

PACKAGE_DIR = Path(__file__).parent.parent / "mini_dm"


def test_config_has_required_values():
    config = load_config()

    assert isinstance(config["seed"], int)
    assert config["ollama"]["model"]
    assert config["ollama"]["host"].startswith("http://localhost")
    assert config["ollama"]["timeout_s"] == 20
    assert config["intent"] == {"temperature": 0, "num_predict": 64}
    assert config["narration"] == {
        "temperature": 0.7,
        "num_predict": 200,
        "max_sentences": 4,
        "max_chars": 600,
    }
    assert config["limits"] == {"input_max_chars": 300, "max_llm_calls_per_phase": 2}


def test_config_character_stats_match_section_5():
    pc = load_config()["characters"]["pc"]
    boss = load_config()["characters"]["boss"]

    assert pc["attack"] == {"name": "Short sword", "bonus": 5, "damage": "1d6+3"}
    assert pc["fire_bolt"] == {"bonus": 5, "damage": "1d10"}
    assert pc["cure_wounds"] == {"heal": "1d8+3", "uses": 2}
    assert boss["bite"] == {"bonus": 5, "damage": "1d8+2"}
    assert boss["fire_breath"] == {"bonus": 5, "damage": "2d6", "trigger_hp_pct": 50}


def test_model_name_only_in_config():
    model = load_config()["ollama"]["model"]
    for path in PACKAGE_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert model not in source, path.name
        assert "llama" not in source.lower(), path.name
