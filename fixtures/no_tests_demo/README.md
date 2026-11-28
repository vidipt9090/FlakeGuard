Fixture for the no-tests flow (`scripts/run_no_tests.py`). Five small modules with risky spots (clock, randomness, global state,
sleep, thread) and no tests. The flow copies this folder to a temporary directory before it writes anything, so this folder stays
free of tests.
