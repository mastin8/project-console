"""La matrice della prossima azione: un solo motore, nessuna lettura libera del verdetto."""
from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registers import next_action  # noqa: E402
from registers import activate, mandate, sync_phases  # noqa: E402
from console import constitution  # noqa: E402
import server  # noqa: E402
from workspace import Workspace  # noqa: E402


class NextActionTests(unittest.TestCase):
    def test_negative_verdict_always_returns_to_e(self):
        for phase in ("E", "T", "R"):
            azione = next_action.decide_report(phase, "needs_changes")
            self.assertEqual(azione["code"], "rework_e")
            self.assertEqual(azione["target_phase"], "E")

    def test_positive_e_asks_acceptance_then_t(self):
        azione = next_action.decide_report("E", "pass")
        self.assertEqual(azione["code"], "accept")
        self.assertEqual(azione["accept_phase"], "E")
        self.assertEqual(azione["after_phase"], "T")

    def test_positive_t_asks_acceptance_then_r(self):
        azione = next_action.decide_report("T", "pass_with_declared_limits")
        self.assertEqual(azione["code"], "accept")
        self.assertEqual(azione["accept_phase"], "T")
        self.assertEqual(azione["after_phase"], "R")

    def test_fast_lane_never_opens_a_or_r(self):
        self.assertEqual(next_action.phases_for("fast"), ("E", "T"))
        azione = next_action.decide_report("T", "pass", lane="fast")
        self.assertEqual(azione["accept_phase"], "T")
        self.assertIsNone(azione["after_phase"])

    def test_fast_lane_is_not_selected_for_risky_paths(self):
        lane = next_action.infer_lane(
            "fast",
            paths=["app/migrations/0001.py"],
        )
        self.assertEqual(lane, "standard")

    def test_report_closure_becomes_a_close_action(self):
        azione = next_action.decide_report(
            "R",
            "pass",
            closure_condition_met=True,
        )
        self.assertEqual(azione["code"], "close_obligation")
        self.assertEqual(azione["primary"], "close")

    def test_unclassified_verdict_needs_a_human_review(self):
        azione = next_action.decide_report("T", "qualcosa_di_strano")
        self.assertEqual(azione["code"], "review")

    def test_task_delivery_uses_the_same_accept_decision(self):
        azione = next_action.for_task(
            {
                "phase": "E",
                "consegnata": True,
                "verdetto": "ready_for_handoff",
            }
        )
        self.assertEqual(azione["code"], "accept")
        self.assertEqual(azione["after_phase"], "T")

    def test_fast_task_uses_only_its_declared_e_and_t_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            radice = Path(tmp)
            (radice / "tasks.yaml").write_text(
                "units:\n"
                "- id: FAST01\n"
                "  domain: prova\n"
                "  lane: fast\n"
                "tasks:\n"
                "- id: FAST01E\n"
                "  unit_id: FAST01\n"
                "  kind: implementation\n"
                "- id: FAST01T\n"
                "  unit_id: FAST01\n"
                "  kind: independent_verification\n",
                encoding="utf-8",
            )
            (radice / "state.yaml").write_text(
                "schema: project-console-state/1.0\n"
                "active_claims:\n"
                "tasks:\n"
                "execution_attempts:\n",
                encoding="utf-8",
            )
            (radice / "constitution.md").write_text(
                "---\n"
                "schema: project-console-constitution/1.0\n"
                "status: draft\n"
                'project: "Progetto"\n'
                'updated_at: ""\n'
                'approved_at: ""\n'
                'approved_sha256: ""\n'
                "---\n\n"
                "# Costituzione\n\n## 1. Obiettivo\n\nSolo E e T.\n",
                encoding="utf-8",
            )
            workspace = Workspace.load(radice)
            constitution.approve(workspace)
            percorso = activate.prossimi(workspace)
            self.assertEqual([voce["phase"] for voce in percorso], ["FAST01E"])
            self.assertEqual(percorso[0]["next_action"]["target_phase"], "FAST01E")

    def test_completed_fast_lane_without_closure_asks_for_review(self):
        azione = next_action.for_obligation(
            {
                "lane": "fast",
                "stages": {
                    "A": "not_required",
                    "E": "done",
                    "T": "done",
                    "R": "not_required",
                },
                "report_phase": "T",
                "report_verdict": "pass",
            }
        )
        self.assertEqual(azione["code"], "review")

    def test_owed_direction_selects_one_executable_phase(self):
        azione = next_action.for_owed(
            {
                "codes": [
                    {"code": "TASK01T", "live": True},
                    {"code": "TASK01E", "status": "pending"},
                ]
            }
        )
        self.assertEqual(azione["code"], "run_phase")
        self.assertEqual(azione["target_phase"], "TASK01E")

    def test_close_obligation_writes_the_declared_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            radice = Path(tmp)
            (radice / "reports" / "OBB").mkdir(parents=True)
            report = radice / "reports" / "OBB" / "attempt-1.yaml"
            report.write_text(
                yaml.safe_dump(
                    {
                        "task_id": "OBB",
                        "attempt": 1,
                        "phase": "T",
                        "verdict": "pass",
                        "published_at": "2026-10-20T12:00:00+02:00",
                        "obligation_status_after": "closed",
                        "closure_condition_met": True,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (radice / "state.yaml").write_text(
                "schema: project-console-state/1.0\n"
                "active_claims:\n"
                "tasks:\n"
                "execution_attempts:\n"
                "- obligation_id: OBB\n"
                "  status: open\n"
                "  required_before: END01\n",
                encoding="utf-8",
            )
            (radice / "tasks.yaml").write_text("units: []\ntasks: []\n", encoding="utf-8")
            workspace = Workspace.load(radice)
            esito = next_action.close_obligation(workspace, "OBB", "reports/OBB/attempt-1.yaml")
            self.assertTrue(esito["closed"])
            stato = yaml.safe_load((radice / "state.yaml").read_text(encoding="utf-8"))
            voce = stato["execution_attempts"][0]
            self.assertEqual(voce["status"], "closed")
            self.assertEqual(
                voce["closure_kind"],
                "automatic_from_published_report",
            )
            self.assertEqual(
                voce["closure_declaration_ref"],
                "reports/OBB/attempt-1.yaml",
            )

    def test_snapshot_keeps_pending_and_closure_on_their_own_obligation(self):
        with tempfile.TemporaryDirectory() as tmp:
            radice = Path(tmp)
            for nome in ("OBB-REWORK", "OBB-CLOSE"):
                (radice / "reports" / nome).mkdir(parents=True)
            (radice / "tasks.yaml").write_text("units: []\ntasks: []\n", encoding="utf-8")
            (radice / "state.yaml").write_text(
                "schema: project-console-state/1.0\n"
                "active_claims:\n"
                "tasks:\n"
                "execution_attempts:\n"
                "- obligation_id: OBB-REWORK\n"
                "  status: open\n"
                "  required_before: END01\n"
                "- obligation_id: OBB-CLOSE\n"
                "  status: open\n"
                "  required_before: None\n",
                encoding="utf-8",
            )
            (radice / "refinements.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema": "project-console-refinements/1.0",
                        "items": [
                            {
                                "id": "OBB-REWORK",
                                "lane": "fast",
                                "phases": {
                                    "E": {
                                        "status": "needs_changes",
                                        "attempt": 1,
                                        "report": "reports/OBB-REWORK/attempt-1.yaml",
                                        "verdict": "needs_changes",
                                    }
                                },
                            },
                            {
                                "id": "OBB-CLOSE",
                                "lane": "standard",
                                "phases": {
                                    "T": {
                                        "status": "delivered",
                                        "attempt": 1,
                                        "report": "reports/OBB-CLOSE/attempt-1.yaml",
                                        "verdict": "pass",
                                    }
                                },
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (radice / "reports" / "OBB-REWORK" / "attempt-1.yaml").write_text(
                yaml.safe_dump(
                    {
                        "phase": "E",
                        "verdict": "needs_changes",
                        "closure_condition_met": False,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (radice / "reports" / "OBB-CLOSE" / "attempt-1.yaml").write_text(
                yaml.safe_dump(
                    {
                        "phase": "T",
                        "verdict": "pass",
                        "closure_condition_met": True,
                        "obligation_status_after": "closed",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (radice / "constitution.md").write_text(
                "---\n"
                "schema: project-console-constitution/1.0\n"
                "status: draft\n"
                'project: "Progetto"\n'
                'updated_at: ""\n'
                'approved_at: ""\n'
                'approved_sha256: ""\n'
                "---\n\n"
                "# Costituzione\n\n## 1. Obiettivo\n\nMisurare.\n",
                encoding="utf-8",
            )
            workspace = Workspace.load(radice)
            constitution.approve(workspace)
            snapshot = server.ReviewState(workspace).snapshot()
            azioni = {
                voce["id"]: voce["next_action"]["code"]
                for voce in snapshot["obligations"]
            }
            self.assertEqual(azioni["OBB-REWORK"], "rework_e")
            self.assertEqual(azioni["OBB-CLOSE"], "close_obligation")
            rework = next(
                voce for voce in snapshot["obligations"] if voce["id"] == "OBB-REWORK"
            )
            self.assertNotEqual(
                (rework.get("pending_refinement") or {}).get("id"),
                "OBB-CLOSE",
            )

    def test_constitution_blocks_activation_and_then_enriches_the_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            radice = Path(tmp)
            (radice / "state.yaml").write_text(
                "schema: project-console-state/1.0\n"
                "active_claims:\n"
                "tasks:\n"
                "execution_attempts:\n",
                encoding="utf-8",
            )
            (radice / "tasks.yaml").write_text(
                "units:\n"
                "- id: TASK01\n"
                "  domain: prova\n"
                "  title: Prova\n"
                "tasks:\n"
                "- id: TASK01E\n"
                "  unit_id: TASK01\n"
                "  kind: implementation\n"
                "  title: Esecuzione\n",
                encoding="utf-8",
            )
            percorso = radice / "constitution.md"
            percorso.write_text(
                "---\n"
                "schema: project-console-constitution/1.0\n"
                "status: draft\n"
                'project: "Progetto"\n'
                'updated_at: ""\n'
                'approved_at: ""\n'
                'approved_sha256: ""\n'
                "---\n\n"
                "# Costituzione\n\n"
                "## 1. Obiettivo\n\nSolo il comportamento misurato.\n\n"
                "## 9. Test e accettazione\n\nUn modulo, una corsa.\n",
                encoding="utf-8",
            )
            workspace = Workspace.load(radice)
            self.assertEqual(activate.attivabili(workspace), [])
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    sync_phases.main(["--workspace", str(radice), "--apply"]),
                    1,
                )
            with self.assertRaises(constitution.ConstitutionNotApproved):
                activate.attiva(workspace, "TASK01E")
            with self.assertRaises(constitution.ConstitutionNotApproved):
                mandate.per(workspace, "TASK01E")
            constitution.approve(workspace)
            prompt = mandate.con_busta(workspace, "TASK01E", "Corpo del lavoro.\n")
            self.assertIn("VINCOLI DELLA COSTITUZIONE APPROVATA", prompt)
            self.assertIn("Solo il comportamento misurato", prompt)
            self.assertIn("Un modulo, una corsa", prompt)


if __name__ == "__main__":
    unittest.main()
