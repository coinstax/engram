"""Garbage collection — archive old events to keep the main store lean."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from engram.store import EventStore


class GarbageCollector:
    """Archives old mutation/outcome events, preserving warnings and decisions."""

    def __init__(self, store: EventStore, engram_dir: Path):
        self.store = store
        self.engram_dir = engram_dir

    def collect(self, max_age_days: int = 90, dry_run: bool = False) -> dict:
        """Archive old mutation/outcome events.

        Warnings and decisions are always preserved regardless of age.

        Returns:
            Dict with keys: archived (int), cutoff (str),
            and optionally archive_path (str).
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).isoformat()

        # Find archivable events (only mutations and outcomes older than cutoff)
        archivable = self.store.conn.execute(
            "SELECT * FROM events "
            "WHERE event_type IN ('mutation', 'outcome') "
            "AND timestamp < ? "
            "ORDER BY timestamp",
            (cutoff,),
        ).fetchall()

        if dry_run:
            return {"archived": 0, "would_archive": len(archivable), "cutoff": cutoff}

        if not archivable:
            return {"archived": 0, "cutoff": cutoff}

        # Create archive DB
        archive_dir = self.engram_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        month = datetime.now().strftime("%Y-%m")
        archive_path = archive_dir / f"{month}.db"

        archive_store = EventStore(archive_path)
        archive_store.initialize()

        # Copy events to archive
        events = [self.store._row_to_event(r) for r in archivable]
        archive_store.insert_batch(events)
        archive_store.close()

        # Delete from main store
        ids = [r["id"] for r in archivable]
        placeholders = ",".join("?" for _ in ids)
        with self.store.conn:
            self.store.conn.execute(
                f"DELETE FROM events WHERE id IN ({placeholders})", ids
            )

        return {
            "archived": len(ids),
            "archive_path": str(archive_path),
            "cutoff": cutoff,
        }
