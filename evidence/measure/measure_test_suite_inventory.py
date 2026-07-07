"""Inventory the real test suite: counts, categories, and measured coverage.

This does not estimate — it parses the actual files. Python test functions are
counted by AST (every ``def test_*`` / ``async def test_*``), TypeScript/React
test cases by their ``it(`` / ``test(`` blocks. Tests are bucketed by the rigour
signal in their filename (property / fuzz / determinism / adversarial / injection
/ fail-closed / boundary / race), because CLAUDE.md 3.6 holds that a green suite
of trivial tests is worthless — the mix of hard test kinds is the quality signal.

Line/branch coverage is read from evidence/data/coverage_raw.json when present
(produced by `coverage run --branch --source=engine -m pytest`); the harness
labels it honestly as measured-or-pending rather than asserting a number.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_RIGOUR_MARKERS = (
    "property",
    "fuzz",
    "determinis",
    "adversar",
    "injection",
    "fail_closed",
    "boundary",
    "race",
    "toctou",
    "exact",
    "kill_switch",
)


def _count_python_tests() -> dict[str, Any]:
    tests_dir = _REPO_ROOT / "tests"
    files = sorted(tests_dir.glob("test_*.py"))
    total_functions = 0
    total_loc = 0
    marker_counts: Counter[str] = Counter()
    for path in files:
        source = path.read_text(encoding="utf-8")
        total_loc += source.count("\n") + 1
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                "test_"
            ):
                total_functions += 1
        lowered = path.name.lower()
        for marker in _RIGOUR_MARKERS:
            if marker in lowered:
                marker_counts[marker] += 1
    return {
        "test_files": len(files),
        "test_functions": total_functions,
        "test_loc": total_loc,
        "files_by_rigour_marker": dict(sorted(marker_counts.items())),
        "files_touching_a_rigour_marker": sum(
            1
            for p in files
            if any(m in p.name.lower() for m in _RIGOUR_MARKERS)
        ),
    }


def _count_typescript_tests() -> dict[str, Any]:
    apps_dir = _REPO_ROOT / "apps"
    patterns = ("*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(apps_dir.rglob(pattern))
    case_re = re.compile(r"\b(?:it|test)\s*\(")
    total_cases = 0
    total_loc = 0
    for path in files:
        source = path.read_text(encoding="utf-8")
        total_loc += source.count("\n") + 1
        total_cases += len(case_re.findall(source))
    return {
        "test_files": len(files),
        "test_cases": total_cases,
        "test_loc": total_loc,
    }


def _count_engine_source() -> dict[str, Any]:
    engine_dir = _REPO_ROOT / "engine"
    files = [p for p in engine_dir.rglob("*.py") if "__pycache__" not in p.parts]
    over_limit = [
        p.relative_to(_REPO_ROOT).as_posix()
        for p in files
        if (p.read_text(encoding="utf-8").count("\n") + 1) > 300 and p.name != "__init__.py"
    ]
    total_loc = sum(p.read_text(encoding="utf-8").count("\n") + 1 for p in files)
    return {
        "source_files": len(files),
        "source_loc": total_loc,
        "files_over_300_line_limit": over_limit,
    }


def _read_coverage() -> dict[str, Any]:
    # Committed small summary (produced from the coverage.py run); the multi-MB
    # raw report is gitignored, so this is the source of the reproducible number.
    cov_path = _DATA_DIR / "coverage_summary.json"
    if not cov_path.is_file():
        return {"status": "pending", "note": "run coverage to populate coverage_summary.json"}
    summary = json.loads(cov_path.read_text(encoding="utf-8"))
    totals = summary.get("totals", {})
    return {
        "status": "measured",
        "line_coverage_pct": summary.get("line_coverage_pct"),
        "branch_coverage_pct": summary.get("branch_coverage_pct"),
        "covered_lines": totals.get("covered_lines"),
        "num_statements": totals.get("num_statements"),
        "num_branches": totals.get("num_branches"),
        "covered_branches": totals.get("covered_branches"),
        "num_files": summary.get("num_files"),
        "tool": summary.get("tool"),
    }


def main() -> None:
    python_tests = _count_python_tests()
    ts_tests = _count_typescript_tests()
    source = _count_engine_source()
    coverage = _read_coverage()
    result = {
        "method": "AST count of def test_* (Python) and it()/test() blocks (TypeScript) "
        "over the real repository; coverage from coverage.py when measured.",
        "python": python_tests,
        "typescript": ts_tests,
        "engine_source": source,
        "total_test_cases": python_tests["test_functions"] + ts_tests["test_cases"],
        "coverage": coverage,
        "coverage_gate_target": {
            "line_pct": 90,
            "branch_pct": 85,
            "source": "CLAUDE.md 5.5 — target gate; CI currently enforces lint + mypy "
            "strict + full pytest (no network); coverage/mutation gates staged to land.",
        },
        "mutation_readiness": "Tests are written adversarially (property/fuzz/determinism/"
        "injection/boundary suites present); mutation scoring is batched to the hardening "
        "gate on Linux CI per CLAUDE.md 7.2, not run on this box.",
    }
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "test_suite_inventory.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"  python: {python_tests['test_functions']} tests / {python_tests['test_files']} files"
    )
    print(f"  typescript: {ts_tests['test_cases']} cases / {ts_tests['test_files']} files")
    print(f"  total test cases = {result['total_test_cases']}")
    print(f"  coverage: {coverage.get('status')} -> line {coverage.get('line_coverage_pct')}")
    print(f"  source files over 300 lines: {len(source['files_over_300_line_limit'])}")


if __name__ == "__main__":
    main()
