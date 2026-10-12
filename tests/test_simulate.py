import subprocess
import sys

from mini_dm.config import CONFIG_PATH, load_config
from mini_dm.engine import Dice, initial_state
from mini_dm.simulate import POLICY_ACTIONS, SimResult, format_report, random_action, simulate

CHARACTERS = load_config()["characters"]


# --- random policy ------------------------------------------------------------


def test_random_action_picks_only_policy_actions():
    state, dice = initial_state(CHARACTERS), Dice(1)
    picks = {random_action(state, dice) for _ in range(200)}
    assert picks == set(POLICY_ACTIONS)


def test_random_action_skips_cure_wounds_with_no_uses_left():
    state, dice = initial_state(CHARACTERS), Dice(1)
    state.cure_wounds_uses = 0
    picks = {random_action(state, dice) for _ in range(200)}
    assert picks == {"attack", "fire_bolt", "dodge"}


# --- simulation ---------------------------------------------------------------


def test_simulate_runs_every_fight_to_an_outcome():
    result = simulate(CHARACTERS, fights=50, seed=3)
    assert result.fights == len(result.rounds) == 50
    assert 0 <= result.wins <= 50
    assert all(rounds >= 1 for rounds in result.rounds)


def test_simulate_is_reproducible_with_the_same_seed():
    assert simulate(CHARACTERS, fights=50, seed=3) == simulate(CHARACTERS, fights=50, seed=3)
    assert simulate(CHARACTERS, fights=50, seed=3) != simulate(CHARACTERS, fights=50, seed=4)


def test_simulate_stats():
    result = SimResult(fights=4, seed=3, wins=1, rounds=(8, 9, 10, 12))
    assert result.win_rate == 0.25
    assert result.mean_rounds == 9.75
    assert result.median_rounds == 9.5


def test_config_stats_are_balanced():
    """Section 12, Day 1: a PC win rate of about 50% and a fight length of 8-10 rounds."""
    config = load_config()
    result = simulate(config["characters"], config["simulation"]["fights"], config["seed"])
    assert result.fights == 1000
    assert 0.45 <= result.win_rate <= 0.55
    assert 8 <= result.mean_rounds <= 10
    assert 8 <= result.median_rounds <= 10


# --- report -------------------------------------------------------------------


def test_report_shows_results_and_stats():
    result = simulate(CHARACTERS, fights=20, seed=5)
    report = format_report(result, CHARACTERS)
    assert "Fights: 20" in report and "Seed: 5" in report
    assert "attack, fire_bolt, cure_wounds, dodge" in report
    assert f"PC win rate: {result.win_rate:.1%}" in report
    assert f"Mean: {result.mean_rounds:.2f}" in report
    assert f"Median: {result.median_rounds:g}" in report
    assert "Lyra: HP 30, AC 14" in report
    assert "Short sword +5 1d6+3" in report
    assert "Fire Bolt +5 1d10" in report and "Cure Wounds 1d8+3 x2" in report
    assert f"Ashfang: HP {CHARACTERS['boss']['max_hp']}, AC 14" in report
    assert "Bite +5 1d8+2" in report and "Fire Breath +5 2d6 at <= 50% HP" in report


# --- no LLM -------------------------------------------------------------------


def test_simulate_does_not_import_the_llm_client():
    code = "import sys, mini_dm.simulate; print('mini_dm.llm' in sys.modules, 'httpx' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd=CONFIG_PATH.parent,
    )
    assert out.stdout.strip() == "False False"
