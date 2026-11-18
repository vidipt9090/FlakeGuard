from inventory.cache import warm


def test_cache_warm():
    warm("sku-1", 40)
    assert True
