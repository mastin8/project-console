"""Matrice della fase A/E/T/R delle rifiniture.

Il console non deve dipendere dal nome di una singola rifinitura: questa matrice prova i casi
che i report possono dichiarare e il caso in cui la fase non è determinabile.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


CASI = [
    (
        {"report_phase": "T", "report_verdict": "pass_with_declared_limits"},
        {"A": "done", "E": "done", "T": "done", "R": "missing"},
        "R",
    ),
    (
        {"report_phase": "T", "report_verdict": "needs_changes"},
        {"A": "done", "E": "done", "T": "done", "R": "missing"},
        "E",
    ),
    (
        {"report_phase": "E", "report_verdict": "needs_changes", "taken": True},
        {"A": "done", "E": "in_progress", "T": "missing", "R": "missing"},
        "E",
    ),
    (
        {"report_phase": "", "report_verdict": "needs_changes"},
        {"A": "done", "E": "partial", "T": "missing", "R": "missing"},
        "E",
    ),
    (
        {"report_phase": "", "report_verdict": "measurement_delivered_obligation_open"},
        {"A": "done", "E": "partial", "T": "missing", "R": "missing"},
        "E",
    ),
    (
        {"report_phase": "", "report_verdict": "still_open_remeasured"},
        {"A": "done", "E": "done", "T": "missing", "R": "missing"},
        "T",
    ),
    (
        {"report_phase": "", "report_verdict": "esito_non_classificato"},
        {"A": "done", "E": "missing", "T": "missing", "R": "missing"},
        "?",
    ),
    (
        {"taken": True},
        {"A": "done", "E": "in_progress", "T": "missing", "R": "missing"},
        "E",
    ),
    (
        {},
        {"A": "missing", "E": "missing", "T": "missing", "R": "missing"},
        "A",
    ),
]


def main():
    for indice, (voce, attese, prossima) in enumerate(CASI, start=1):
        fasi, ottenuta, fonte = server._refinement_stage(voce)
        assert fasi == attese, f"caso {indice}: fasi {fasi} != {attese}"
        assert ottenuta == prossima, f"caso {indice}: prossima {ottenuta} != {prossima}"
        assert fonte, f"caso {indice}: fonte vuota"
    print(f"ok {len(CASI)} casi A/E/T/R")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
