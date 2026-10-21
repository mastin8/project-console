"""L'audit di partenza: ciò che viene misurato, spiegato e chiuso prima dell'approvazione."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import constitution  # noqa: E402
import onboarding_findings  # noqa: E402
import onboarding_questions  # noqa: E402
from workspace import Workspace  # noqa: E402


class OnboardingFindingsTests(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.addCleanup(self.cartella.cleanup)
        self.repo = Path(self.cartella.name)
        self.workspace_dir = self.repo / ".coord"
        self.workspace_dir.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test")

    def _git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _write(self, relative, text):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _constitution(self):
        path = self.workspace_dir / "constitution.md"
        path.write_text(
            "---\n"
            "schema: project-console-constitution/1.0\n"
            "status: draft\n"
            'project: "Prova"\n'
            'updated_at: ""\n'
            'approved_at: ""\n'
            'approved_sha256: ""\n'
            "---\n\n"
            "# Costituzione\n\n"
            f"{onboarding_findings.START}\n"
            "## 0. Stato di partenza e decisioni mancanti\n"
            f"{onboarding_findings.END}\n\n"
            "## 1. Obiettivo\n\nUn prodotto verificabile.\n",
            encoding="utf-8",
        )
        return path

    def test_scan_detects_real_stack_without_reading_env(self):
        self._write(
            "frontend/package.json",
            '{"dependencies":{"vue":"3.5.0"},"devDependencies":{"vite":"7.0.0","vitest":"3.0.0"}}',
        )
        self._write("requirements.txt", "Django==5.2\ncelery==5.5\nredis==6\n")
        self._write(
            "settings.py",
            "DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql'}}\n",
        )
        sentinel = self._write(".env", "TOKEN_CHE_NON_DEVE_COMPARIRE=segreto\n")
        self._git("add", ".")
        self._git("commit", "-m", "base")

        document = onboarding_findings.scan(self.repo, self.workspace_dir)
        serializzato = yaml.safe_dump(document, allow_unicode=True)
        self.assertIn("Vue, Vite, Vitest", serializzato)
        self.assertIn("Django, Celery, Redis, PostgreSQL", serializzato)
        self.assertIn("BOOT-SECRETS", serializzato)
        self.assertNotIn("TOKEN_CHE_NON_DEVE_COMPARIRE", serializzato)
        self.assertTrue(sentinel.exists())

    def test_interview_has_ninety_traceable_questions_and_preserves_answers(self):
        domande = onboarding_questions.initial_questions()
        self.assertEqual(len(domande), 90)
        self.assertEqual(len({item["id"] for item in domande}), 90)
        self.assertEqual(len({item["area"] for item in domande}), 15)

        self._constitution()
        document = onboarding_findings.scan(self.repo, self.workspace_dir)
        onboarding_findings.save(self.workspace_dir, document)
        aggiornato = onboarding_findings.resolve(
            self.workspace_dir,
            "PROD01",
            "answered",
            "Il risultato è un gestionale locale usabile da operatori reali.",
        )
        domanda = next(item for item in aggiornato["questions"] if item["id"] == "PROD01")
        self.assertEqual(domanda["answer"], "Il risultato è un gestionale locale usabile da operatori reali.")
        self.assertIn("PROD01", (self.workspace_dir / "onboarding-questions.md").read_text(encoding="utf-8"))

        riscansione = onboarding_findings.scan(self.repo, self.workspace_dir)
        conservata = next(item for item in riscansione["questions"] if item["id"] == "PROD01")
        self.assertEqual(conservata["status"], "answered")
        self.assertEqual(conservata["answer"], domanda["answer"])

    def test_dirty_worktree_and_existing_code_become_visible_gaps(self):
        self._write("app.py", "print('ciao')\n")
        document = onboarding_findings.scan(self.repo, self.workspace_dir)
        ids = {gap["id"] for gap in document["gaps"]}
        self.assertIn("BOOT-DIRTY", ids)
        self.assertIn("BOOT-CODE-BASE", ids)
        self.assertIn("BOOT-STACK", ids)

    def test_resolve_regenerates_yaml_and_constitution_section(self):
        self._write("app.py", "print('ciao')\n")
        constitution_path = self._constitution()
        document = onboarding_findings.scan(self.repo, self.workspace_dir)
        onboarding_findings.save(self.workspace_dir, document)
        self.assertIn("BOOT-CODE-BASE", constitution_path.read_text(encoding="utf-8"))

        with self.assertRaises(SystemExit):
            onboarding_findings.resolve(
                self.workspace_dir, "BOOT-CODE-BASE", "resolved", ""
            )
        aggiornato = onboarding_findings.resolve(
            self.workspace_dir,
            "BOOT-CODE-BASE",
            "resolved",
            "Il codice esistente viene evoluto; nessun file viene riscritto da zero.",
        )
        gap = next(
            item for item in aggiornato["gaps"] if item["id"] == "BOOT-CODE-BASE"
        )
        self.assertEqual(gap["status"], "resolved")
        self.assertIn("codice esistente viene evoluto", gap["resolution"])
        self.assertIn("Il codice esistente viene evoluto", constitution_path.read_text(encoding="utf-8"))

    def test_approval_is_blocked_by_open_blocking_findings_and_unblocks_after_decision(self):
        self._write("app.py", "print('ciao')\n")
        constitution_path = self._constitution()
        document = onboarding_findings.scan(self.repo, self.workspace_dir)
        onboarding_findings.save(self.workspace_dir, document)
        workspace = Workspace.load(self.workspace_dir)
        gate = constitution.gate(workspace)
        self.assertEqual(gate["status"], "draft")
        self.assertTrue(gate["blocking_findings"])
        self.assertIn("decisioni di partenza", gate["message"])

        with self.assertRaises(constitution.ConstitutionInvalid) as errore:
            constitution.approve(workspace)
        self.assertIn("BOOT-CODE-BASE", str(errore.exception))
        self.assertEqual(constitution.load(workspace)["status"], "draft")

        for gap in document["gaps"]:
            gap["status"] = "not_applicable"
            gap["resolution"] = "Gap di prova chiuso dopo una decisione esplicita."
        for domanda in document["questions"]:
            domanda["status"] = "not_applicable"
            domanda["answer"] = "Domanda di prova non pertinente, con motivazione esplicita."
        onboarding_findings.save(self.workspace_dir, document)
        approvata = constitution.approve(workspace)
        self.assertEqual(approvata["status"], "approved")
        self.assertTrue(constitution_path.is_file())

    def test_an_unreadable_audit_fails_closed(self):
        self._constitution()
        (self.workspace_dir / "onboarding-findings.yaml").write_text(
            "gaps: [\n", encoding="utf-8"
        )
        workspace = Workspace.load(self.workspace_dir)
        with self.assertRaises(constitution.ConstitutionInvalid):
            constitution.approve(workspace)


if __name__ == "__main__":
    unittest.main()
