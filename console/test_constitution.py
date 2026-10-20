"""La legge della Costituzione: bozza, conflitto, approvazione e sigillo."""
from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import constitution  # noqa: E402
from workspace import Workspace  # noqa: E402


class ConstitutionTests(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.addCleanup(self.cartella.cleanup)
        self.radice = Path(self.cartella.name)
        self.percorso = self.radice / "constitution.md"
        self.percorso.write_text(
            "---\n"
            "schema: project-console-constitution/1.0\n"
            "status: draft\n"
            'project: "Prova"\n'
            'updated_at: ""\n'
            'approved_at: ""\n'
            'approved_sha256: ""\n'
            "---\n\n"
            "# Costituzione\n\nObiettivo iniziale.\n",
            encoding="utf-8",
        )
        self.workspace = Workspace.load(self.radice)

    def test_draft_can_be_saved_and_reloaded(self):
        letto = constitution.load(self.workspace)
        self.assertTrue(letto["editable"])
        salvato = constitution.save_draft(
            self.workspace,
            "# Costituzione\n\nObiettivo deciso.\n",
            expected_sha256=letto["draft_sha256"],
        )
        self.assertEqual(salvato["body"], "# Costituzione\n\nObiettivo deciso.\n")
        self.assertEqual(constitution.load(self.workspace)["body"], salvato["body"])
        self.assertTrue(salvato["updated_at"])

    def test_old_checksum_is_a_conflict(self):
        letto = constitution.load(self.workspace)
        constitution.save_draft(self.workspace, "# Prima modifica\n", letto["draft_sha256"])
        with self.assertRaises(constitution.ConstitutionConflict):
            constitution.save_draft(self.workspace, "# Seconda modifica\n", letto["draft_sha256"])

    def test_approval_locks_the_file_and_rejects_a_second_act(self):
        letto = constitution.load(self.workspace)
        approvata = constitution.approve(
            self.workspace,
            expected_sha256=letto["draft_sha256"],
            body="# Costituzione approvata\n\nRegola uno.\n",
        )
        self.assertEqual(approvata["status"], "approved")
        self.assertFalse(approvata["editable"])
        self.assertEqual(approvata["approved_sha256"], approvata["draft_sha256"])
        self.assertEqual(
            stat.S_IMODE(self.percorso.stat().st_mode) & 0o222,
            0,
            "dopo l'approvazione il file deve essere in sola lettura",
        )
        with self.assertRaises(constitution.ConstitutionLocked):
            constitution.save_draft(self.workspace, "# Cambio\n")
        with self.assertRaises(constitution.ConstitutionLocked):
            constitution.approve(self.workspace)

    def test_tampering_after_approval_fails_closed(self):
        constitution.approve(
            self.workspace,
            body="# Costituzione approvata\n\nRegola uno.\n",
        )
        self.percorso.chmod(0o644)
        self.percorso.write_text(
            self.percorso.read_text(encoding="utf-8").replace("Regola uno", "Regola cambiata"),
            encoding="utf-8",
        )
        with self.assertRaises(constitution.ConstitutionIntegrityError):
            constitution.load(self.workspace)

    def test_legacy_markdown_is_a_draft(self):
        self.percorso.write_text("# Costituzione vecchia\n\nSenza frontmatter.\n", encoding="utf-8")
        letto = constitution.load(self.workspace)
        self.assertEqual(letto["status"], "draft")
        self.assertTrue(letto["editable"])
        self.assertEqual(letto["body"], "# Costituzione vecchia\n\nSenza frontmatter.\n")

    def test_empty_constitution_cannot_be_approved(self):
        with self.assertRaises(constitution.ConstitutionInvalid):
            constitution.approve(self.workspace, body="  \n")

    def test_missing_file_is_declared(self):
        self.percorso.unlink()
        with self.assertRaises(constitution.ConstitutionMissing):
            constitution.load(self.workspace)


if __name__ == "__main__":
    unittest.main()
