# Design — `area` tag for events (schema v6)

**Date:** 2026-07-06
**Branch:** `v1.7-plugin` (or a follow-on branch)
**Status:** Approved design, pending implementation plan

## Problem

Engram events carry a single `scope: list[str]` field. In practice it is
overloaded with two different meanings:

- **File paths** — what files an event touched (hooks auto-fill this with exact
  paths; e.g. `src/http/routes/me/email.ts`).
- **Area labels** — the conceptual component/feature an event belongs to (set by
  hand; e.g. `auth`, `billing`).

Because the concept only exists implicitly inside the file list, "show me
everything about the email-change work" is not reliably queryable. Two failure
modes observed in real use:

1. **Concept spans unrelated files.** The email-change feature spanned
   `.../me/email.ts`, `.../lib/rate-limit.ts`, a Svelte settings page, and
   migrations across two repos over sessions 43–45. No single file appears in
   every event, so a file-overlap query on any one path recalls only a slice.
   Reconstructing the feature meant eyeballing the whole briefing.
2. **Shared file conflates features.** `rate-limit.ts` is touched by both the
   email-change cooldown and (specced) outbound-abuse-controls work. A file-path
   query on it conflates two unrelated features.

## Decision

Add **one optional `area` string** per event, distinct from `scope`. Keep
`scope` as file paths only (stop overloading it — that overload is the bug).
Default `area` from a path→area map so it populates without discipline, and let
it be set explicitly to override. Make briefing and query aware of it.

Rejected: two separate `files_changed`/`area` fields (over-reach — a single
well-populated tag beats two half-populated fields); read-time derivation with no
stored column (can't store an explicit tag, so it fails failure-mode 1 where the
concept has no common file).

### Cardinality

`area` is a **single nullable string**, not a list. One event = one area. Matches
the observed usage (each event maps to one concept) and avoids reintroducing the
multi-value fuzziness the split is meant to escape.

## Architecture

### 1. Model + schema

- `Event.area: str | None = None` — new dataclass field in `models.py`, placed
  after `scope`.
- Schema **v6**: `ALTER TABLE events ADD COLUMN area TEXT`. Added to the existing
  auto-migration ladder in `store.py`. Nullable, no default.
- `scope` is documented as file-paths-only going forward. Not enforced; existing
  data is left untouched.

### 2. Path→area map — `.engram/areas.json`

Shape:

```json
{
  "rules": [
    { "prefix": "src/http/routes/me/", "area": "account" },
    { "prefix": "src/billing/",        "area": "billing" }
  ]
}
```

- **Matching:** for each path in `scope`, find the longest `prefix` that the path
  starts with. The first path (in `scope` order) that yields a match sets the
  area. Longest-prefix wins on ties within a single path.
- The file is **optional**. Absent or empty `rules` → no inference (area stays
  whatever was passed, else `None`).
- New module `src/engram/areas.py`, pure and DB-free:
  - `load_area_map(project_dir: Path) -> list[AreaRule]` — reads and validates
    `areas.json`; missing file → `[]`.
  - `infer_area(scope: list[str] | None, rules: list[AreaRule]) -> str | None`.

`AreaRule` is a small dataclass (`prefix: str`, `area: str`).

### 3. Post path (CLI + MCP)

Precedence when creating an event:

1. Explicit `area` argument, if given.
2. Else `infer_area(scope, load_area_map(project_dir))`.
3. Else `None`.

- CLI `post`: add `--area` / `-A`.
- MCP `post_event`: add `area: str | None = None` parameter.

The area is resolved **at insert time** and frozen — not recomputed on read, so
later edits to `areas.json` don't retroactively change stored events (predictable,
and mirrors how `scope` behaves).

### 4. Migration backfill (v5 → v6)

On upgrade:

1. `ALTER TABLE events ADD COLUMN area TEXT`.
2. Load `areas.json` if present. For each existing event, run `infer_area` over
   its `scope` and write the result. No match, or no map file → leave `NULL`.

`scope` is never modified. Backfill is idempotent (re-running yields the same
result for a given map). If `areas.json` is absent at migration time, all rows
stay `NULL` and can be populated later by re-posting or a future re-index command
(out of scope here).

### 5. Read surface

- **Query:** `QueryFilter.area: str | None`; `query.py` + `store.py` add an
  exact-match `WHERE area = ?` condition. Surfaced as CLI `query --area` and MCP
  `query(area=...)`.
- **FTS:** include `area` in the FTS5 index (extend the insert trigger at
  `store.py:49` and rebuild the FTS table during migration) so free-text search
  also matches on area.
- **Briefing — focus-key match:** when a focus/scope value names an area,
  briefing's focus-relevant section matches events by `area` in addition to the
  existing file-overlap logic (`briefing.py` focus-relevance path). No new
  section, no change to the 4-section structure — area becomes an additional
  matchable focus key. A dedicated "By area" briefing section is explicitly out
  of scope for this pass.

### 6. Testing

- `tests/test_areas.py` — `load_area_map` (present / missing / malformed file),
  `infer_area` (longest-prefix, first-path-wins, no-match, empty scope, empty
  rules).
- Migration test — seed a v5 DB, migrate to v6, assert: `area` column exists,
  backfill values correct given a map, `scope` unchanged, idempotent on re-run,
  and NULL-everywhere when no map file.
- CLI + MCP post — explicit area wins over inference; inference fills when area
  omitted; `None` when neither.
- Query — `--area` / `area=` exact filter; FTS free-text hit on an area value.
- Briefing — event tagged with an area surfaces under focus-relevant when focus
  names that area.

## Non-goals (this pass)

- Splitting into two fields (`files_changed` + `area`) — rejected above.
- A dedicated "By area" briefing section.
- A re-index / bulk re-tag CLI command for events posted before a map existed.
- Enforcing that `scope` contains only file paths (kept as documentation-only).
- Multi-area events.

## Version / release notes

- Bumps schema to **v6** (auto-migration).
- Package version bump (1.6.1 → 1.7.0) remains the separate release-commit task;
  this change lands under the same in-progress v1.7.0 CHANGELOG section.
- No breaking API change: `area` is additive and optional on every surface.
