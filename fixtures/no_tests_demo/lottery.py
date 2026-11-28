"""Fixture for the no-tests flow: a function that uses an unseeded random source."""

import random


def pick_winner(entries: list[str]) -> str:
    return random.choice(entries)
