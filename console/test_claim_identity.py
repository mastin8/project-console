"""La presa vive in `taken_by`; `owner` puo' essere il residuo dell'attivazione."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registers import claim_identity  # noqa: E402
import recap  # noqa: E402
import server  # noqa: E402
from workspace import Workspace  # noqa: E402


class ClaimIdentityTests(unittest.TestCase):
    def test_taken_by_wins_over_activation_owner(self):
        claim = {
            "task_id": "FND01E",
            "taken_by": "/root",
            "owner": "NESSUN TITOLARE: attivazione in attesa di un esecutore",
        }

        self.assertEqual(claim_identity.owner(claim), "/root")

    def test_legacy_claim_fields_remain_readable(self):
        self.assertEqual(claim_identity.owner({"owner_agent": "/legacy"}), "/legacy")
        self.assertEqual(claim_identity.owner({"owner": "/owner"}), "/owner")
        self.assertEqual(claim_identity.owner(None), "")

    def test_snapshot_and_recap_show_the_actual_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks.yaml").write_text(
                "units:\n"
                "- id: FND01\n"
                "  domain: fondamenta\n"
                "tasks:\n"
                "- id: FND01E\n"
                "  unit_id: FND01\n"
                "  kind: implementation\n",
                encoding="utf-8",
            )
            (root / "state.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema": "project-console-state/1.0",
                        "active_claims": [
                            {
                                "task_id": "FND01E",
                                "phase": "E",
                                "status": "taken",
                                "taken_by": "/root",
                                "taken_at": "2026-11-02T09:48:03+01:00",
                                "owner": "NESSUN TITOLARE: attivazione in attesa di un esecutore",
                            }
                        ],
                        "tasks": {
                            "FND01E": {
                                "status": "pending",
                                "attempt": 0,
                                "kind": "implementation",
                            }
                        },
                        "execution_attempts": [],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            workspace = Workspace.load(root)
            state = server.ReviewState(workspace)

            snapshot = state.snapshot()
            claim = snapshot["claims"][0]
            self.assertEqual(claim["owner"], "/root")
            self.assertEqual(claim["taken_by"], "/root")
            with mock.patch.object(recap.constitution, "prompt_context", return_value=""):
                self.assertNotIn("NESSUN TITOLARE", str(recap.costruisci(state)))


if __name__ == "__main__":
    unittest.main()
