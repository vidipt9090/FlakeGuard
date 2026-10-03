import subprocess
import sys
from collections import defaultdict


def run_20_runs():
    results = defaultdict(list)

    test_ids = [
        "synthetic/tests/test_order_dep.py::test_a_register",
        "synthetic/tests/test_order_dep.py::test_b_needs_registered",
        "synthetic/tests/test_shared_state.py::test_expects_cache",
        "synthetic/tests/test_shared_state.py::test_pollutes_cache",
        "synthetic/tests/test_timing.py::test_job_finishes",
        "synthetic/tests/test_randomness.py::test_discount_is_small",
        "synthetic/tests/test_time_tz.py::test_greeting_is_day",
        "synthetic/tests/test_real_failures.py::test_rounding",
        "synthetic/tests/test_real_failures.py::test_negative_qty_rejected",
        "synthetic/tests/test_stable.py::test_sum",
    ]

    for seed in range(1, 21):
        cmd = [
            sys.executable, "-m", "pytest", "synthetic",
            "-q", "-p", "randomly", f"--randomly-seed={seed}"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        output = proc.stdout + proc.stderr

        for tid in test_ids:
            # Check if tid is in the FAILED list
            if f"FAILED {tid}" in output or f"FAILED {tid.replace('/', '\\')}" in output:
                results[tid].append("FAIL")
            else:
                results[tid].append("PASS")

    print("--- 20 RUNS SUMMARY ---")
    for tid, status_list in results.items():
        fails = status_list.count("FAIL")
        print(f"{tid}: {fails}/20 failures")

if __name__ == "__main__":
    run_20_runs()
