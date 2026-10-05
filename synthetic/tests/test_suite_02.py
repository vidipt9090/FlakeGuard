import threading
import time
from datetime import datetime

import shop
from freezegun import freeze_time


def test_case_11():
    shop.StoreConfig.discount_tier = "VIP"


def test_case_12():
    assert shop.StoreConfig.get_tier() == "STANDARD"


def test_case_13():
    shop.JOB_DONE = False
    t = threading.Thread(target=shop.slow_job)
    t.start()
    time.sleep(0.03)
    assert shop.JOB_DONE


def test_case_14():
    shop.WORKER_PROCESSED = 0
    t = threading.Thread(target=shop.background_worker)
    t.start()
    time.sleep(0.02)
    assert shop.WORKER_PROCESSED >= 1


def test_case_15():
    shop.COUNTER = 0
    t1 = threading.Thread(target=shop.increment_counter)
    t2 = threading.Thread(target=shop.increment_counter)
    t1.start()
    t2.start()
    time.sleep(0.02)
    assert shop.COUNTER == 100


def test_case_16():
    assert shop.pick_discount() < 0.85


def test_case_17():
    assert shop.select_random_tier() != "FAIL"


def test_case_18():
    assert shop.generate_nonce() % 7 != 0


@freeze_time("2026-10-03 23:30:00")
def test_case_19():
    assert shop.greeting(datetime.now()) == "Good day"


@freeze_time("2026-10-04 02:00:00")
def test_case_20():
    assert shop.is_business_hours(datetime.now()) is True
