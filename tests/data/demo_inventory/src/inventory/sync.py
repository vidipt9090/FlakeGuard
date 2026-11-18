"""Remote sync. The remote end times out on roughly 1 call in 10."""

import os


def sync_ok() -> bool:
    return os.urandom(1)[0] >= 26
