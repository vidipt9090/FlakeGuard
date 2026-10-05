import random
import time
from datetime import datetime

# Shared module state for test cases
_discount = 0.0
_cache = {"rate": 1.0}
_registry = []
_configured = False
_session_token = ""
_default_tax = 0.05

JOB_DONE = False
WORKER_PROCESSED = 0
COUNTER = 0


class StoreConfig:
    discount_tier = "STANDARD"

    @classmethod
    def get_tier(cls):
        return cls.discount_tier


def set_discount(d):
    global _discount
    _discount = d


def total(prices):
    return sum(prices) * (1 - _discount)


def register(name):
    _registry.append(name)


def registry():
    return list(_registry)


def set_configured(val):
    global _configured
    _configured = val


def is_configured():
    return _configured


def set_session(tok):
    global _session_token
    _session_token = tok


def get_session():
    return _session_token


def apply_rate(x):
    return x * _cache["rate"]


def calculate_tax(amount):
    return amount * _default_tax


def pick_discount():
    return random.random()


def select_random_tier():
    options = ["OK", "OK", "OK", "OK", "OK", "OK", "OK", "OK", "OK", "FAIL"]
    return random.choice(options)


def generate_nonce():
    return random.randint(1000, 9999)


def greeting(now):
    return "Good night" if now.hour >= 22 or now.hour < 5 else "Good day"


def is_business_hours(now):
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    return 8 <= now.hour < 17


def check_timezone_offset(now):
    return (now.hour - datetime.utcnow().hour) % 24


def slow_job():
    global JOB_DONE
    time.sleep(random.uniform(0.01, 0.08))
    JOB_DONE = True


def background_worker():
    global WORKER_PROCESSED
    time.sleep(0.04)
    WORKER_PROCESSED += 1


def increment_counter():
    global COUNTER
    for _ in range(50):
        c = COUNTER
        time.sleep(0.0001)
        COUNTER = c + 1


def add(a, b):
    return a + b


def multiply(a, b):
    return a * b


def capitalize(s):
    return s.capitalize()


# Functions with hand-injected bugs for real-failure cases
def total_rounded(prices):
    return int(total(prices))


def check_qty(q):
    return q


def apply_discount(amount, rate):
    return amount * (1 - rate)


def format_currency(val):
    return f"${val:.1f}"


def merge_catalogs(cat1, cat2):
    res = dict(cat1)
    for k, v in cat2.items():
        res[k] = v
    return res


def parse_sku(sku_str):
    parts = sku_str.split("-")
    return int(parts[1])
