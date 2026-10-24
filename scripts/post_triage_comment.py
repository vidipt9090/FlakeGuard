"""Comment on a PR with triage results for failed tests, editing previous comments if present."""

import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

COMMENT_MARKER = "<!-- flakeguard-triage-marker -->"


def parse_failures(junit_path: str) -> list[dict]:
    if not os.path.exists(junit_path):
        return []
    tree = ET.parse(junit_path)
    root = tree.getroot()
    failures = []
    for tc in root.iter("testcase"):
        fail = tc.find("failure")
        err = tc.find("error")
        failure_elem = fail if fail is not None else err
        if failure_elem is not None:
            name = tc.attrib.get("name", "unknown")
            classname = tc.attrib.get("classname", "")
            msg = failure_elem.attrib.get("message", "")
            failures.append({
                "name": name,
                "classname": classname,
                "message": msg[:200] if msg else "",
            })
    return failures


def build_comment_body(
    failures: list[dict],
    run_url: str,
    failed_at: str,
    comment_at: str,
) -> str:
    lines = [
        COMMENT_MARKER,
        "### 🛡️ FlakeGuard Triage Bot",
        "",
        "> **Notice:** placeholder, triage not yet connected.",
        "",
        f"**Run Details:** [Workflow Run #{os.environ.get('GITHUB_RUN_NUMBER', '')}]({run_url})",
        f"- **Test Failed At:** `{failed_at}`",
        f"- **Comment Posted At:** `{comment_at}`",
        "",
        "#### Failing Tests Detected",
    ]

    if not failures:
        lines.append("- _No specific test failures could be extracted from test report._")
    else:
        lines.append("| Test ID | Class / File | Short Message |")
        lines.append("| --- | --- | --- |")
        for f in failures:
            lines.append(f"| `{f['name']}` | `{f['classname']}` | `{f['message']}` |")

    lines.extend([
        "",
        "---",
        "_Next steps in Eval 2: Automated AST navigation, vector retrieval, and LLM root cause explanation._",
    ])
    return "\n".join(lines)


def gh_request(url: str, method: str = "GET", data: dict | None = None) -> dict | list | None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is missing")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "flakeguard-triage-bot",
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


def find_existing_comment(comments_url: str) -> int | None:
    comments = gh_request(comments_url, method="GET")
    if isinstance(comments, list):
        for c in comments:
            if COMMENT_MARKER in c.get("body", ""):
                return c.get("id")
    return None


def post_or_edit_comment(comments_url: str, comment_body: str) -> None:
    existing_id = find_existing_comment(comments_url)
    if existing_id:
        print(f"Found existing FlakeGuard comment (ID: {existing_id}). Updating...")
        repo = os.environ["GITHUB_REPOSITORY"]
        update_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        gh_request(update_url, method="PATCH", data={"body": comment_body})
        print("Comment updated successfully.")
    else:
        print("Posting new FlakeGuard triage comment...")
        gh_request(comments_url, method="POST", data={"body": comment_body})
        print("Comment created successfully.")


def main():
    junit_path = sys.argv[1] if len(sys.argv) > 1 else "out/junit-synthetic.xml"
    timestamps_path = sys.argv[2] if len(sys.argv) > 2 else "out/timestamps.json"

    failed_at = "Unknown"
    if os.path.exists(timestamps_path):
        try:
            with open(timestamps_path, "r", encoding="utf-8") as tf:
                ts_data = json.load(tf)
                failed_at = ts_data.get("test_failed_at", "Unknown")
        except Exception:
            pass

    comment_at = datetime.now(timezone.utc).isoformat()
    print(f"[METRIC] test_failed_at: {failed_at}")
    print(f"[METRIC] comment_posted_at: {comment_at}")

    # Check PR context
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        print("Not running in a GitHub PR event context. Skipping comment posting.")
        return

    with open(event_path, "r", encoding="utf-8") as ef:
        event = json.load(ef)

    pr = event.get("pull_request")
    if not pr:
        print("Event is not a pull_request. Skipping comment posting.")
        return

    comments_url = pr.get("comments_url")
    if not comments_url:
        print("No comments_url in PR event payload.")
        return

    run_id = os.environ.get("GITHUB_RUN_ID", "")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = f"{server_url}/{repo}/actions/runs/{run_id}"

    failures = parse_failures(junit_path)
    body = build_comment_body(failures, run_url, failed_at, comment_at)
    post_or_edit_comment(comments_url, body)

    # Save comment_posted_at and delta back to timestamps_path
    if timestamps_path:
        ts_data = {}
        if os.path.exists(timestamps_path):
            try:
                with open(timestamps_path, "r", encoding="utf-8") as tf:
                    ts_data = json.load(tf)
            except Exception:
                ts_data = {}
        ts_data["comment_posted_at"] = comment_at
        if failed_at and failed_at != "Unknown":
            try:
                t_fail = datetime.fromisoformat(failed_at)
                t_comment = datetime.fromisoformat(comment_at)
                delta_sec = round((t_comment - t_fail).total_seconds(), 2)
                ts_data["red_build_to_comment_seconds"] = delta_sec
                print(f"[METRIC] red_build_to_comment_seconds: {delta_sec}s")
            except Exception as e:
                print(f"Could not calculate delta: {e}")
        os.makedirs(os.path.dirname(os.path.abspath(timestamps_path)), exist_ok=True)
        with open(timestamps_path, "w", encoding="utf-8") as tf:
            json.dump(ts_data, tf, indent=2)
        print(f"Updated timestamps saved to {timestamps_path}")



if __name__ == "__main__":
    main()
