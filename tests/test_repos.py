"""Tests for resolving a repository spec and discovering its tests.

The live panel takes a repository from a text box, so this module decides
what a user-supplied string is allowed to make the server do. The tests that
matter most here are the ones about what it must *not* do: no shell, no
arbitrary scheme, no importing the repository it just downloaded.

Nothing here reaches the network — cloning is covered by driving the UI, not
by a unit test that would fail on a train.
"""

import subprocess
from pathlib import Path

import pytest

from flakeguard.app import repos

# --------------------------------------------------------- what is a URL


@pytest.mark.parametrize(
    "spec",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "http://gitlab.example.com/group/project.git",
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo/",
    ],
)
def test_clone_urls_are_recognised(spec):
    assert repos.looks_like_url(spec)


@pytest.mark.parametrize(
    "spec",
    [
        ".",
        "../cachetools",
        "/home/me/project",
        "C:/Users/me/project",
        "",
        "   ",
        # Schemes that are not ours to hand to git.
        "file:///etc/passwd",
        "ext::sh -c whoami",
        "ssh://evil/repo",
        "--upload-pack=touch /tmp/pwned",
        "-u evil",
    ],
)
def test_everything_else_is_not_a_url(spec):
    """A spec that is not clearly http(s)/ssh-shorthand is treated as a path.

    ``ext::`` and ``--upload-pack`` are the two classic git-argument tricks;
    neither must ever reach a clone.
    """
    assert not repos.looks_like_url(spec)


def test_a_flag_shaped_spec_is_refused_as_a_path(tmp_path, monkeypatch):
    monkeypatch.setattr(repos, "REPO_ROOT", tmp_path)
    with pytest.raises(repos.RepoError) as err:
        repos.resolve("--upload-pack=whoami")
    assert "not a directory" in str(err.value)


def test_clone_never_goes_through_a_shell(monkeypatch):
    """git is invoked with an argument list, and user input comes after --,
    so a URL cannot be read as a flag."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["shell"] = kwargs.get("shell", False)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(repos.subprocess, "run", fake_run)
    repos._git(["clone", "--depth", "1", "--", "https://example.com/x", "/tmp/x"])

    assert isinstance(seen["args"], list), "git must not be given a string"
    assert seen["shell"] is False
    assert "--" in seen["args"], "user-supplied values must follow --"
    assert seen["args"].index("--") < seen["args"].index("https://example.com/x")


def test_clone_disables_credential_prompts(monkeypatch):
    """A private repo must fail fast, not hang the request on a prompt."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["env"] = kwargs.get("env", {})
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(repos.subprocess, "run", fake_run)
    repos._git(["status"])
    assert seen["env"].get("GIT_TERMINAL_PROMPT") == "0"


def test_a_git_failure_becomes_a_message_a_person_can_act_on(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 128, stdout="", stderr="remote: Repository not found.\nfatal: could not read"
        )

    monkeypatch.setattr(repos.subprocess, "run", fake_run)
    with pytest.raises(repos.RepoError) as err:
        repos._git(["clone", "--", "https://example.com/nope", "/tmp/x"])
    assert err.value.hint, "a failure with no hint leaves the user stuck"


# ------------------------------------------------------------ cache slugs


@pytest.mark.parametrize(
    "url,expected_name",
    [
        ("https://github.com/Sam2126/Emma--Smart-Agent-.git", "Emma--Smart-Agent-"),
        ("https://github.com/tkem/cachetools", "cachetools"),
        ("git@github.com:owner/repo.git", "repo"),
    ],
)
def test_slug_keeps_the_repository_name(url, expected_name):
    subdir, name = repos.slug_for(url)
    assert name == expected_name
    assert ".." not in subdir, "a slug must not be able to climb out of the cache"
    assert not subdir.startswith("/")


def test_slug_cannot_escape_the_cache_directory():
    """A hostile URL must not place the clone outside .cache/repos."""
    subdir, _ = repos.slug_for("https://evil/../../../../etc/passwd")
    target = (repos.CACHE / subdir).resolve()
    assert repos.CACHE.resolve() in target.parents or target == repos.CACHE.resolve()


# -------------------------------------------------------------- local paths


def test_a_local_directory_resolves_to_itself(tmp_path):
    resolved = repos.resolve(str(tmp_path))
    assert resolved.kind == "local"
    assert resolved.path == tmp_path.resolve()


def test_a_missing_directory_says_so(tmp_path):
    with pytest.raises(repos.RepoError) as err:
        repos.resolve(str(tmp_path / "nope"))
    assert "not a directory" in str(err.value)
    assert "URL" in err.value.hint, "the hint should mention the other option"


def test_an_empty_spec_is_refused():
    with pytest.raises(repos.RepoError):
        repos.resolve("")


# --------------------------------------------------------------- discovery


def test_discovers_module_and_class_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(
        "import pytest\n\n\n"
        "def test_one():\n    assert True\n\n\n"
        "async def test_two():\n    assert True\n\n\n"
        "def helper():\n    return 1\n\n\n"
        "class TestGroup:\n"
        "    def test_three(self):\n        assert True\n\n"
        "    def helper(self):\n        return 2\n\n\n"
        "class NotATestClass:\n"
        "    def test_four(self):\n        assert True\n",
        encoding="utf-8",
    )
    found = {t["test_id"] for t in repos.discover_tests(tmp_path)}
    assert found == {
        "tests/test_sample.py::test_one",
        "tests/test_sample.py::test_two",
        "tests/test_sample.py::TestGroup::test_three",
    }, found


def test_discovery_skips_vendored_directories(tmp_path):
    for vendor in (".venv/Lib/site-packages/pkg", "node_modules/thing", ".tox/py312"):
        d = tmp_path / vendor
        d.mkdir(parents=True)
        (d / "test_vendor.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ours.py").write_text(
        "def test_ours():\n    pass\n", encoding="utf-8"
    )

    found = [t["test_id"] for t in repos.discover_tests(tmp_path)]
    assert found == ["tests/test_ours.py::test_ours"]


def test_discovery_survives_a_file_it_cannot_parse(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_broken.py").write_text(
        "def test_a(:\n  syntax error\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_fine.py").write_text(
        "def test_b():\n    pass\n", encoding="utf-8"
    )
    found = [t["test_id"] for t in repos.discover_tests(tmp_path)]
    assert found == ["tests/test_fine.py::test_b"]


def test_discovery_does_not_import_the_repository(tmp_path):
    """Parsing, never importing. A cloned repo is untrusted code.

    If discovery imported what it found, this module's side effect would
    happen; it must not.
    """
    (tmp_path / "tests").mkdir()
    marker = tmp_path / "IMPORTED"
    (tmp_path / "tests" / "test_evil.py").write_text(
        f"from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n\n\n"
        f"def test_x():\n    pass\n",
        encoding="utf-8",
    )
    found = [t["test_id"] for t in repos.discover_tests(tmp_path)]
    assert found == ["tests/test_evil.py::test_x"]
    assert not marker.exists(), "discovery executed the repository's code"


def test_discovery_respects_its_limit(tmp_path):
    (tmp_path / "tests").mkdir()
    body = "\n\n".join(f"def test_{i}():\n    pass" for i in range(50))
    (tmp_path / "tests" / "test_many.py").write_text(body, encoding="utf-8")
    assert len(repos.discover_tests(tmp_path, limit=10)) == 10


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil/../../../../etc/passwd",
        "https://evil/..%2f..%2fx",
        "https://evil/./././x",
        "https://evil/../.git/hooks",
        "git@evil:../../x.git",
    ],
)
def test_no_url_can_place_a_clone_outside_the_cache(hostile):
    """Dots survive the character sanitiser, because a repository may legally
    be called `foo.bar` — so `..` has to be dropped separately."""
    subdir, name = repos.slug_for(hostile)
    # The property that matters is where the clone lands, not how the name
    # reads: ".._2f.._2fx" is an ugly but perfectly safe directory name.
    assert ".." not in Path(subdir).parts
    assert ".." not in Path(name).parts
    target = (repos.CACHE / subdir).resolve()
    cache = repos.CACHE.resolve()
    assert cache in target.parents or target == cache, target
