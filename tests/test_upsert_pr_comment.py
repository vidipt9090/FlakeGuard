"""The PR comment is created once and then edited in place, never duplicated."""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "upsert_pr_comment.py"
spec = importlib.util.spec_from_file_location("upsert_pr_comment", SCRIPT)
upsert_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upsert_module)

MARKER = "<!-- flakeguard-pr-comment -->"


class FakeGitHub:
    """Just enough of the issue comments API: list (paged), create, edit."""

    def __init__(self, page_size: int = 100) -> None:
        self.comments: list[dict] = []
        self.requests: list[tuple[str, str]] = []
        self.page_size = page_size
        self.next_id = 100
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def _send(self, status: int, payload, headers: dict | None = None):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append(("GET", self.path))
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                page = int(query.get("page", ["1"])[0])
                start = (page - 1) * outer.page_size
                chunk = outer.comments[start:start + outer.page_size]
                headers = {}
                if start + outer.page_size < len(outer.comments):
                    headers["Link"] = f'<http://127.0.0.1:{outer.port}/repos/o/r/issues/7/comments?per_page=100&page={page + 1}>; rel="next"'
                self._send(200, chunk, headers)

            def do_POST(self):
                outer.requests.append(("POST", self.path))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                comment = {"id": outer.next_id, "body": body["body"], "user": {"login": "github-actions[bot]"},
                           "html_url": f"https://github.test/c/{outer.next_id}"}
                outer.next_id += 1
                outer.comments.append(comment)
                self._send(201, comment)

            def do_PATCH(self):
                outer.requests.append(("PATCH", self.path))
                cid = int(self.path.rsplit("/", 1)[1])
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                comment = next(c for c in outer.comments if c["id"] == cid)
                comment["body"] = body["body"]
                self._send(200, comment)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def human(self, body: str) -> None:
        self.comments.append({"id": self.next_id, "body": body, "user": {"login": "someone"}, "html_url": "x"})
        self.next_id += 1

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def gh():
    g = FakeGitHub()
    yield g
    g.close()


def post(gh: FakeGitHub, text: str) -> str:
    action, _ = upsert_module.upsert(gh.url, "o/r", 7, "token", MARKER, f"{MARKER}\n{text}")
    return action


def test_first_run_creates_one_comment(gh):
    assert post(gh, "first") == "created"
    assert len(gh.comments) == 1


def test_second_push_edits_the_same_comment_and_does_not_duplicate(gh):
    post(gh, "first")
    first_id = gh.comments[0]["id"]
    assert post(gh, "second") == "updated"
    assert post(gh, "third") == "updated"
    assert len(gh.comments) == 1
    assert gh.comments[0]["id"] == first_id and gh.comments[0]["body"].endswith("third")
    assert [m for m, _ in gh.requests].count("POST") == 1


def test_a_comment_written_by_a_person_is_never_edited(gh):
    gh.human(f"{MARKER}\nA person quoting the marker")
    assert post(gh, "mine") == "created"
    assert len(gh.comments) == 2
    assert gh.comments[0]["body"].endswith("A person quoting the marker")


def test_finds_the_comment_on_a_later_page():
    g = FakeGitHub(page_size=2)
    try:
        for i in range(5):
            g.human(f"unrelated {i}")
        g.comments.append({"id": 999, "body": f"{MARKER}\nold", "user": {"login": "github-actions[bot]"}, "html_url": "x"})
        assert post(g, "new") == "updated"
        assert g.comments[-1]["body"].endswith("new") and len(g.comments) == 6
    finally:
        g.close()


def test_marker_is_required_so_the_comment_can_be_found_again(tmp_path, monkeypatch):
    f = tmp_path / "c.md"
    f.write_text("no marker here", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    with pytest.raises(SystemExit, match="marker"):
        upsert_module.main(["--file", str(f), "--repo", "o/r", "--pr", "7"])


def test_api_errors_are_not_swallowed(monkeypatch, tmp_path):
    f = tmp_path / "c.md"
    f.write_text(f"{MARKER}\nbody", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:9")  # nothing listens here
    with pytest.raises(Exception):
        upsert_module.main(["--file", str(f), "--repo", "o/r", "--pr", "7"])
