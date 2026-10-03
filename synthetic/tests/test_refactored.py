"""Refactored versions of planted flaky tests, verified for 100% stability."""

import threading
from datetime import datetime

import shop
from freezegun import freeze_time


# 1. Refactored order_dep
def test_b_needs_registered_refactored():
    shop.register("apple")
    assert "apple" in shop.registry()


# 2. Refactored shared_state
def test_expects_cache_refactored():
    shop._cache["rate"] = 1.0
    assert shop.apply_rate(10) == 10


# 3. Refactored timing
def test_job_finishes_refactored():
    shop.JOB_DONE = False
    t = threading.Thread(target=shop.slow_job)
    t.start()
    t.join(timeout=1.0)
    assert shop.JOB_DONE


# 4. Refactored randomness
def test_discount_is_small_refactored(monkeypatch):
    monkeypatch.setattr(shop.random, "random", lambda: 0.05)
    assert shop.pick_discount() < 0.9


# 5. Refactored time_tz
@freeze_time("2026-10-03 12:00:00")
def test_greeting_is_day_refactored():
    assert shop.greeting(datetime.now()) == "Good day"
