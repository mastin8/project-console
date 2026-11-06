"""La coda valida si applica da sola e non riapplica richieste superate."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "registers"))

import apply_transitions  # noqa: E402
from registers import coda  # noqa: E402
from registers import mandate  # noqa: E402
import server  # noqa: E402
from workspace import Workspace  # noqa: E402


class CodaAutomaticaTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Workspace:
        (root / "tasks.yaml").write_text(
            "units:\n"
            "- id: DEMO\n"
            "  domain: prova\n"
            "tasks:\n"
            "- id: DEMO1\n"
            "  unit_id: DEMO\n"
            "  kind: implementation\n",
            encoding="utf-8",
        )
        (root / "state.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema": "project-console-state/1.0",
                    "active_claims": [
                        {
                            "task_id": "DEMO1",
                            "phase": "E",
                            "status": "pending",
                            "attempt": 1,
                        }
                    ],
                    "tasks": {
                        "DEMO1": {
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
        (root / "pending-transitions").mkdir()
        return Workspace.load(root)

    def _request(self, directory: Path, name: str, status: str) -> Path:
        path = directory / name
        path.write_text(
            yaml.safe_dump(
                {
                    "schema": "project-console-transition/1.0",
                    "requested_by": "/test",
                    "requested_at": "2026-11-03T17:00:00+01:00",
                    "file": "state.yaml",
                    "anchor": "- task_id: DEMO1",
                    "field": "status",
                    "text": status,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_dir_cli_uses_the_safe_runner_and_archives_successes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            self._request(ws.transitions_dir, "20261103T170001-a.yaml", "taken")

            output = StringIO()
            with redirect_stdout(output):
                codice = apply_transitions.main(
                    ["--workspace", str(root), "--dir", str(ws.transitions_dir)]
                )

            state = yaml.safe_load((root / "state.yaml").read_text(encoding="utf-8"))
            self.assertEqual(codice, 0)
            self.assertIn("1 applicate, 0 rifiutate, 0 saltate, 0 in coda", output.getvalue())
            self.assertEqual(state["active_claims"][0]["status"], "taken")
            self.assertEqual(list(ws.transitions_dir.glob("*.yaml")), [])
            self.assertEqual(len(list((ws.transitions_dir / "applied").glob("*.yaml"))), 1)

    def test_stale_duplicate_is_skipped_instead_of_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            self._request(ws.transitions_dir, "20261103T170001-a.yaml", "taken")
            self._request(ws.transitions_dir, "20261103T170002-b.yaml", "taken")

            esito = coda.applica(ws)

            state = yaml.safe_load((root / "state.yaml").read_text(encoding="utf-8"))
            self.assertEqual(state["active_claims"][0]["status"], "taken")
            self.assertIn("1 saltate, 1 in coda", esito["esito"])
            self.assertEqual(
                [path.name for path in ws.transitions_dir.glob("*.yaml")],
                ["20261103T170001-a.yaml"],
            )

    def test_auto_apply_waits_for_a_quiet_batch_and_then_starts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            richiesta = self._request(ws.transitions_dir, "20261103T170001-a.yaml", "taken")
            os.utime(richiesta, (100.0, 100.0))
            state = SimpleNamespace(workspace=ws, applicazione={})

            self.assertFalse(server._coda_stabile(ws, quiet_seconds=1.5, adesso=101.0))
            self.assertTrue(server._coda_stabile(ws, quiet_seconds=1.5, adesso=102.0))
            with (
                mock.patch.object(server.coda, "leggi", return_value={"da_applicare": 1}),
                mock.patch.object(server, "avvia_applicazione_coda", return_value=True) as avvia,
            ):
                self.assertTrue(
                    server.applica_coda_se_pronta(state, quiet_seconds=1.5)
                )
            avvia.assert_called_once_with(state, automatica=True)

    def test_auto_apply_does_not_force_a_suspicious_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            richiesta = self._request(ws.transitions_dir, "20261103T170001-a.yaml", "taken")
            os.utime(richiesta, (100.0, 100.0))
            state = SimpleNamespace(workspace=ws, applicazione={})
            with (
                mock.patch.object(server.coda, "leggi", return_value={"da_applicare": 0}),
                mock.patch.object(server, "avvia_applicazione_coda") as avvia,
            ):
                self.assertFalse(
                    server.applica_coda_se_pronta(state, quiet_seconds=1.5)
                )
            avvia.assert_not_called()

    def test_background_watcher_applies_a_real_batch_without_a_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            richiesta = self._request(ws.transitions_dir, "20261103T170001-a.yaml", "taken")
            os.utime(richiesta, (100.0, 100.0))
            state = SimpleNamespace(
                workspace=ws,
                applicazione={"in_corso": False, "esito": "", "quando": ""},
            )
            stop = threading.Event()
            watcher = threading.Thread(
                target=server.sorveglia_coda,
                args=(state, stop),
                kwargs={"quiet_seconds": 0, "intervallo": 0.02},
                daemon=True,
            )
            watcher.start()
            try:
                scadenza = time.monotonic() + 15
                while time.monotonic() < scadenza:
                    state_corrente = yaml.safe_load(
                        (root / "state.yaml").read_text(encoding="utf-8")
                    )
                    if (
                        state_corrente["active_claims"][0]["status"] == "taken"
                        and state.applicazione.get("returncode") == 0
                    ):
                        break
                    time.sleep(0.05)
                else:
                    self.fail("il watcher non ha applicato il lotto entro 15 secondi")
            finally:
                stop.set()
                watcher.join(timeout=2)

            self.assertEqual(list(ws.transitions_dir.glob("*.yaml")), [])
            self.assertTrue(state.applicazione.get("automatica"))
            self.assertEqual(state.applicazione.get("returncode"), 0)

    def test_generated_claim_appends_the_next_attempt_without_mutating_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            state_path = root / "state.yaml"
            documento = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            documento["active_claims"][0].update(
                {
                    "status": "released",
                    "attempt": 1,
                    "released_at": "2026-11-03T17:00:00+01:00",
                }
            )
            state_path.write_text(
                yaml.safe_dump(documento, sort_keys=False),
                encoding="utf-8",
            )

            prompt = mandate.busta(ws, "DEMO1")
            inizio = prompt.index("    schema: project-console-transition/1.0")
            fine = prompt.index("\n\nSCHEMA DEI REPORT", inizio)
            richiesta = yaml.safe_load(textwrap.dedent(prompt[inizio:fine]))
            richiesta["requested_by"] = "/test"
            richiesta["requested_at"] = "2026-11-03T17:05:00+01:00"
            richiesta["item"]["taken_by"] = "/test"
            richiesta["item"]["taken_at"] = "2026-11-03T17:05:00+01:00"
            richiesta["item"]["registered_at"] = "2026-11-03T17:05:00+01:00"
            richiesta["item"]["registered_by"] = "/test"
            richiesta["item"]["owner"] = "/test"
            percorso = ws.transitions_dir / "20261103T170500-test-claim.yaml"
            percorso.write_text(
                yaml.safe_dump(richiesta, sort_keys=False),
                encoding="utf-8",
            )

            esito = coda.applica(ws)

            aggiornato = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            self.assertIn("1 applicate", esito["esito"])
            self.assertEqual(len(aggiornato["active_claims"]), 2)
            self.assertEqual(aggiornato["active_claims"][0]["status"], "released")
            self.assertEqual(aggiornato["active_claims"][0]["attempt"], 1)
            self.assertEqual(aggiornato["active_claims"][1]["status"], "taken")
            self.assertEqual(aggiornato["active_claims"][1]["attempt"], 2)
            self.assertEqual(aggiornato["active_claims"][1]["taken_by"], "/test")

    def test_version_fingerprint_tracks_files_outside_the_main_registries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = self._workspace(root)
            state = server.ReviewState(ws)
            prima = state.versione()
            self.assertEqual(prima["reports_mtime_ns"], 0)
            self.assertEqual(prima["dispatch_queue_mtime_ns"], 0)
            self.assertEqual(prima["transitions_mtime_ns"], 0)
            self.assertEqual(prima["inbox_mtime_ns"], 0)

            (root / "reports" / "DEMO1").mkdir(parents=True)
            (root / "reports" / "DEMO1" / "attempt-1.yaml").write_text(
                "task_id: DEMO1\nattempt: 1\n",
                encoding="utf-8",
            )
            (root / "dispatch-queue").mkdir()
            (root / "dispatch-queue" / "ordine.yaml").write_text(
                "task_id: DEMO1\n",
                encoding="utf-8",
            )
            (ws.transitions_dir / "transizione.yaml").write_text(
                "schema: project-console-transition/1.0\n",
                encoding="utf-8",
            )
            (root / "inbox").mkdir()
            (root / "inbox" / "messaggio.md").write_text("testo\n", encoding="utf-8")

            dopo = state.versione()
            self.assertGreater(dopo["reports_mtime_ns"], 0)
            self.assertGreater(dopo["dispatch_queue_mtime_ns"], 0)
            self.assertGreater(dopo["transitions_mtime_ns"], 0)
            self.assertGreater(dopo["inbox_mtime_ns"], 0)


if __name__ == "__main__":
    unittest.main()
