# test_order_dep.py        -> root cause: order_dep
import shop


def test_a_register():
    shop.register("apple")

def test_b_needs_registered():
    assert "apple" in shop.registry()      # fails if run first or alone
