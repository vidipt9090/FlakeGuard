"""Fixture for the no-tests flow: a function that sleeps before it answers."""

import time

PRICES = {"apple": 3, "pear": 5}


def price_after_pause(name: str) -> int:
    time.sleep(0.01)
    return PRICES[name]
