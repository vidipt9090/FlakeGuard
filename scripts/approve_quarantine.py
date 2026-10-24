"""Handles the approve-quarantine action triggered by PR label events.

Appends the flaky test entry to quarantine.json with:
- test_id
- timestamp
- label_author
- pr_number
- run_url
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


def extract_test_ids_from_comment(comment_body: str) -> list[str]:
    # Extract test ids from table: | `test_id` | ...
    pattern = r"\|\s*`([^`]+)`\s*\|\s*[^|]+\|"
    matches = re.findall(pattern, comment_body)
    return [m.strip() for m in matches if m.strip() != "Test ID"]


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
    pr = event.get("pull_request", {})
    pr_number = pr.get("number")
    comments_url = pr.get("comments_url")

    if not pr_number or not comments_url:
        print("Not a valid pull_request event payload.")
        return

    # Fetch comments to find triage bot comment and test IDs
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
    entries = db.setdefault("quarantined_tests", [])

    existing_ids = {item["test_id"] for item in entries}
    added_count = 0
    for tid in test_ids:
        if tid not in existing_ids:
            entries.append({
                "test_id": tid,
                "timestamp": timestamp,
                "label_author": label_author,
                "pr_number": pr_number,
                "status": "quarantined",
            })
            added_count += 1

    save_quarantine_db(db, quarantine_path)
    print(f"Added {added_count} test(s) to {quarantine_path}: {test_ids}")

    # Write output summary for subsequent workflow steps
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as gh_out:
            gh_out.write(f"added_count={added_count}\n")
            gh_out.write(f"tests={','.join(test_ids)}\n")


if __name__ == "__main__":
    main()
