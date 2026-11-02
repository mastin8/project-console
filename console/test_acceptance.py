"""L'accettazione non deve scrivere una firma che il registro non sa ricevere."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registers import accetta, activate, preflight  # noqa: E402
from workspace import Workspace  # noqa: E402


def _workspace(root: Path, *, open_phase: bool = True) -> Workspace:
    (root / "tasks.yaml").write_text(
        "units:\n"
        "- id: FND01\n"
        "  domain: fondamenta\n"
        "tasks:\n"
        "- id: FND01A\n"
        "  unit_id: FND01\n"
        "  kind: analysis\n"
        "  title: Analisi\n",
        encoding="utf-8",
    )
    task_block = (
        "  FND01A:\n"
        "    status: pending\n"
        "    attempt: 0\n"
        "    kind: analysis\n"
        if open_phase
        else ""
    )
    (root / "state.yaml").write_text(
        "schema: project-console-state/1.0\n"
        "active_claims:\n"
        "tasks:\n"
        f"{task_block}"
        "execution_attempts:\n",
        encoding="utf-8",
    )
    (root / "reports" / "FND01A").mkdir(parents=True)
    (root / "reports" / "FND01A" / "attempt-1.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "project-console-report/1.0",
                "task_id": "FND01A",
                "attempt": 1,
                "status": "published",
                "verdict": "pass",
                "published_at": "2026-10-31T14:42:07+01:00",
                "summary": "Analisi pronta.",
                "next": "FND01E: implementare.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "reports" / "FND01A.yaml").write_text(
        "schema: project-console-report-pointer/1.0\n"
        "task_id: FND01A\n"
        "attempt: 1\n"
        "report: reports/FND01A/attempt-1.yaml\n"
        "report_ref: reports/FND01A/attempt-1.yaml\n"
        "status: published\n"
        "verdict: pass\n"
        "published_at: '2026-10-31T14:42:07+01:00'\n",
        encoding="utf-8",
    )
    return Workspace.load(root)


class AcceptanceTests(unittest.TestCase):
    def test_activation_rejects_an_unsynchronised_phase_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _workspace(root, open_phase=False)

            with mock.patch.object(activate.constitution, "require_approved", return_value={}), mock.patch.object(
                activate.plan,
                "require_approved",
                return_value={},
            ):
                with self.assertRaisesRegex(
                    activate.apply_transitions.TransitionError,
                    "sync_phases.py --apply",
                ):
                    activate.attiva(ws, "FND01A")

            self.assertFalse((root / "dispatch-queue").exists())

    def test_preflight_blocks_a_phase_missing_from_state_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _workspace(root, open_phase=False)
            prima = (root / "reports" / "FND01A.yaml").read_bytes()

            quadro = preflight.leggi(ws, "FND01A")

            self.assertEqual(quadro["esito"], "NON ANCORA")
            self.assertTrue(
                any("non e' aperta" in motivo and "sync_phases.py --apply" in motivo for motivo in quadro["motivi"])
            )
            with self.assertRaisesRegex(ValueError, "sync_phases.py --apply"):
                accetta.per(ws, "FND01A")
            self.assertEqual((root / "reports" / "FND01A.yaml").read_bytes(), prima)
            self.assertFalse((root / "reports" / "FND01A" / "attempt-2.yaml").exists())

    def test_acceptance_registers_the_act_and_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _workspace(root)

            esito = accetta.per(ws, "FND01A")

            self.assertEqual(esito["numero"], 2)
            registro = yaml.safe_load((root / "state.yaml").read_text(encoding="utf-8"))
            self.assertEqual(registro["tasks"]["FND01A"]["status"], "accepted")
            self.assertEqual(registro["tasks"]["FND01A"]["attempt"], 2)
            puntatore = yaml.safe_load((root / "reports" / "FND01A.yaml").read_text(encoding="utf-8"))
            self.assertEqual(puntatore["report"], "reports/FND01A/attempt-2.yaml")
            self.assertTrue((root / "reports" / "FND01A" / "attempt-2.yaml").is_file())

    def test_failed_transition_rolls_back_report_pointer_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _workspace(root)
            stato_prima = (root / "state.yaml").read_bytes()
            puntatore_prima = (root / "reports" / "FND01A.yaml").read_bytes()
            reale = accetta.apply_transitions.apply_request
            chiamate = {"n": 0}

            def prima_poi_fallisce(request, **kwargs):
                chiamate["n"] += 1
                if chiamate["n"] == 2:
                    raise accetta.apply_transitions.TransitionError("errore simulato")
                return reale(request, **kwargs)

            with mock.patch.object(
                accetta.apply_transitions,
                "apply_request",
                side_effect=prima_poi_fallisce,
            ):
                with self.assertRaisesRegex(accetta.apply_transitions.TransitionError, "errore simulato"):
                    accetta.per(ws, "FND01A")

            self.assertEqual((root / "state.yaml").read_bytes(), stato_prima)
            self.assertEqual((root / "reports" / "FND01A.yaml").read_bytes(), puntatore_prima)
            self.assertFalse((root / "reports" / "FND01A" / "attempt-2.yaml").exists())


if __name__ == "__main__":
    unittest.main()
