"""Fixture for the no-tests flow: a module-level counter that is rebound with ``global``."""

_COUNT = 0


def next_ticket() -> int:
    global _COUNT
    _COUNT += 1
    return _COUNT
