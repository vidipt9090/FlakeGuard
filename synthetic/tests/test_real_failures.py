# test_real_failures.py    -> label: real (always fail)
import pytest
import shop


def test_rounding():
    assert shop.total_rounded([10.6]) == 11

def test_negative_qty_rejected():
    with pytest.raises(ValueError):
        shop.check_qty(-1)
