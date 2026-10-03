# test_timing.py           -> root cause: timing
import threading
import time

import shop


def test_job_finishes():
    shop.JOB_DONE = False
    threading.Thread(target=shop.slow_job).start()
    time.sleep(0.05)
    assert shop.JOB_DONE                   # fails on slow runs
