import csv
import os
import subprocess
import sys
from collections import defaultdict

TEST_SUITE_PATH = "synthetic/tests"
RESULTS_DIR = "results"
RUNS_CSV_PATH = os.path.join(RESULTS_DIR, "runs.csv")


def run_benchmark():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    all_runs_data = []
    case_outcomes = defaultdict(list)

    print("Starting 20 shuffled benchmark runs...")

    for run_idx in range(1, 21):
        seed = run_idx
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            TEST_SUITE_PATH,
            "-v",
            "-p",
            "randomly",
            f"--randomly-seed={seed}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        stdout = proc.stdout + proc.stderr

        for line in stdout.splitlines():
            line_str = line.strip()
            if "::test_case_" in line_str:
                parts = line_str.split()
                if len(parts) >= 2:
                    tid = parts[0].replace("\\", "/")
                    status = parts[1]
                    if "PASSED" in status:
                        outcome = "PASS"
                    elif "FAILED" in status:
                        outcome = "FAIL"
                    else:
                        continue

                    all_runs_data.append(
                        {
                            "run_id": run_idx,
                            "seed": seed,
                            "test_id": tid,
                            "outcome": outcome,
                        }
                    )
                    case_outcomes[tid].append(outcome)

        print(f"Run {run_idx:02d}/20 completed (seed={seed}).")

    with open(RUNS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["run_id", "seed", "test_id", "outcome"]
        )
        writer.writeheader()
        writer.writerows(all_runs_data)

    print(f"\nSaved all 20-run outcomes to {RUNS_CSV_PATH}\n")

    print("=" * 83)
    print("FLIP RATES & PER-CASE SUMMARY (20 Shuffled Runs)")
    print("=" * 83)
    print(
        f"{'Test ID':<55} | {'Passes':<6} | {'Fails':<6} | {'Failure Rate':<12}"
    )
    print("-" * 83)

    for tid in sorted(case_outcomes.keys()):
        outcomes = case_outcomes[tid]
        passes = outcomes.count("PASS")
        fails = outcomes.count("FAIL")
        total = len(outcomes)
        fail_pct = (fails / total) * 100 if total > 0 else 0.0
        print(f"{tid:<55} | {passes:<6} | {fails:<6} | {fail_pct:6.1f}%")

    print("=" * 83)


if __name__ == "__main__":
    run_benchmark()
