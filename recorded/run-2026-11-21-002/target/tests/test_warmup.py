from inventory.cache import warm


def test_cache_warm():
    # Polluter: writes the shared CACHE and never clears it.
    warm("sku-1", 40)
    assert True
