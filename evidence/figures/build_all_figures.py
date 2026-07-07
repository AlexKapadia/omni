"""Regenerate every evidence figure (PNG + interactive HTML) from committed data.

Run under the isolated analysis venv (evidence/.evidence-venv), which carries the
plotting dependencies from evidence/requirements-analysis.txt:
    evidence/.evidence-venv/Scripts/python build_all_figures.py
"""

from __future__ import annotations

import build_figures_retrieval_stt as retrieval_stt
import build_figures_router_ask_tests as router_ask_tests


def main() -> None:
    retrieval_stt.main()
    router_ask_tests.main()
    print("all figures regenerated (PNG + HTML)")


if __name__ == "__main__":
    main()
