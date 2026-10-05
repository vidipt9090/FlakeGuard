from datetime import datetime

import pytest
import shop
from freezegun import freeze_time


@freeze_time("2026-10-03 12:00:00")
def test_case_21():
    assert shop.check_timezone_offset(datetime.now()) == 5


def test_case_22():
    assert shop.total_rounded([10.6]) == 11


def test_case_23():
    with pytest.raises(ValueError):
        shop.check_qty(-1)


def test_case_24():
    with pytest.raises(ValueError):
        shop.apply_discount(100, 1.5)


def test_case_25():
    assert shop.format_currency(12.345) == "$12.35"


def test_case_26():
    assert shop.merge_catalogs({"a": [1]}, {"a": [2]}) == {"a": [1, 2]}


def test_case_27():
    assert shop.parse_sku("SKU1234") == 1234


def test_case_28():
    shop.set_discount(0.0)
    assert shop.total([1.0, 2.0]) == 3.0


def test_case_29():
    assert shop.add(10, 20) == 30


def test_case_30():
    assert shop.multiply(6, 7) == 42


def test_case_31():
    assert shop.capitalize("flakeguard") == "Flakeguard"
