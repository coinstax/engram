"""Auto-context assembly for AI consultations."""

from pathlib import Path

from engram.briefing import BriefingGenerator
from engram.formatting import format_event_compact
from engram.store import EventStore


# Target char budget for assembled context
MAX_CONTEXT_CHARS = 4000
README_MAX_LINES = 60


class ContextAssembler:
    """Assembles project context for injection into consultation system prompts."""

    def __init__(self, store: EventStore, project_dir: Path | None = None):
        self.store = store
        self.project_dir = project_dir or Path.cwd()

    def assemble(
        self,
        topic: str | None = None,
        scope: str | None = None,
        since: str | None = None,
    ) -> str:
        """Build a context string from project metadata, README, and recent events.

        Returns a markdown-formatted string suitable for use as a system prompt.
        """
        sections: list[str] = []

        # Project identity
        project_name = self.store.get_meta("project_name") or "unknown"
        total_events = self.store.count()
        sections.append(f"# Project: {project_name}")
        sections.append(f"Total events in memory: {total_events}")

        # Topic framing
        if topic:
            sections.append(f"\n## Consultation Topic\n{topic}")

        # README excerpt
        readme_text = self._read_readme()
        if readme_text:
            sections.append(f"\n## Project Overview (from README)\n{readme_text}")

        # Source architecture
        arch = self._list_source_modules()
        if arch:
            sections.append(f"\n## Source Modules\n{arch}")

        # Briefing data: warnings, decisions, discoveries
        gen = BriefingGenerator(self.store)
        briefing = gen.generate(scope=scope, since=since)

        if briefing.active_warnings:
            lines = [format_event_compact(e) for e in briefing.active_warnings[:5]]
            sections.append(f"\n## Active Warnings ({len(briefing.active_warnings)})\n" + "\n".join(lines))

        if briefing.recent_decisions:
            lines = [format_event_compact(e) for e in briefing.recent_decisions[:7]]
            sections.append(f"\n## Recent Decisions ({len(briefing.recent_decisions)})\n" + "\n".join(lines))

        if briefing.recent_discoveries:
            lines = [format_event_compact(e) for e in briefing.recent_discoveries[:5]]
            sections.append(f"\n## Recent Discoveries ({len(briefing.recent_discoveries)})\n" + "\n".join(lines))

        if briefing.potentially_stale:
            lines = [format_event_compact(e) for e in briefing.potentially_stale[:3]]
            sections.append(f"\n## Potentially Stale ({len(briefing.potentially_stale)})\n" + "\n".join(lines))

        result = "\n".join(sections)

        # Enforce char budget by trimming README if needed
        if len(result) > MAX_CONTEXT_CHARS:
            result = self._trim_to_budget(sections)

        return result

    def assemble_for_consultation(
        self,
        topic: str,
        models: list[str],
        scope: str | None = None,
        since: str | None = None,
    ) -> str:
        """Assemble context with a consultation role framing prefix.

        Returns a system prompt string ready for use with providers.
        """
        project_name = self.store.get_meta("project_name") or "unknown"
        model_names = ", ".join(models)

        framing = (
            f"You are a technical reviewer consulting on the {project_name} project. "
            f"The host agent (Claude Code) is directing this conversation. "
            f"Other models in this consultation: {model_names}. "
            f"Be concise and specific. Disagree when you see issues."
        )

        context = self.assemble(topic=topic, scope=scope, since=since)
        return f"{framing}\n\n---\n\n{context}"

    def context_summary(self) -> str:
        """Return a one-line summary of what the context contains. For CLI output."""
        gen = BriefingGenerator(self.store)
        briefing = gen.generate()

        readme_exists = (self.project_dir / "README.md").is_file()
        parts = []
        if readme_exists:
            parts.append("README")
        if briefing.active_warnings:
            parts.append(f"{len(briefing.active_warnings)} warnings")
        if briefing.recent_decisions:
            parts.append(f"{len(briefing.recent_decisions)} decisions")
        if briefing.recent_discoveries:
            parts.append(f"{len(briefing.recent_discoveries)} discoveries")

        return ", ".join(parts) if parts else "minimal (no events or README)"

    def _read_readme(self) -> str | None:
        """Read first N lines of README.md, return as string or None."""
        readme_path = self.project_dir / "README.md"
        if not readme_path.is_file():
            return None

        try:
            lines = readme_path.read_text(encoding="utf-8").splitlines()
            excerpt = lines[:README_MAX_LINES]
            return "\n".join(excerpt)
        except (OSError, UnicodeDecodeError):
            return None

    def _list_source_modules(self) -> str | None:
        """List .py files in src/engram/ as a compact architecture overview."""
        src_dir = self.project_dir / "src" / "engram"
        if not src_dir.is_dir():
            return None

        py_files = sorted(f.name for f in src_dir.glob("*.py") if f.name != "__pycache__")
        if not py_files:
            return None

        return ", ".join(py_files)

    def _trim_to_budget(self, sections: list[str]) -> str:
        """Trim context to fit within MAX_CONTEXT_CHARS.

        Strategy: keep all event sections (warnings/decisions/discoveries are high value),
        truncate the README excerpt progressively.
        """
        # Find and progressively shorten the README section
        readme_idx = None
        for i, section in enumerate(sections):
            if "## Project Overview (from README)" in section:
                readme_idx = i
                break

        if readme_idx is not None:
            # Halve README lines until under budget
            readme_section = sections[readme_idx]
            header = "## Project Overview (from README)\n"
            readme_body = readme_section.split(header, 1)[-1]
            readme_lines = readme_body.splitlines()

            while len("\n".join(sections)) > MAX_CONTEXT_CHARS and len(readme_lines) > 5:
                readme_lines = readme_lines[: len(readme_lines) // 2]
                sections[readme_idx] = f"\n{header}" + "\n".join(readme_lines) + "\n[...truncated]"

        result = "\n".join(sections)

        # Last resort: hard truncate
        if len(result) > MAX_CONTEXT_CHARS:
            result = result[:MAX_CONTEXT_CHARS] + "\n[...truncated]"

        return result
