"""Matrice della fase A/E/T/R delle rifiniture.

Il console non deve dipendere dal nome di una singola rifinitura: questa matrice prova i casi
che i report possono dichiarare e il caso in cui la fase non è determinabile.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import refinements  # noqa: E402
import server  # noqa: E402
from workspace import Workspace  # noqa: E402


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
    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp)
        (radice / "reports" / "RIF").mkdir(parents=True)
        report = {
            "task_id": "RIF",
            "attempt": 2,
            "phase": "E",
            "verdict": "needs_changes",
            "findings": [{"id": "F1", "what": "errore misurato"}],
            "test": {"command": "test mirato", "exit": 1, "duration": "2s"},
        }
        (radice / "reports" / "RIF" / "attempt-2.yaml").write_text(
            yaml.safe_dump(report, sort_keys=False), encoding="utf-8"
        )
        (radice / "refinements.yaml").write_text(
            yaml.safe_dump({
                "schema": refinements.SCHEMA,
                "items": [{
                    "id": "RIF",
                    "phases": {
                        "E": {
                            "status": "delivered",
                            "attempt": 2,
                            "report": "reports/RIF/attempt-2.yaml",
                        }
                    },
                }],
            }, sort_keys=False),
            encoding="utf-8",
        )
        workspace = Workspace.load(radice)
        esito = refinements.sync(workspace)
        assert any(cambio.endswith("E.status") for cambio in esito["updated"])
        documento = yaml.safe_load((radice / "refinements.yaml").read_text())
        fase = documento["items"][0]["phases"]["E"]
        assert fase["status"] == "needs_changes"
        assert fase["test"]["exit"] == 1
        assert fase["errors"]
        try:
            refinements.update(workspace, "RIF", phase="A", status="delivered")
        except ValueError:
            pass
        else:
            raise AssertionError("una consegna senza test/report deve essere rifiutata")
    print(f"ok {len(CASI)} casi A/E/T/R + sync + consegna validata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
