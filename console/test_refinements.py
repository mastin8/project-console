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
from registers import next_action  # noqa: E402
from workspace import Workspace  # noqa: E402


CASI = [
    (
        {"report_phase": "T", "report_verdict": "pass_with_declared_limits"},
        "accept",
        "T",
    ),
    (
        {"report_phase": "T", "report_verdict": "needs_changes"},
        "rework_e",
        "E",
    ),
    (
        {"report_phase": "E", "report_verdict": "needs_changes", "taken": True},
        "rework_e",
        "E",
    ),
    (
        {"report_phase": "", "report_verdict": "needs_changes"},
        "rework_e",
        "E",
    ),
    (
        {"report_phase": "", "report_verdict": "measurement_delivered_obligation_open"},
        "rework_e",
        "E",
    ),
    (
        {"report_phase": "", "report_verdict": "still_open_remeasured"},
        "run_phase",
        "T",
    ),
    (
        {"report_phase": "", "report_verdict": "esito_non_classificato"},
        "review",
        None,
    ),
    (
        {"taken": True},
        "wait",
        "A",
    ),
    (
        {},
        "run_phase",
        "A",
    ),
]


def main():
    for indice, (voce, codice, fase) in enumerate(CASI, start=1):
        azione = next_action.decide_report(
            voce.get("report_phase"),
            voce.get("report_verdict"),
            closure_condition_met=voce.get("report_closed"),
        )
        if not voce.get("report_phase") and voce.get("taken"):
            azione = next_action.for_obligation(voce)
        assert azione["code"] == codice, (
            f"caso {indice}: azione {azione['code']} != {codice}"
        )
        if fase is not None:
            assert azione.get("target_phase") == fase, (
                f"caso {indice}: fase {azione.get('target_phase')} != {fase}"
            )
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
        refinements.update(workspace, "RIF", lane="fast")
        veloce = refinements.load(workspace)["RIF"]
        fasi_veloci = refinements.stage_map(veloce)
        assert fasi_veloci["A"] == "not_required"
        assert fasi_veloci["R"] == "not_required"
        assert refinements.next_phase(veloce) in ("E", "T")
    print(f"ok {len(CASI)} casi A/E/T/R + sync + consegna validata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
