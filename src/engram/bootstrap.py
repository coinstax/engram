"""Git history mining and seed event generation."""

import re
import subprocess
from pathlib import Path

from engram.models import Event, EventType

FIX_PATTERN = re.compile(r"\b(fix|bug|patch|resolve|hotfix|repair)\b", re.IGNORECASE)
REFACTOR_PATTERN = re.compile(
    r"\b(refactor|restructure|migrate|rewrite|redesign|overhaul|reorganize)\b",
    re.IGNORECASE,
)

# Null byte as delimiter to handle | in commit subjects
GIT_LOG_FORMAT = "%H%x00%aI%x00%an%x00%s"
SEPARATOR = "\x00"


class GitBootstrapper:
    """Mines git history and project docs to generate seed events."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        if not (project_dir / ".git").exists():
            raise ValueError(f"Not a git repository: {project_dir}")

    def mine_history(self, max_commits: int = 100) -> list[Event]:
        """Parse git log and project docs into seed events."""
        events = []
        events.extend(self._parse_commits(max_commits))
        events.extend(self._extract_project_docs())
        return events

    def _run_git(self, *args: str) -> str:
        """Run a git command and return stdout."""
        result = subprocess.run(
            ["git", *args],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout

    def _parse_commits(self, max_commits: int) -> list[Event]:
        """Parse git log into events."""
        raw = self._run_git(
            "log", f"--pretty=format:{GIT_LOG_FORMAT}", "--name-only",
            f"-n{max_commits}",
        )

        if not raw.strip():
            return []

        events = []
        # Split by double newline (separates commits with their file lists)
        blocks = raw.strip().split("\n\n")

        for block in blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue

            # First line is the formatted commit info
            parts = lines[0].split(SEPARATOR)
            if len(parts) < 4:
                continue

            commit_hash, date, author, subject = parts[0], parts[1], parts[2], parts[3]

            # Remaining lines are file paths
            files = [l.strip() for l in lines[1:] if l.strip()]

            event_type, content = self._classify_commit(subject, files)

            scope = files[:10] if files else None

            events.append(Event(
                id="",
                timestamp=date,
                event_type=event_type,
                agent_id="git-bootstrap",
                content=content[:2000],
                scope=scope,
            ))

        return events

    def _classify_commit(self, subject: str, files: list[str]) -> tuple[EventType, str]:
        """Classify a commit into an event type and summarized content."""
        if FIX_PATTERN.search(subject):
            return EventType.DISCOVERY, f"Fixed: {subject}"

        if len(files) >= 10 or REFACTOR_PATTERN.search(subject):
            file_note = f" ({len(files)} files)" if len(files) >= 10 else ""
            return EventType.DECISION, f"Refactored: {subject}{file_note}"

        return EventType.MUTATION, subject

    def _extract_project_docs(self) -> list[Event]:
        """Read README and CLAUDE.md to generate discovery events."""
        events = []

        for filename in ("README.md", "CLAUDE.md"):
            filepath = self.project_dir / filename
            if filepath.exists():
                try:
                    text = filepath.read_text(encoding="utf-8", errors="replace")
                    # Take first 1800 chars to leave room for prefix
                    truncated = text[:1800]
                    if len(text) > 1800:
                        truncated += "... (truncated)"
                    events.append(Event(
                        id="",
                        timestamp="",
                        event_type=EventType.DISCOVERY,
                        agent_id="git-bootstrap",
                        content=f"Project {filename}: {truncated}",
                        scope=[filename],
                    ))
                except Exception:
                    pass

        return events

    def detect_project_name(self) -> str:
        """Detect project name from git remote, config files, or directory name."""
        # Try git remote
        remote = self._run_git("remote", "get-url", "origin").strip()
        if remote:
            # Extract repo name from URL
            name = remote.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return name

        # Try pyproject.toml
        pyproject = self.project_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text()
                for line in text.splitlines():
                    if line.strip().startswith("name"):
                        match = re.search(r'"([^"]+)"', line)
                        if match:
                            return match.group(1)
            except Exception:
                pass

        # Try package.json
        pkg = self.project_dir / "package.json"
        if pkg.exists():
            try:
                import json
                data = json.loads(pkg.read_text())
                if "name" in data:
                    return data["name"]
            except Exception:
                pass

        # Fallback to directory name
        return self.project_dir.name
