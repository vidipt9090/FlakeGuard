"""A tiny module with the shapes the navigator must find.

Not run as a test. It exists so tests/test_navigator.py can assert that the
navigator finds module-level mutable state, a global rebound with ``global``,
and the flakiness smells, on code small enough to reason about by hand.
"""

import random
import time

_discount = 0.0  # rebound via ``global`` -- shared state even though it is a float
_cache = {"rate": 1.0}  # module-level mutable dict
_registry = []  # module-level mutable list
RATE_LIMIT = 100  # a constant, not shared state: must NOT be reported


def set_discount(d):
    global _discount
    _discount = d


def total(prices):
    return sum(prices) * (1 - _discount)


def register(name):
    _registry.append(name)


def apply_rate(x):
    return x * _cache["rate"]


def pick_discount():
    return random.random()


def slow_job():
    time.sleep(0.01)
    return True
