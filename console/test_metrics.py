"""Le misure del metodo vengono dai report; quello che manca resta dichiarato."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import metrics  # noqa: E402
from workspace import Workspace  # noqa: E402


class MetricsTests(unittest.TestCase):
    def test_metrics_measure_first_pass_rework_time_tokens_and_human_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for fase in ("ONE01E", "TWO01E"):
                (root / "reports" / fase).mkdir(parents=True)
            (root / "tasks.yaml").write_text(
                "units:\n"
                "- id: ONE01\n"
                "  domain: uno\n"
                "tasks:\n"
                "- id: ONE01E\n"
                "  unit_id: ONE01\n"
                "- id: TWO01E\n"
                "  unit_id: TWO01\n",
                encoding="utf-8",
            )
            (root / "state.yaml").write_text(
                "schema: project-console-state/1.0\n"
                "active_claims:\n"
                "- task_id: ONE01E\n"
                "  status: released\n"
                "  taken_at: '2026-10-20T10:00:00+02:00'\n"
                "- task_id: TWO01E\n"
                "  status: released\n"
                "  taken_at: '2026-10-20T11:00:00+02:00'\n"
                "tasks:\n"
                "  ONE01E:\n"
                "    status: accepted\n"
                "  TWO01E:\n"
                "    status: accepted\n"
                "execution_attempts:\n",
                encoding="utf-8",
            )
            (root / "reports" / "ONE01E" / "attempt-1.yaml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "ONE01E",
                        "attempt": 1,
                        "verdict": "pass",
                        "published_at": "2026-10-20T10:30:00+02:00",
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (root / "reports" / "ONE01E" / "attempt-2.yaml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "ONE01E",
                        "attempt": 2,
                        "verdict": "accepted",
                        "authored_by": "utente",
                        "role": "accettazione dell'utente",
                        "published_at": "2026-10-20T11:00:00+02:00",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (root / "reports" / "TWO01E" / "attempt-1.yaml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "TWO01E",
                        "attempt": 1,
                        "verdict": "needs_changes",
                        "published_at": "2026-10-20T11:30:00+02:00",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (root / "reports" / "TWO01E" / "attempt-2.yaml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "TWO01E",
                        "attempt": 2,
                        "verdict": "accepted",
                        "authored_by": "utente",
                        "role": "accettazione dell'utente",
                        "published_at": "2026-10-20T12:30:00+02:00",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            esito = metrics.build(Workspace.load(root))
            summary = esito["summary"]
            self.assertEqual(summary["accepted_with_reports"], 2)
            self.assertEqual(summary["first_pass_comparable"], 2)
            self.assertEqual(summary["first_pass_accepted"], 1)
            self.assertEqual(summary["rework_comparable"], 2)
            self.assertEqual(summary["reworked_phases"], 1)
            self.assertEqual(summary["attempts"], 4)
            self.assertEqual(summary["negative_attempts"], 1)
            self.assertEqual(summary["tokens"]["reports_measured"], 1)
            self.assertEqual(summary["tokens"]["total"], 150)
            self.assertEqual(summary["human_interventions"]["acceptances"], 2)
            self.assertEqual(summary["cycle_time"]["measured_phases"], 2)
            self.assertFalse(
                any("Token non misurati" in avviso for avviso in esito["warnings"])
            )

    def test_missing_usage_is_declared_not_reported_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports" / "ONE01E").mkdir(parents=True)
            (root / "tasks.yaml").write_text(
                "units:\n- id: ONE01\n  domain: uno\ntasks:\n"
                "- id: ONE01E\n  unit_id: ONE01\n",
                encoding="utf-8",
            )
            (root / "state.yaml").write_text(
                "schema: project-console-state/1.0\n"
                "active_claims:\n"
                "tasks:\n"
                "  ONE01E:\n"
                "    status: accepted\n"
                "execution_attempts:\n",
                encoding="utf-8",
            )
            (root / "reports" / "ONE01E" / "attempt-1.yaml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "ONE01E",
                        "attempt": 1,
                        "verdict": "pass",
                        "published_at": "2026-10-20T10:30:00+02:00",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            esito = metrics.build(Workspace.load(root))
            self.assertEqual(esito["summary"]["tokens"]["reports_measured"], 0)
            self.assertIsNone(esito["summary"]["tokens"]["total"])
            self.assertTrue(
                any("Token non misurati" in avviso for avviso in esito["warnings"])
            )


if __name__ == "__main__":
    unittest.main()
