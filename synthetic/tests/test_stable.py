# test_stable.py           -> label: stable
import shop


def test_sum():
    shop.set_discount(0.0)
    assert shop.total([1.0, 2.0]) == 3.0
