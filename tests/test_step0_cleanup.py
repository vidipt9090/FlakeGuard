"""Test repo cleanup for Eval 3 Step 0."""

from pathlib import Path


def test_flakeguard_packages_importable():
    """Verify that consolidated packages under flakeguard import directly."""
    from flakeguard.analysis import failure_log
    from flakeguard.llm import run_prompts

    assert hasattr(failure_log, "generate_failure_log")
    assert hasattr(run_prompts, "run_llm_prompts")


def test_archived_files_exist():
    """Verify that archived historical files exist under docs/archive/."""
    root = Path(__file__).parent.parent
    archive_dir = root / "docs" / "archive"

    assert (archive_dir / "PERSON_A.md").is_file()
    assert (archive_dir / "CONFIG.md").is_file()
    assert (archive_dir / "setup-laptop1.md").is_file()


def test_package_readmes_exist():
    """Verify that skeleton packages carry an informative one-line README."""
    root = Path(__file__).parent.parent
    packages = ["actions", "baselines", "cluster", "collector", "monitor", "reproduce"]

    for pkg in packages:
        readme = root / "flakeguard" / pkg / "README.md"
        assert readme.is_file(), f"Missing README in flakeguard/{pkg}"
        assert len(readme.read_text(encoding="utf-8").strip()) > 0

