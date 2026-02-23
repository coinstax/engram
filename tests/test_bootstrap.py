"""Tests for the git bootstrapper."""

import subprocess
from pathlib import Path

import pytest

from engram.bootstrap import GitBootstrapper
from engram.models import EventType


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with known commits."""
    repo = tmp_path / "test-repo"
    repo.mkdir()

    def run_git(*args):
        subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
            env={"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com",
                 "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
        )

    run_git("init")
    run_git("config", "user.name", "Test")
    run_git("config", "user.email", "t@t.com")

    # Commit 1: regular mutation
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')")
    run_git("add", ".")
    run_git("commit", "-m", "Initial commit with main module")

    # Commit 2: bug fix
    (repo / "src" / "auth.py").write_text("def login(): pass")
    run_git("add", ".")
    run_git("commit", "-m", "Fix authentication bug in login flow")

    # Commit 3: refactor
    (repo / "src" / "api.py").write_text("def handle(): pass")
    run_git("add", ".")
    run_git("commit", "-m", "Refactor API handler for clarity")

    # Add a README
    (repo / "README.md").write_text("# Test Project\n\nA test project for Engram.")
    run_git("add", ".")
    run_git("commit", "-m", "Add README")

    return repo


class TestGitBootstrapper:

    def test_not_a_git_repo(self, tmp_path):
        with pytest.raises(ValueError, match="Not a git repository"):
            GitBootstrapper(tmp_path)

    def test_mine_history(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history(max_commits=10)
        assert len(events) >= 4  # 4 commits + README doc

    def test_commit_classification_fix(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history()
        fix_events = [e for e in events if "Fixed:" in e.content]
        assert len(fix_events) >= 1
        assert fix_events[0].event_type == EventType.DISCOVERY

    def test_commit_classification_refactor(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history()
        refactor_events = [e for e in events if "Refactored:" in e.content]
        assert len(refactor_events) >= 1
        assert refactor_events[0].event_type == EventType.DECISION

    def test_commit_classification_mutation(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history()
        mutation_events = [e for e in events if e.event_type == EventType.MUTATION]
        assert len(mutation_events) >= 1

    def test_project_docs_extracted(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history()
        doc_events = [e for e in events if "README.md" in e.content]
        assert len(doc_events) >= 1
        assert "Test Project" in doc_events[0].content

    def test_detect_project_name_directory(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        name = bootstrapper.detect_project_name()
        assert name == "test-repo"

    def test_all_events_have_types(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history()
        for e in events:
            assert e.event_type in EventType
            assert e.agent_id == "git-bootstrap"

    def test_scope_populated(self, git_repo):
        bootstrapper = GitBootstrapper(git_repo)
        events = bootstrapper.mine_history()
        commit_events = [e for e in events if e.agent_id == "git-bootstrap"
                         and "README.md" not in (e.content or "")]
        # At least some commit events should have scope (file paths)
        with_scope = [e for e in commit_events if e.scope]
        assert len(with_scope) >= 1
