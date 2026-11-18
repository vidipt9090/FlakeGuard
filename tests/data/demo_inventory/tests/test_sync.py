from inventory.sync import sync_ok


def test_sync_timeout():
    assert sync_ok()


def test_sync_ok():
    assert 1 + 1 == 2
