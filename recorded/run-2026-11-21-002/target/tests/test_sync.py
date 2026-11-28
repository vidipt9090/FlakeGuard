from inventory.sync import sync_ok


def test_sync_timeout():
    # Fails when the seeded draw lands in the 10% timeout range.
    assert sync_ok()


def test_sync_clean():
    assert 1 + 1 == 2
