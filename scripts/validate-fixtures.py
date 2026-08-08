from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "contract-fixtures" / "regression-corpus.json"
SCENARIO_DOC = ROOT / "docs" / "05-regression-scenarios.md"

CASE_ID = re.compile(r"^[A-Z]+-[0-9]{3}$")
DOC_CASE_ID = re.compile(r"^###\s+([A-Z]+-[0-9]{3})\s+·", re.MULTILINE)
PRIORITIES = {"P0", "P1", "P2"}
CATEGORIES = {
    "ROLE",
    "EXPERIENCE",
    "SOURCE",
    "REQUIREMENT",
    "FIT",
    "ROADMAP",
    "ASYNC",
    "UI",
    "SECURITY",
}
FIXTURE_TYPES = {"USER_PROVIDED_EXCERPT", "SYNTHETIC_MINIMAL", "STATE_SCENARIO"}
PROVENANCE_KINDS = {
    "USER_REPORTED_REGRESSION",
    "USER_PROVIDED_SOURCE",
    "PRODUCT_DECISION",
}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_case(case: Any, index: int, errors: list[str]) -> str | None:
    prefix = f"cases[{index}]"
    require(isinstance(case, dict), f"{prefix}: object required", errors)
    if not isinstance(case, dict):
        return None

    required = {
        "id",
        "priority",
        "category",
        "title",
        "fixtureType",
        "input",
        "expected",
        "forbidden",
        "provenance",
    }
    missing = required - case.keys()
    extra = case.keys() - (required | {"notes"})
    require(not missing, f"{prefix}: missing {sorted(missing)}", errors)
    require(not extra, f"{prefix}: unknown fields {sorted(extra)}", errors)

    case_id = case.get("id")
    require(isinstance(case_id, str) and CASE_ID.fullmatch(case_id or "") is not None,
            f"{prefix}.id: invalid", errors)
    require(case.get("priority") in PRIORITIES, f"{prefix}.priority: invalid", errors)
    require(case.get("category") in CATEGORIES, f"{prefix}.category: invalid", errors)
    require(case.get("fixtureType") in FIXTURE_TYPES, f"{prefix}.fixtureType: invalid", errors)
    require(isinstance(case.get("title"), str) and bool(case.get("title", "").strip()),
            f"{prefix}.title: non-empty string required", errors)
    require(isinstance(case.get("input"), dict), f"{prefix}.input: object required", errors)
    require(isinstance(case.get("expected"), dict) and bool(case.get("expected")),
            f"{prefix}.expected: non-empty object required", errors)
    require(isinstance(case.get("forbidden"), list), f"{prefix}.forbidden: array required", errors)

    provenance = case.get("provenance")
    require(isinstance(provenance, dict), f"{prefix}.provenance: object required", errors)
    if isinstance(provenance, dict):
        require(provenance.get("kind") in PROVENANCE_KINDS,
                f"{prefix}.provenance.kind: invalid", errors)
        require(isinstance(provenance.get("reference"), str)
                and bool(provenance.get("reference", "").strip()),
                f"{prefix}.provenance.reference: non-empty string required", errors)
        require(isinstance(provenance.get("containsPersonalData"), bool),
                f"{prefix}.provenance.containsPersonalData: boolean required", errors)

    expected_category = case_id.split("-", 1)[0] if isinstance(case_id, str) else None
    category_alias = {"EXP": "EXPERIENCE", "REQ": "REQUIREMENT", "MAP": "ROADMAP",
                      "ASYNC": "ASYNC", "SRC": "SOURCE", "FIT": "FIT",
                      "ROLE": "ROLE", "UI": "UI", "SEC": "SECURITY"}
    require(category_alias.get(expected_category) == case.get("category"),
            f"{prefix}: id/category mismatch", errors)
    return case_id if isinstance(case_id, str) else None


def main() -> int:
    errors: list[str] = []
    try:
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"fixture corpus load failed: {exc}", file=sys.stderr)
        return 1

    require(isinstance(corpus, dict), "corpus: object required", errors)
    if not isinstance(corpus, dict):
        return 1
    require(corpus.get("schemaVersion") == "1.0", "schemaVersion must be 1.0", errors)
    require(set(corpus.keys()) == {"schemaVersion", "cases"},
            "corpus fields must be schemaVersion and cases", errors)
    cases = corpus.get("cases")
    require(isinstance(cases, list) and bool(cases), "cases: non-empty array required", errors)
    if not isinstance(cases, list):
        cases = []

    case_ids = [case_id for index, case in enumerate(cases)
                if (case_id := validate_case(case, index, errors))]
    duplicates = [case_id for case_id, count in Counter(case_ids).items() if count > 1]
    require(not duplicates, f"duplicate case ids: {duplicates}", errors)

    try:
        documented_ids = DOC_CASE_ID.findall(SCENARIO_DOC.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"scenario document load failed: {exc}")
        documented_ids = []

    corpus_set = set(case_ids)
    documented_set = set(documented_ids)
    require(corpus_set == documented_set,
            "corpus/document mismatch: "
            f"missing_in_corpus={sorted(documented_set - corpus_set)}, "
            f"missing_in_document={sorted(corpus_set - documented_set)}",
            errors)

    p0_count = sum(1 for case in cases if isinstance(case, dict) and case.get("priority") == "P0")
    require(p0_count > 0, "at least one P0 case required", errors)
    personal_count = sum(
        1 for case in cases
        if isinstance(case, dict)
        and isinstance(case.get("provenance"), dict)
        and case["provenance"].get("containsPersonalData") is True
    )
    require(personal_count == 0, "fixture corpus must not contain personal data", errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        "fixture validation passed: "
        f"cases={len(cases)}, p0={p0_count}, documented={len(documented_ids)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
