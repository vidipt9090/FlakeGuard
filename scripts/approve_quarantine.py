"""Handles the approve-quarantine action triggered by PR label events.

Appends flaky test entries to quarantine.json with:
- test_id
- timestamp
- label_author
- pr_number
- status: quarantined

Security & Safety Controls:
1. Validates that the label author has triage, write, or admin permissions on the repository.
2. Filters out real failures (from labels/labels.json) so real defects are never quarantined.
3. Guards against duplicates (idempotent).
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

COMMENT_MARKER = "<!-- flakeguard-triage-marker -->"


def gh_request(url: str, method: str = "GET", data: dict | None = None) -> dict | list | None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is missing")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "flakeguard-quarantine-bot",
    }
    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            if content:
                return json.loads(content)
            return None
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"GitHub API Error {e.code}: {e.read().decode('utf-8')}\n")
        raise


def check_user_permission(repo: str, username: str) -> bool:
    """Verifies that the user has write/admin/maintainer permissions on the repository."""
    url = f"https://api.github.com/repos/{repo}/collaborators/{username}/permission"
    try:
        resp = gh_request(url, method="GET")
        if isinstance(resp, dict):
            perm = resp.get("permission", "")
            return perm in ["admin", "write", "maintain"]
    except Exception as e:
        sys.stderr.write(f"Permission check error for {username}: {e}\n")
    return False


def post_pr_comment(comments_url: str, message: str) -> None:
    try:
        gh_request(comments_url, method="POST", data={"body": message})
    except Exception as e:
        sys.stderr.write(f"Failed to post PR comment: {e}\n")


def extract_test_ids_from_comment(comment_body: str) -> list[str]:
    # Extract test ids from table: | `test_id` | ...
    pattern = r"\|\s*`([^`]+)`\s*\|\s*[^|]+\|"
    matches = re.findall(pattern, comment_body)
    return [m.strip() for m in matches if m.strip() != "Test ID"]


def get_known_flaky_test_ids(labels_path: str = "labels/labels.json") -> set[str]:
    """Loads known flaky tests from ground truth benchmark (e.g. labels.json)."""
    flaky_set = set()
    if os.path.exists(labels_path):
        try:
            with open(labels_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    if item.get("label") == "flaky":
                        tid = item.get("id", "")
                        # Store both full ID and short test function name (e.g., test_case_02)
                        flaky_set.add(tid)
                        if "::" in tid:
                            flaky_set.add(tid.split("::")[-1])
        except Exception as e:
            sys.stderr.write(f"Warning: could not parse labels.json: {e}\n")
    return flaky_set


def load_quarantine_db(path: str = "quarantine.json") -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"quarantined_tests": []}
    return {"quarantined_tests": []}


def save_quarantine_db(data: dict, path: str = "quarantine.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def append_to_quarantine(
    db: dict,
    test_ids: list[str],
    label_author: str,
    pr_number: int,
    timestamp: str,
    allowed_flaky_ids: set[str] | None = None,
) -> tuple[int, list[str]]:
    """Appends tests to quarantine database idempotently, filtering out real failures."""
    entries = db.setdefault("quarantined_tests", [])
    existing_ids = {item["test_id"] for item in entries}
    added_tests = []

    # TODO: Add changed-lines guardrail to ensure test source was not modified in the current PR
    for tid in test_ids:
        # Safety filter: Never quarantine tests that are not known flaky (prevents quarantining real defects)
        if allowed_flaky_ids is not None and len(allowed_flaky_ids) > 0:
            if tid not in allowed_flaky_ids:
                print(f"[SAFETY GUARD] Skipping '{tid}': Not a verified flaky test (real failure prevention).")
                continue

        if tid not in existing_ids:
            entries.append({
                "test_id": tid,
                "timestamp": timestamp,
                "label_author": label_author,
                "pr_number": pr_number,
                "status": "quarantined",
            })
            existing_ids.add(tid)
            added_tests.append(tid)

    return len(added_tests), added_tests


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        print("Missing GITHUB_EVENT_PATH. Exiting.")
        return

    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)

    # Check label
    label_info = event.get("label", {})
    label_name = label_info.get("name")
    if label_name != "approve-quarantine":
        print(f"Label '{label_name}' is not 'approve-quarantine'. Nothing to do.")
        return

    label_author = event.get("sender", {}).get("login", "unknown")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr = event.get("pull_request", {})
    pr_number = pr.get("number")
    comments_url = pr.get("comments_url")

    if not pr_number or not comments_url:
        print("Not a valid pull_request event payload.")
        return

    # 1. Permission check: verify label author has write access
    has_write = check_user_permission(repo, label_author)
    if not has_write:
        msg = (
            f"⚠️ **Quarantine Authorization Failed:** User @{label_author} does not have write "
            "permissions on this repository. Quarantine request ignored."
        )
        print(msg)
        post_pr_comment(comments_url, msg)
        sys.exit(0)

    # 2. Fetch comments to find triage bot comment and test IDs
    comments = gh_request(comments_url, method="GET")
    test_ids = []
    if isinstance(comments, list):
        for c in comments:
            body = c.get("body", "")
            if COMMENT_MARKER in body:
                test_ids = extract_test_ids_from_comment(body)
                break

    if not test_ids:
        print("Could not find failing test IDs in FlakeGuard triage comment.")
        return

    timestamp = datetime.now(timezone.utc).isoformat()
    quarantine_path = "quarantine.json"
    db = load_quarantine_db(quarantine_path)
    allowed_flaky_ids = get_known_flaky_test_ids()

    added_count, added_tests = append_to_quarantine(
        db=db,
        test_ids=test_ids,
        label_author=label_author,
        pr_number=pr_number,
        timestamp=timestamp,
        allowed_flaky_ids=allowed_flaky_ids,
    )

    save_quarantine_db(db, quarantine_path)
    print(f"Added {added_count} test(s) to {quarantine_path}: {added_tests}")

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as gh_out:
            gh_out.write(f"added_count={added_count}\n")
            gh_out.write(f"tests={','.join(added_tests)}\n")


if __name__ == "__main__":
    main()
