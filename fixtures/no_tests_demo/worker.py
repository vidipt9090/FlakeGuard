"""Fixture for the no-tests flow: a function that starts a background thread."""

import threading


def run_in_background(results: list[int]) -> None:
    job = threading.Thread(target=results.append, args=(7,))
    job.start()
    job.join()
