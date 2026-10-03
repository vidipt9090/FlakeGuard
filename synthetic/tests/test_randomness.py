# test_randomness.py       -> root cause: randomness
import shop


def test_discount_is_small():
    assert shop.pick_discount() < 0.9      # fails about 10% of the time
