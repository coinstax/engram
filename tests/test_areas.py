import json
from pathlib import Path

from engram.areas import AreaRule, load_area_map, infer_area


def _write_map(project: Path, rules):
    engram = project / ".engram"
    engram.mkdir(parents=True, exist_ok=True)
    (engram / "areas.json").write_text(json.dumps({"rules": rules}))


def test_load_missing_file_returns_empty(tmp_path):
    assert load_area_map(tmp_path) == []


def test_load_malformed_file_returns_empty(tmp_path):
    engram = tmp_path / ".engram"
    engram.mkdir()
    (engram / "areas.json").write_text("{not json")
    assert load_area_map(tmp_path) == []


def test_load_skips_bad_rules(tmp_path):
    _write_map(tmp_path, [
        {"prefix": "src/billing/", "area": "billing"},
        {"prefix": "src/nope/"},          # missing area -> skipped
        {"area": "orphan"},               # missing prefix -> skipped
        "garbage",                        # not a dict -> skipped
    ])
    rules = load_area_map(tmp_path)
    assert rules == [AreaRule(prefix="src/billing/", area="billing")]


def test_infer_none_when_no_rules_or_scope():
    assert infer_area(None, []) is None
    assert infer_area(["src/a.py"], []) is None
    assert infer_area(None, [AreaRule("src/", "x")]) is None


def test_infer_longest_prefix_wins():
    rules = [
        AreaRule("src/http/", "http"),
        AreaRule("src/http/routes/me/", "account"),
    ]
    assert infer_area(["src/http/routes/me/email.ts"], rules) == "account"


def test_infer_first_matching_path_wins():
    rules = [
        AreaRule("src/billing/", "billing"),
        AreaRule("src/http/", "http"),
    ]
    # First path with any match determines the area.
    assert infer_area(["docs/readme.md", "src/http/x.ts", "src/billing/y.ts"], rules) == "http"


def test_infer_no_match_returns_none():
    assert infer_area(["docs/readme.md"], [AreaRule("src/", "code")]) is None


def test_infer_duplicate_prefix_first_rule_wins():
    # Same prefix listed twice: the tie-break uses strict `>` on prefix
    # length, so the earlier rule wins.
    rules = [AreaRule("src/", "first"), AreaRule("src/", "second")]
    assert infer_area(["src/x.py"], rules) == "first"
