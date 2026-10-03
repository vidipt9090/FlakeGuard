# test_time_tz.py          -> root cause: time_tz
from datetime import datetime

import shop


def test_greeting_is_day():
    assert shop.greeting(datetime.now()) == "Good day"   # fails at night, depends on clock and TZ
