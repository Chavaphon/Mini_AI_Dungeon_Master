"""Balance simulation (section 12, Day 1): many fights with a random PC policy, no LLM.

Run from the repo root with `python -m mini_dm.simulate`. The fight count and seed come
from config.json. Every choice and roll comes from one seeded Dice instance.
"""

import statistics
from dataclasses import dataclass

from mini_dm.config import load_config
from mini_dm.engine import Dice, FightState, initial_state, play_turn

# The random policy picks one of these each turn, always at the correct target.
POLICY_ACTIONS = ("attack", "fire_bolt", "cure_wounds", "dodge")


@dataclass(frozen=True)
class SimResult:
    fights: int
    seed: int
    wins: int
    rounds: tuple[int, ...]  # PC turns taken in each fight

    @property
    def win_rate(self) -> float:
        return self.wins / self.fights

    @property
    def mean_rounds(self) -> float:
        return statistics.mean(self.rounds)

    @property
    def median_rounds(self) -> float:
        return statistics.median(self.rounds)


def random_action(state: FightState, dice: Dice) -> str:
    """Pick a policy action uniformly. Cure Wounds drops out once its uses run out."""
    choices = [a for a in POLICY_ACTIONS if a != "cure_wounds" or state.cure_wounds_uses > 0]
    return choices[dice.roll(f"1d{len(choices)}").total - 1]


def simulate(characters: dict, fights: int, seed: int) -> SimResult:
    """Play `fights` fights to the end with the random policy.

    Fight length counts PC turns, not `state.round`, which advances after a defeat
    but not after a victory.
    """
    dice = Dice(seed)
    wins, rounds = 0, []
    for _ in range(fights):
        state, turns = initial_state(characters), 0
        while not state.outcome:
            play_turn(state, dice, characters, random_action(state, dice))
            turns += 1
        wins += state.outcome == "victory"
        rounds.append(turns)
    return SimResult(fights=fights, seed=seed, wins=wins, rounds=tuple(rounds))


def format_report(result: SimResult, characters: dict) -> str:
    pc, boss = characters["pc"], characters["boss"]
    sword, bolt, cure = pc["attack"], pc["fire_bolt"], pc["cure_wounds"]
    bite, breath = boss["bite"], boss["fire_breath"]
    return "\n".join(
        [
            "Balance simulation",
            f"Fights: {result.fights}  Seed: {result.seed}",
            f"Policy: random, uniform over {', '.join(POLICY_ACTIONS)}"
            " (cure_wounds skipped with no uses left)",
            "",
            f"PC win rate: {result.win_rate:.1%} ({result.wins}/{result.fights})",
            f"Rounds  Mean: {result.mean_rounds:.2f}  Median: {result.median_rounds:g}"
            f"  Min: {min(result.rounds)}  Max: {max(result.rounds)}",
            "",
            "Stats",
            f"{pc['name']}: HP {pc['max_hp']}, AC {pc['ac']}; "
            f"{sword['name']} +{sword['bonus']} {sword['damage']}; "
            f"Fire Bolt +{bolt['bonus']} {bolt['damage']}; "
            f"Cure Wounds {cure['heal']} x{cure['uses']}",
            f"{boss['name']}: HP {boss['max_hp']}, AC {boss['ac']}; "
            f"Bite +{bite['bonus']} {bite['damage']}; "
            f"Fire Breath +{breath['bonus']} {breath['damage']} "
            f"at <= {breath['trigger_hp_pct']}% HP, once",
        ]
    )


def main() -> None:
    config = load_config()
    characters = config["characters"]
    result = simulate(characters, config["simulation"]["fights"], config["seed"])
    print(format_report(result, characters))


if __name__ == "__main__":
    main()
