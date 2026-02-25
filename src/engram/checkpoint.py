"""Checkpoint — context save/restore integration with Engram events."""

import re
from pathlib import Path

from engram.briefing import BriefingGenerator
from engram.formatting import format_event_compact, format_briefing_compact
from engram.models import Checkpoint, EventType
from engram.store import EventStore


# Sections in context markdown that can be enriched, mapped to event types
ENRICHABLE_SECTIONS = {
    "Key Design Decisions": EventType.DECISION,
    "Design Decisions": EventType.DECISION,
    "Known Issues": EventType.WARNING,
    "Technical Debt": EventType.WARNING,
    "Known Issues / Technical Debt": EventType.WARNING,
    "Recent Discoveries": EventType.DISCOVERY,
    "Discoveries": EventType.DISCOVERY,
}

# HTML comment markers for Engram-injected content
ENGRAM_START = "<!-- engram:start -->"
ENGRAM_END = "<!-- engram:end -->"


class CheckpointEngine:
    """Handles context file enrichment and checkpoint recording."""

    def __init__(self, store: EventStore, project_dir: Path | None = None):
        self.store = store
        self.project_dir = project_dir or Path.cwd()

    def save(
        self,
        file_path: str,
        agent_id: str = "cli",
        enrich: bool = True,
        session_id: str | None = None,
    ) -> Checkpoint:
        """Save a checkpoint: record it and optionally enrich the context file.

        Args:
            file_path: Path to the context markdown file
            agent_id: Who is creating this checkpoint
            enrich: Whether to enrich the file with Engram events (default: True)
            session_id: Optional session to link this checkpoint to

        Returns:
            The saved Checkpoint record
        """
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"Context file not found: {file_path}")

        enriched_sections = []
        if enrich:
            enriched_sections = self._enrich_file(path)

        checkpoint = Checkpoint(
            id="",
            file_path=str(path),
            agent_id=agent_id,
            created_at="",
            event_count_at_creation=0,
            enriched_sections=enriched_sections or None,
            session_id=session_id,
        )
        return self.store.save_checkpoint(checkpoint)

    def restore(
        self,
        checkpoint_id: str | None = None,
        since: str | None = None,
        scope: str | None = None,
        focus: str | None = None,
    ) -> str:
        """Generate a full briefing combining checkpoint context + recent activity.

        If checkpoint_id is None, uses the latest checkpoint.
        Returns a markdown string combining static context + dynamic briefing.
        """
        if checkpoint_id:
            checkpoint = self.store.get_checkpoint(checkpoint_id)
        else:
            checkpoint = self.store.get_latest_checkpoint()

        sections = []

        # Part 1: Static context from the checkpoint file
        if checkpoint:
            path = Path(checkpoint.file_path)
            if path.is_file():
                content = path.read_text(encoding="utf-8")
                sections.append(
                    f"# Saved Context (checkpoint {checkpoint.id}, "
                    f"{checkpoint.created_at[:16].replace('T', ' ')} UTC)"
                )
                sections.append("")
                sections.append(content)
            else:
                sections.append(f"# Checkpoint {checkpoint.id}")
                sections.append(
                    f"Warning: Context file not found at {checkpoint.file_path}"
                )

            # Use checkpoint timestamp as the "since" for dynamic section
            if not since:
                since = checkpoint.created_at
        else:
            sections.append("# No checkpoint found")
            sections.append("Showing full dynamic briefing instead.")

        # Part 2: Dynamic recent activity since checkpoint
        sections.append("")
        sections.append("---")
        sections.append("")
        sections.append("# Activity Since Checkpoint")
        sections.append("")

        gen = BriefingGenerator(self.store)
        briefing_result = gen.generate(scope=scope, since=since, focus=focus)
        dynamic = format_briefing_compact(briefing_result)
        sections.append(dynamic)

        return "\n".join(sections)

    def _enrich_file(self, path: Path) -> list[str]:
        """Enrich a context markdown file with Engram events.

        Finds sections that map to event types and appends any events
        that aren't already mentioned in the section content.

        Returns list of section names that were enriched.
        """
        content = path.read_text(encoding="utf-8")
        enriched = []

        for section_name, event_type in ENRICHABLE_SECTIONS.items():
            # Find section in the markdown (## heading to next ## or end of file)
            pattern = rf"(## {re.escape(section_name)}.*?)(\n## |\Z)"
            match = re.search(pattern, content, re.DOTALL)
            if not match:
                continue

            section_text = match.group(1)

            # Get recent active events of this type
            events = self.store.recent_by_type(event_type, limit=10, status="active")
            if not events:
                continue

            # Filter to events not already mentioned in the section
            new_events = []
            for event in events:
                # Check if the event content (or a significant prefix) appears
                check_text = event.content[:80]
                if check_text not in section_text:
                    new_events.append(event)

            if not new_events:
                continue

            # Remove previous enrichment block if present
            cleanup_pattern = (
                rf"(## {re.escape(section_name)}.*?)"
                rf"{re.escape(ENGRAM_START)}.*?{re.escape(ENGRAM_END)}\n?"
            )
            content = re.sub(cleanup_pattern, r"\1", content, flags=re.DOTALL)

            # Build enrichment block
            lines = [ENGRAM_START]
            lines.append(f"*Enriched by Engram ({len(new_events)} events):*")
            for event in new_events:
                lines.append(f"- {format_event_compact(event)}")
            lines.append(ENGRAM_END)
            enrichment = "\n".join(lines)

            # Re-find the section after cleanup and insert enrichment at end
            match = re.search(pattern, content, re.DOTALL)
            if match:
                insert_pos = match.end(1)
                content = (
                    content[:insert_pos] + "\n" + enrichment + "\n"
                    + content[insert_pos:]
                )
                enriched.append(section_name)

        if enriched:
            path.write_text(content, encoding="utf-8")

        return enriched
