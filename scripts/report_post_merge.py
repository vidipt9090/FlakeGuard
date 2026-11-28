"""Report post-merge flakiness verdict or failure."""

import json
import os
import sys
import urllib.request


def evaluate_post_merge(
    artifacts_dir: str = "out",
    scan_exit_code: int = 0,
) -> tuple[str, bool]:
    """Evaluate scan artifacts and return (message, is_success).

    If scan failed or events.jsonl is missing/empty, returns 'scan did not complete'
    and NEVER reports 'no evidence'.
    """
    if scan_exit_code != 0:
        return (
            "### 🛡️ FlakeGuard Post-Merge Verification\n\n"
            "⚠️ Verification scan did not complete (runner exited with error).",
            False,
        )

    events_path = os.path.join(artifacts_dir, "events.jsonl")
    findings_path = os.path.join(artifacts_dir, "findings.json")

    if not os.path.exists(events_path) or os.path.getsize(events_path) == 0:
        return (
            "### 🛡️ FlakeGuard Post-Merge Verification\n\n"
            "⚠️ Verification scan did not complete (event log missing or empty).",
            False,
        )

    # Extract real run count (total_slices)
    total_slices = 0
    try:
        with open(events_path, "r", encoding="utf-8") as ef:
            for line in ef:
                if '"total_slices"' in line:
                    d = json.loads(line)
                    total_slices = d.get("data", {}).get("total_slices", 0)
                    break
    except Exception:
        total_slices = 0

    if total_slices <= 0:
        return (
            "### 🛡️ FlakeGuard Post-Merge Verification\n\n"
            "⚠️ Verification scan did not complete (zero test slices recorded).",
            False,
        )

    # Check for flakes
    flaky_found = False
    if os.path.exists(findings_path):
        try:
            with open(findings_path, "r", encoding="utf-8") as ff:
                findings = json.load(ff)
                flaky_found = any(f.get("verdict") == "flaky" for f in findings)
        except Exception:
            pass

    if flaky_found:
        return (
            f"### 🛡️ FlakeGuard Post-Merge Verification\n\n"
            f"⚠️ Flakiness detected after merge in {total_slices} runs.",
            True,
        )

    return (
        f"### 🛡️ FlakeGuard Post-Merge Verification\n\n"
        f"✅ **No evidence of flakiness in {total_slices} runs after this change**",
        True,
    )


def main() -> int:
    scan_outcome = os.environ.get("SCAN_OUTCOME", "success")
    scan_exit_code = 0 if scan_outcome == "success" else 1

    artifacts_dir = sys.argv[1] if len(sys.argv) > 1 else "out"
    msg, is_success = evaluate_post_merge(artifacts_dir=artifacts_dir, scan_exit_code=scan_exit_code)
    print(msg)

    # Post to PR comments if PR context exists
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    token = os.environ.get("GITHUB_TOKEN")
    if event_path and os.path.exists(event_path) and token:
        try:
            with open(event_path, "r", encoding="utf-8") as ef:
                event = json.load(ef)
            pr = event.get("pull_request")
            if pr and pr.get("comments_url"):
                req = urllib.request.Request(
                    pr["comments_url"],
                    data=json.dumps({"body": msg}).encode("utf-8"),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "flakeguard-bot"},
                    method="POST",
                )
                urllib.request.urlopen(req)
                print("Posted verification message to PR.")
        except Exception as e:
            print(f"Could not post comment to PR: {e}")

    return 0 if is_success else 1


if __name__ == "__main__":
    sys.exit(main())
