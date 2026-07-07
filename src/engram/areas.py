"""Path->area inference from an optional .engram/areas.json map."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AreaRule:
    prefix: str
    area: str


def load_area_map(project_dir: Path) -> list[AreaRule]:
    """Load area rules from <project_dir>/.engram/areas.json.

    Missing file, unreadable file, malformed JSON, or a bad shape all
    return an empty list — inference is best-effort and never fatal.
    """
    path = Path(project_dir) / ".engram" / "areas.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    rules_raw = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules_raw, list):
        return []
    rules: list[AreaRule] = []
    for r in rules_raw:
        if (isinstance(r, dict)
                and isinstance(r.get("prefix"), str)
                and isinstance(r.get("area"), str)):
            rules.append(AreaRule(prefix=r["prefix"], area=r["area"]))
    return rules


def infer_area(scope: list[str] | None, rules: list[AreaRule]) -> str | None:
    """Infer an area from scope paths using longest-prefix matching.

    For each path in scope order, pick the longest matching prefix. The
    first path that yields a match determines the area. Returns None when
    scope is empty, rules is empty, or nothing matches.
    """
    if not scope or not rules:
        return None
    for path in scope:
        best: AreaRule | None = None
        for rule in rules:
            if path.startswith(rule.prefix):
                if best is None or len(rule.prefix) > len(best.prefix):
                    best = rule
        if best is not None:
            return best.area
    return None
