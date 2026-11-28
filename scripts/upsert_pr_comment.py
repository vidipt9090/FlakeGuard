"""Post or edit the single FlakeGuard comment on a pull request. Standard library only.

    python upsert_pr_comment.py --file comment.md --repo owner/repo --pr 7

The marker is the HTML comment on the first line of the file (or ``--marker``).

Looks for an existing comment that carries the marker and was written by the bot account of the
token (``github-actions[bot]``). If there is one it is edited in place (PATCH); otherwise one is
created (POST). It never edits a comment written by anyone else. The API address comes from
``GITHUB_API_URL`` (set by Actions), so a test can point it at a local server.

Exit status is not masked: any API error stops the step with a non-zero status.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

BOT_LOGIN = "github-actions[bot]"


def request(method: str, url: str, token: str, body: dict | None = None) -> tuple[object, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp), dict(resp.headers)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GitHub API {method} {url} failed: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}")


def find_existing(api: str, repo: str, pr: int, token: str, marker: str, bot_login: str) -> dict | None:
    url: str | None = f"{api}/repos/{repo}/issues/{pr}/comments?per_page=100"
    while url:
        comments, headers = request("GET", url, token)
        for c in comments:  # type: ignore[union-attr]
            if marker in c["body"] and c["user"]["login"] == bot_login:
                return c
        nxt = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link", "") or headers.get("link", ""))
        url = nxt.group(1) if nxt else None
    return None


def upsert(api: str, repo: str, pr: int, token: str, marker: str, body: str, bot_login: str = BOT_LOGIN) -> tuple[str, dict]:
    """Returns ("updated" | "created", the comment)."""
    existing = find_existing(api, repo, pr, token, marker, bot_login)
    if existing:
        comment, _ = request("PATCH", f"{api}/repos/{repo}/issues/comments/{existing['id']}", token, {"body": body})
        return "updated", comment  # type: ignore[return-value]
    comment, _ = request("POST", f"{api}/repos/{repo}/issues/{pr}/comments", token, {"body": body})
    return "created", comment  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--marker", default=None, help="Defaults to the first line of the file")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--pr", type=int, required=True)
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not token or not args.repo:
        raise SystemExit("GITHUB_TOKEN and --repo (or GITHUB_REPOSITORY) are required")
    body = open(args.file, encoding="utf-8").read()
    marker = args.marker or body.splitlines()[0]
    if not marker.startswith("<!--") or marker not in body:
        raise SystemExit("The comment must carry a marker (an HTML comment on its first line) so it can be found again.")
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    action, comment = upsert(api, args.repo, args.pr, token, marker, body)
    print(f"{action} comment {comment['id']}: {comment['html_url']}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"FlakeGuard comment {action}: {comment['html_url']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
