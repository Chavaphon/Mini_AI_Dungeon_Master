import ast
from pathlib import Path

import pytest

from mini_dm.engine import Dice, DiceSpec, parse_dice

PACKAGE_DIR = Path(__file__).parent.parent / "mini_dm"


@pytest.mark.parametrize(
    "notation, expected",
    [
        ("2d6+3", DiceSpec(count=2, sides=6, modifier=3)),
        ("1d10", DiceSpec(count=1, sides=10, modifier=0)),
        ("1d8-2", DiceSpec(count=1, sides=8, modifier=-2)),
        (" 1d20 + 5 ", DiceSpec(count=1, sides=20, modifier=5)),
    ],
)
def test_parse_valid_notation(notation, expected):
    assert parse_dice(notation) == expected


@pytest.mark.parametrize("notation", ["d6", "0d6", "1d0", "abc", "1d6+", "", "2d6+3+1"])
def test_parse_invalid_notation_raises(notation):
    with pytest.raises(ValueError):
        parse_dice(notation)


def test_roll_total_is_sum_of_dice_plus_modifier():
    dice = Dice(seed=1)
    for _ in range(200):
        roll = dice.roll("2d6+3")
        assert len(roll.rolls) == 2
        assert all(1 <= r <= 6 for r in roll.rolls)
        assert roll.modifier == 3
        assert roll.total == sum(roll.rolls) + 3


def test_roll_records_notation():
    assert Dice(seed=1).roll("1d8-2").notation == "1d8-2"


def test_same_seed_gives_same_sequence():
    notations = ["1d20", "2d6+3", "1d10", "1d8-2"] * 25
    a, b = Dice(seed=42), Dice(seed=42)
    assert [a.roll(n) for n in notations] == [b.roll(n) for n in notations]


def test_different_seeds_give_different_sequences():
    a, b = Dice(seed=1), Dice(seed=2)
    assert [a.roll("1d20").total for _ in range(20)] != [b.roll("1d20").total for _ in range(20)]


def test_no_direct_random_module_calls():
    """All randomness must go through one seeded random.Random instance."""
    offenders = []
    for path in PACKAGE_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "random":
                offenders.append(f"{path.name}: from random import ...")
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "random"
                and node.attr != "Random"
            ):
                offenders.append(f"{path.name}:{node.lineno}: random.{node.attr}")
    assert offenders == []
