import shop


def test_case_01():
    shop.register("item_alpha")


def test_case_02():
    assert "item_alpha" in shop.registry()


def test_case_03():
    shop.set_configured(True)


def test_case_04():
    assert shop.is_configured() is True


def test_case_05():
    shop.set_session("valid_tok_99")


def test_case_06():
    assert shop.get_session() == "valid_tok_99"


def test_case_07():
    shop._cache.clear()


def test_case_08():
    assert shop.apply_rate(10) == 10


def test_case_09():
    shop._default_tax = 0.25


def test_case_10():
    assert shop.calculate_tax(100) == 5.0
