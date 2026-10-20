"""La legge dei timbri: elenco dal report e raccordo unico.

I casi sono quelli che si presentano davvero: un pin che nomina una revisione vecchia (da
raccordare), un pin gia' allineato, un letterale sparito e un file che non c'e'. Il raccordo non
deve chiedere niente e non deve toccare cio' che non si puo' sostituire.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pins  # noqa: E402
from workspace import Workspace  # noqa: E402

VECCHIO = "0ef21e2c" + "0" * 56
NUOVO = "aec6310d" + "1" * 56


def _workspace(radice: Path, declared=VECCHIO, live=NUOVO):
    file_ = "tenders/tests/prova.py"
    (radice / "tenders" / "tests").mkdir(parents=True)
    (radice / file_).write_text(
        f'PIN = "{declared}"\n"""misura {declared}"""\n', encoding="utf-8"
    )
    (radice / "refinements.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "project-console-refinements/1.0",
                "items": [
                    {
                        "id": "OBBLIGO",
                        "phases": {
                            "E": {
                                "status": "partial",
                                "attempt": 9,
                                "report": "reports/E/attempt-9.yaml",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (radice / "reports" / "E").mkdir(parents=True)
    (radice / "reports" / "E" / "attempt-9.yaml").write_text(
        yaml.safe_dump(
            {
                "phase": "E",
                "fingerprint_mismatches": [
                    {
                        "label": "F5",
                        "file": file_,
                        "path": "tenders/services/prova.py",
                        "declared": declared,
                        "live": live,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return Workspace.load(radice)


class PinsTests(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.addCleanup(self.cartella.cleanup)
        self.radice = Path(self.cartella.name)

    def test_scan_declares_every_occurrence(self):
        ws = _workspace(self.radice)
        voci = pins.scan(ws)
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["status"], "da_raccordare")
        self.assertEqual(voci[0]["occurrences"], 2)

    def test_apply_rewrites_all_occurrences_once_and_keeps_a_copy(self):
        ws = _workspace(self.radice)
        voci = pins.apply(ws)
        self.assertEqual(voci[0]["status"], "raccordato")
        testo = (self.radice / "tenders" / "tests" / "prova.py").read_text(encoding="utf-8")
        self.assertNotIn(VECCHIO, testo)
        self.assertEqual(testo.count(NUOVO), 2)
        copie = list((self.radice / ".pin-backups").iterdir())
        self.assertEqual(len(copie), 1)
        self.assertIn(VECCHIO, copie[0].read_text(encoding="utf-8"))
        # Idempotente: la seconda passata non tocca nulla e non crea una seconda copia.
        seconda = pins.apply(ws)
        self.assertEqual(seconda[0]["status"], "gia_allineato")
        self.assertEqual(len(list((self.radice / ".pin-backups").iterdir())), 1)

    def test_apply_declares_what_it_cannot_replace(self):
        ws = _workspace(self.radice, declared="f" * 64)
        percorso = self.radice / "tenders" / "tests" / "prova.py"
        percorso.write_text('PIN = "altro"\n', encoding="utf-8")
        riassunto = pins._riassunto(pins.apply(ws))
        self.assertFalse(riassunto["ok"])
        self.assertEqual(riassunto["aperti"], 1)
        self.assertEqual(riassunto["voci"][0]["status"], "letterale_assente")
        testo = percorso.read_text(encoding="utf-8")
        self.assertEqual(
            testo,
            'PIN = "altro"\n',
            "un timbro non sostituibile non deve riscrivere il file",
        )

    def test_missing_file_is_declared_not_invented(self):
        ws = _workspace(self.radice)
        (self.radice / "tenders" / "tests" / "prova.py").unlink()
        voci = pins.scan(ws)
        self.assertEqual(voci[0]["status"], "file_assente")


if __name__ == "__main__":
    unittest.main()
