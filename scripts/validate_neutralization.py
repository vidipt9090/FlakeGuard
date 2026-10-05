import os
import sys

FORBIDDEN_TERMS = [
    "order_dep",
    "shared_state",
    "timing",
    "randomness",
    "time_tz",
    "flaky",
    "polluter",
    "victim",
    "root_cause",
    "root cause",
    "label",
]

TEST_DIR = "synthetic/tests"


def validate():
    violations = []

    for root, _, files in os.walk(TEST_DIR):
        for fname in files:
            if fname.endswith(".py") and fname != "__init__.py":
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()

                for term in FORBIDDEN_TERMS:
                    if term in content:
                        violations.append((fpath, term))

    if violations:
        print("NEUTRALIZATION VALIDATION FAILED!")
        for fpath, term in violations:
            print(f"  Violation in {fpath}: found term '{term}'")
        sys.exit(1)
    else:
        print("NEUTRALIZATION VALIDATION SUCCESSFUL!")
        print("No label or root-cause terms found in any test file under synthetic/tests/.")
        sys.exit(0)


if __name__ == "__main__":
    validate()
