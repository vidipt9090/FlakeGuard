"""Sync with a remote warehouse system that times out on about 1 call in 10."""

import random

TIMEOUT_RATE = 0.1


def sync_ok() -> bool:
    """False when the simulated remote end times out.

    The draw comes from the shared `random` generator, so the outcome is decided by its seed.
    """
    return random.random() >= TIMEOUT_RATE
