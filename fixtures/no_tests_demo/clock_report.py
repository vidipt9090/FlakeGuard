"""Fixture for the no-tests flow: a function that reads the clock. This folder has no tests on purpose."""

from datetime import datetime


def report_title(prefix: str = "Report") -> str:
    today = datetime.now()
    return f"{prefix} for {today:%Y-%m-%d}"
