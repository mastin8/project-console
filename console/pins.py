"""I timbri stantii: si leggono dal report e si riallineano con UN comando.

Legge del project-tool (2026-10-20). La rifinitura serve a sapere se il tool funziona. I timbri
— le impronte che una prova dichiara di stare misurando — non sono lavoro di ufficio: quando una
prova e' verde ma il suo pin nomina una revisione che non esiste piu', l'agente lo dichiara nel
report e il console li riallinea TUTTI con un pulsante solo.

Forma dichiarata dal report (una voce per timbro)::

    fingerprint_mismatches:
      - {label: F5, file: tenders/tests/x.py,
         path: tenders/services/y.py, declared: <vecchio sha256>, live: <nuovo sha256>}

``file`` e' il file che CONTIENE il letterale da riscrivere; ``path`` e' cio' che il timbro
descrive (per chi legge). L'applicazione sostituisce ``declared`` con ``live`` dentro ``file``,
una copia prima, e rifiuta la voce se il letterale non c'e' piu' o se il file non si legge.

Uso::

    python3 console/pins.py --workspace <progetto>            # resoconto
    python3 console/pins.py --workspace <progetto> --apply    # riallinea tutti
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workspace import Workspace  # noqa: E402

CHIAVI = ("fingerprint_mismatches", "pins", "timbri")
FASI = ("A", "E", "T", "R")


def _leggi(percorso: Path):
    try:
        return yaml.load(
            percorso.read_text(encoding="utf-8", errors="replace"),
            Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
        ) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _radici(ws):
    """Dove si risolvono i path: il workspace e il repository che lo contiene."""
    viste = [ws.root]
    for candidato in (ws.root.parent, Path.cwd()):
        if candidato not in viste:
            viste.append(candidato)
    return viste


def _risolvi(ws, relativo):
    for radice in _radici(ws):
        percorso = (radice / str(relativo)).resolve()
        if percorso.is_file():
            return percorso
    return None


def _report_corrente(ws, voce):
    """L'ultimo report registrato per la rifinitura (l'attempt piu' alto)."""
    migliore = None
    for fase in FASI:
        registrato = (voce.get("phases") or {}).get(fase) or {}
        percorso = registrato.get("report")
        if not percorso:
            continue
        numero = int(registrato.get("attempt") or 0)
        if migliore is None or numero >= migliore[0]:
            migliore = (numero, str(percorso))
    return migliore[1] if migliore else None


def _voci(ws, documento):
    for voce in documento.get("items") or []:
        if not isinstance(voce, dict) or voce.get("active") is False:
            continue
        report = _report_corrente(ws, voce)
        if not report:
            continue
        dati = _leggi(ws.path(report)) if hasattr(ws, "path") else _leggi(ws.root / report)
        for chiave in CHIAVI:
            elenco = dati.get(chiave)
            if not isinstance(elenco, list):
                continue
            for indice, timbro in enumerate(elenco):
                if not isinstance(timbro, dict):
                    continue
                file_ = str(timbro.get("file") or "").strip()
                dichiarato = str(timbro.get("declared") or "").strip()
                vivo = str(timbro.get("live") or "").strip()
                if not (file_ and dichiarato and vivo):
                    continue
                yield {
                    "obligation": str(voce.get("id") or ""),
                    "report": report,
                    "index": indice,
                    "label": str(timbro.get("label") or f"{voce.get('id')}#{indice + 1}"),
                    "file": file_,
                    "path": str(timbro.get("path") or ""),
                    "declared": dichiarato,
                    "live": vivo,
                }


def scan(ws):
    """I timbri diversi dichiarati dai report correnti delle rifiniture attive."""
    documento = _leggi(ws.refinements_path)
    voci = list(_voci(ws, documento))
    for voce in voci:
        percorso = _risolvi(ws, voce["file"])
        if percorso is None:
            voce["status"] = "file_assente"
            voce["occurrences"] = 0
            continue
        testo = percorso.read_text(encoding="utf-8", errors="replace")
        voce["occurrences"] = testo.count(voce["declared"])
        if voce["occurrences"]:
            voce["status"] = "da_raccordare"
        elif voce["live"] in testo:
            voce["status"] = "gia_allineato"
        else:
            voce["status"] = "letterale_assente"
    return voci


def _backup(ws, percorso):
    cartella = ws.root / ".pin-backups"
    cartella.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y%m%dT%H%M%S")
    copia = cartella / f"{marca}-{percorso.name}"
    shutil.copy2(percorso, copia)
    return copia


def apply(ws):
    """Sostituisce ogni ``declared`` con il suo ``live`` dentro il file dichiarato.

    Un solo passaggio, nessun prompt: le voci non applicabili restano dichiarate nel resoconto.
    """
    risultati = []
    for voce in scan(ws):
        esito = dict(voce)
        if voce["status"] != "da_raccordare":
            risultati.append(esito)
            continue
        percorso = _risolvi(ws, voce["file"])
        if percorso is None:
            esito["status"] = "file_assente"
            risultati.append(esito)
            continue
        testo = percorso.read_text(encoding="utf-8")
        sostituzioni = testo.count(voce["declared"])
        copia = _backup(ws, percorso)
        nuovo = testo.replace(voce["declared"], voce["live"])
        maniglia, temporaneo = tempfile.mkstemp(dir=str(percorso.parent), prefix=".pin-")
        try:
            with os.fdopen(maniglia, "w", encoding="utf-8") as flusso:
                flusso.write(nuovo)
            os.replace(temporaneo, percorso)
        except Exception:
            try:
                os.unlink(temporaneo)
            except OSError:
                pass
            raise
        esito.update(
            {
                "status": "raccordato",
                "occurrences": sostituzioni,
                "backup": str(copia),
            }
        )
        risultati.append(esito)
    return risultati


def _riassunto(voci):
    fatti = [voce for voce in voci if voce.get("status") == "raccordato"]
    aperti = [voce for voce in voci if voce.get("status") not in ("raccordato", "gia_allineato")]
    return {
        "ok": not aperti,
        "totale": len(voci),
        "raccordati": len(fatti),
        "aperti": len(aperti),
        "voci": voci,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Timbri diversi: resoconto e raccordo unico")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    voci = apply(ws) if args.apply else scan(ws)
    riassunto = _riassunto(voci)
    if args.json:
        print(json.dumps(riassunto, ensure_ascii=False, indent=2))
    else:
        for voce in voci:
            print(f"{voce['status']:16} {voce['label']:8} {voce['file']} ({voce['occurrences']}×)")
        print(
            f"raccordati={riassunto['raccordati']} aperti={riassunto['aperti']} totale={riassunto['totale']}"
        )
    return 0 if riassunto["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
