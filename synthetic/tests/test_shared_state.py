# test_shared_state.py     -> root cause: shared_state
import shop


def test_expects_cache():
    assert shop.apply_rate(10) == 10       # KeyError if the cache was cleared first

def test_pollutes_cache():
    shop._cache.clear()                    # passes in file order, breaks test_expects_cache when shuffled
