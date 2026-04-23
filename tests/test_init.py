"""Tests for the shared init helper."""

import subprocess
from pathlib import Path

import pytest

from engram.init import InitResult, perform_init
from engram.store import EventStore


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A bare git project with one commit and a README — no .engram/."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "--allow-empty", "-q", "-m", "initial commit"],
        cwd=tmp_path, check=True,
    )
    (tmp_path / "README.md").write_text("# testproj\n")
    return tmp_path


def test_perform_init_creates_engram_dir_and_db(tmp_path):
    result = perform_init(tmp_path)
    assert isinstance(result, InitResult)
    assert (tmp_path / ".engram" / "events.db").exists()
    assert result.already_initialized is False


def test_perform_init_is_idempotent(tmp_path):
    first = perform_init(tmp_path)
    second = perform_init(tmp_path)
    assert first.already_initialized is False
    assert second.already_initialized is True
    assert second.project_name == first.project_name


def test_perform_init_non_git_project_falls_back_to_dirname(tmp_path):
    result = perform_init(tmp_path)
    assert result.project_name == tmp_path.name
    assert result.events_seeded == 0


def test_perform_init_seeds_from_git_history(git_project):
    result = perform_init(git_project)
    # Git repo has at least one commit; bootstrapper mines it plus docs.
    assert result.events_seeded >= 1
    assert result.already_initialized is False


def test_perform_init_does_not_touch_claude_md(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Pre-existing content\n")
    pre = claude_md.read_text()

    perform_init(tmp_path)

    assert claude_md.read_text() == pre


def test_perform_init_does_not_create_claude_md(tmp_path):
    perform_init(tmp_path)
    assert not (tmp_path / "CLAUDE.md").exists()


def test_perform_init_sets_project_name_and_initialized_at(tmp_path):
    perform_init(tmp_path)
    store = EventStore(tmp_path / ".engram" / "events.db")
    try:
        assert store.get_meta("project_name") == tmp_path.name
        assert store.get_meta("initialized_at") is not None
    finally:
        store.close()
