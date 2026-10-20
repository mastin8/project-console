"""Il report dei progetti nuovi dichiara usage e provenienza Git."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "registers"))

import report_contract  # noqa: E402
import refinements  # noqa: E402
from workspace import Workspace  # noqa: E402


class ReportContractTests(unittest.TestCase):
    def test_usage_can_be_measured_or_explicitly_unavailable(self):
        self.assertEqual(
            report_contract.usage_errors(
                {"usage": {"availability": "measured", "input_tokens": 10, "output_tokens": 5}}
            ),
            [],
        )
        self.assertEqual(
            report_contract.usage_errors(
                {"usage": {"availability": "unavailable", "reason": "runtime non espone i token"}}
            ),
            [],
        )
        self.assertTrue(report_contract.usage_errors({}))
        self.assertTrue(
            report_contract.usage_errors(
                {"usage": {"availability": "unavailable"}}
            )
        )

    def test_git_provenance_requires_commits_paths_and_clean_state(self):
        documento = {
            "git": {
                "branch": "feature/prova",
                "worktree": "/tmp/progetto",
                "base_commit": "1234567",
                "head_commit": "89abcde",
                "changed_paths": ["app.py"],
                "dirty_before": [],
                "clean_after": True,
            }
        }
        self.assertEqual(report_contract.git_errors(documento), [])
        self.assertTrue(report_contract.git_errors({}))

    def test_legacy_workspace_skips_new_contract(self):
        workspace = SimpleNamespace(
            require_usage=False,
            require_git_provenance=False,
        )
        self.assertEqual(report_contract.validate(workspace, {}), [])

    def test_delivered_refinement_rejects_report_without_new_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "console.yaml").write_text(
                "require_usage: true\nrequire_git_provenance: true\n",
                encoding="utf-8",
            )
            (root / "reports" / "OBB").mkdir(parents=True)
            (root / "reports" / "OBB" / "attempt-1.yaml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "OBB",
                        "attempt": 1,
                        "verdict": "pass",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (root / "refinements.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema": refinements.SCHEMA,
                        "items": [
                            {
                                "id": "OBB",
                                "phases": {
                                    "E": {
                                        "status": "pending",
                                        "report": "reports/OBB/attempt-1.yaml",
                                    }
                                },
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            workspace = Workspace.load(root)
            with self.assertRaisesRegex(ValueError, "report fuori contratto"):
                refinements.update(
                    workspace,
                    "OBB",
                    phase="E",
                    status="delivered",
                    attempt=1,
                    report="reports/OBB/attempt-1.yaml",
                    verdict="pass",
                    test_command="test",
                    test_exit=0,
                    test_duration="1s",
                )


if __name__ == "__main__":
    unittest.main()
