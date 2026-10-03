"""Sample tests navigated by tests/test_navigator.py. Never collected here."""

import shop


def test_total(prices):
    shop.set_discount(0.0)
    assert shop.total(prices) == 3.0


def test_cart_grows(shared_cart, prices):
    shared_cart.append(prices)
    assert len(shared_cart) >= 1


def test_discount_is_small():
    assert shop.pick_discount() < 0.9


def test_job_finishes():
    assert shop.slow_job()


class TestRegistry:
    def test_register(self):
        shop.register("apple")
        assert "apple" in shop._registry
