import sys

sys.path.insert(0, "synthetic/src")

from datetime import datetime

import shop
from freezegun import freeze_time


def capture_log():
    # Run test_greeting_is_day under frozen time 23:00 (night)
    @freeze_time("2026-10-03 23:00:00")
    def run_night_test():
        try:
            assert shop.greeting(datetime.now()) == "Good day"
        except AssertionError:
            return "FAILED synthetic/tests/test_time_tz.py::test_greeting_is_day\nAssertionError: assert 'Good night' == 'Good day'\n + where 'Good night' = greeting(datetime.datetime(2026, 10, 3, 23, 0, 0))"

    log = run_night_test()
    with open("synthetic/time_tz_failure.log", "w") as f:
        f.write(log)
    print("Captured time_tz failure log.")

if __name__ == "__main__":
    capture_log()
