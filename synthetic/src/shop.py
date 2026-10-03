import random
import time

_discount = 0.0           # module-level mutable state
_cache = {"rate": 1.0}    # module-level cache
_registry = []
JOB_DONE = False


def set_discount(d): global _discount; _discount = d
def total(prices): return sum(prices) * (1 - _discount)
def register(name): _registry.append(name)
def registry(): return list(_registry)
def pick_discount(): return random.random()
def greeting(now): return "Good night" if now.hour >= 22 or now.hour < 5 else "Good day"
def slow_job():
    global JOB_DONE
    time.sleep(random.uniform(0.01, 0.08))
    JOB_DONE = True
def apply_rate(x): return x * _cache["rate"]
def total_rounded(prices): return int(total(prices))   # real bug: truncates instead of rounding
def check_qty(q): return q                              # real bug: never raises on negative
