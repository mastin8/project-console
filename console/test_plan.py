"""Il piano dei task: conferma umana, impronta e blocco quando cambia."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registers import plan  # noqa: E402
from console import constitution  # noqa: E402
from registers import activate, mandate  # noqa: E402
from workspace import Workspace  # noqa: E402


def _workspace(root):
    (root / "console.yaml").write_text(
        'project: "Piano"\n'
        "require_plan_approval: true\n",
        encoding="utf-8",
    )
    (root / "tasks.yaml").write_text(
        "units:\n"
        "- id: PLAN01\n"
        "  domain: prova\n"
        "tasks:\n"
        "- id: PLAN01E\n"
        "  unit_id: PLAN01\n"
        "  kind: implementation\n"
        "  title: Esecuzione\n"
        "- id: PLAN01T\n"
        "  unit_id: PLAN01\n"
        "  kind: independent_verification\n"
        "  title: Verifica\n",
        encoding="utf-8",
    )
    (root / "state.yaml").write_text(
        "schema: project-console-state/1.0\n"
        "active_claims:\n"
        "tasks:\n"
        "execution_attempts:\n",
        encoding="utf-8",
    )
    (root / "constitution.md").write_text(
        "---\n"
        "schema: project-console-constitution/1.0\n"
        "status: draft\n"
        'project: "Piano"\n'
        'updated_at: ""\n'
        'approved_at: ""\n'
        'approved_sha256: ""\n'
        "---\n\n"
        "# Costituzione\n\n## 1. Obiettivo\n\nMisurare il piano.\n",
        encoding="utf-8",
    )
    return Workspace.load(root)


class PlanTests(unittest.TestCase):
    def test_new_plan_requires_user_approval_and_then_tracks_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _workspace(root)
            self.assertEqual(plan.gate(ws)["status"], "missing")
            with self.assertRaises(constitution.ConstitutionNotApproved):
                plan.approve(ws)
            constitution.approve(ws)
            approvato = plan.approve(ws)
            self.assertEqual(approvato["status"], "approved")
            self.assertTrue(approvato["approved"])
            (root / "tasks.yaml").write_text(
                (root / "tasks.yaml").read_text(encoding="utf-8")
                + "- id: PLAN01R\n"
                "  unit_id: PLAN01\n"
                "  kind: functional_acceptance\n"
                "  title: Accettazione\n",
                encoding="utf-8",
            )
            self.assertEqual(plan.gate(ws)["status"], "changed")
            with self.assertRaises(plan.PlanChanged):
                plan.require_approved(ws)
            self.assertEqual(activate.attivabili(ws), [])
            with self.assertRaises(plan.PlanChanged):
                mandate.per(ws, "PLAN01E")

    def test_legacy_workspace_does_not_require_a_plan_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks.yaml").write_text("units: []\ntasks: []\n", encoding="utf-8")
            ws = Workspace.load(root)
            stato = plan.gate(ws)
            self.assertFalse(stato["required"])
            self.assertTrue(stato["approved"])


if __name__ == "__main__":
    unittest.main()
