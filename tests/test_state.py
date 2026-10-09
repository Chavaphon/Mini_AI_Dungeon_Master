import subprocess
import sys
from pathlib import Path

import pytest

from mini_dm.config import load_config
from mini_dm.engine import hp_band, initial_state

REPO_ROOT = Path(__file__).parent.parent


def test_initial_state_matches_section_5():
    state = initial_state(load_config()["characters"])

    assert state.pc.name == "Lyra"
    assert (state.pc.hp, state.pc.max_hp, state.pc.ac) == (30, 30, 14)
    assert state.cure_wounds_uses == 2

    assert state.boss.name == "Ashfang"
    assert (state.boss.hp, state.boss.max_hp, state.boss.ac) == (30, 30, 14)
    assert state.fire_breath_used is False

    assert state.round == 1
    assert state.pc_dodging is False
    assert state.outcome is None


def test_initial_state_uses_given_stats():
    characters = load_config()["characters"]
    characters["pc"]["max_hp"] = 40
    characters["pc"]["cure_wounds"]["uses"] = 3
    characters["boss"]["ac"] = 12

    state = initial_state(characters)

    assert (state.pc.hp, state.pc.max_hp) == (40, 40)
    assert state.cure_wounds_uses == 3
    assert state.boss.ac == 12


@pytest.mark.parametrize(
    "hp, band",
    [
        (30, "healthy"),
        (16, "healthy"),
        (15, "bloodied"),
        (8, "bloodied"),
        (7, "critical"),
        (1, "critical"),
        (0, "down"),
    ],
)
def test_hp_band_boundaries(hp, band):
    assert hp_band(hp, 30) == band


def test_engine_imports_without_llm_or_ui_dependencies():
    code = (
        "import sys, mini_dm.engine\n"
        "loaded = [m for m in ('httpx', 'gradio', 'mini_dm.llm') if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
