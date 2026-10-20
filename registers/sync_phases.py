#!/usr/bin/env python3
"""Apre in `state.yaml` le fasi che `tasks.yaml` dichiara e che il registro non conosce ancora.

Perche' esiste: una fase non si puo' prendere se il registro non ha la sua voce. Su un progetto
appena nato `tasks.yaml` e' scritto e `state.yaml#tasks` e' vuoto, quindi la prima presa viene
RIFIUTATA dall'applicatore («ancora non trovata») — misurato il 2026-10-15 sul primo progetto
nuovo, ed e' il primo muro che incontra chi comincia.

Scrive SOLO le voci mancanti, con `status: pending`, e non tocca quelle che esistono: la storia di
una fase non si azzera. Il file non viene riserializzato — si inseriscono delle righe — quindi i
commenti e l'ordine di tutto il resto restano come sono. Backup, validazione e ripristino sono
quelli di `apply_transitions.py`: una scrittura sui registri passa sempre di li'.

Uso::

    python3 registers/sync_phases.py --workspace /percorso/progetto            # mostra cosa farebbe
    python3 registers/sync_phases.py --workspace /percorso/progetto --apply    # lo fa
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import apply_transitions  # noqa: E402 - backup, validazione e ripristino sono suoi
from registers import plan  # noqa: E402 - le fasi si aprono solo dal piano approvato
from console import constitution  # noqa: E402 - nessun task si apre prima dell'approvazione
from workspace import Workspace  # noqa: E402


def fasi_dichiarate(tasks_doc):
    """(id, kind) delle fasi, nell'ordine di `tasks.yaml`."""
    return [
        (str(task.get("id")), str(task.get("kind") or ""))
        for task in tasks_doc.get("tasks") or []
        if task.get("id")
    ]


def righe_nuove(fase, kind):
    righe = [f"  {fase}:", "    status: pending", "    attempt: 0"]
    if kind:
        righe.append(f"    kind: {kind}")
    return righe


def inserisci(testo, da_aprire):
    """Le righe delle fasi mancanti, dentro il blocco `tasks:` (o creandolo in fondo)."""
    righe = testo.splitlines()
    # Il blocco puo' esistere vuoto in tre forme — `tasks:`, `tasks: {}`, `tasks: []` — e tutte
    # vanno riconosciute: senza, il blocco si aggiunge in fondo e il registro resta con due chiavi
    # `tasks` (misurato su un progetto nuovo, e intercettato dal validatore).
    indice = next(
        (i for i, riga in enumerate(righe) if re.match(r"^tasks:\s*(\{\}|\[\])?\s*(#.*)?$", riga)),
        None,
    )
    blocco = [riga for fase, kind in da_aprire for riga in righe_nuove(fase, kind)]
    if indice is None:
        return righe + ["tasks:"] + blocco
    if righe[indice].rstrip().endswith(("{}", "[]")):
        righe[indice] = "tasks:"
    fine = indice + 1
    while fine < len(righe) and (
        not righe[fine].strip() or righe[fine].startswith((" ", "\t", "-"))
    ):
        fine += 1
    return righe[:fine] + blocco + righe[fine:]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    parser.add_argument("--apply", action="store_true", help="scrive davvero (senza: mostra e basta)")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    try:
        constitution.require_approved(ws)
        plan.require_approved(ws)
    except (constitution.ConstitutionError, plan.PlanError) as error:
        print(f"BLOCCATO: {error}")
        return 1
    tasks_doc = yaml.safe_load(ws.path(ws.tasks).read_text(encoding="utf-8")) or {}
    state = yaml.safe_load(ws.state_path.read_text(encoding="utf-8")) or {}
    registrate = set(state.get("tasks") or {})
    da_aprire = [fase for fase in fasi_dichiarate(tasks_doc) if fase[0] not in registrate]
    if not da_aprire:
        print(f"niente da aprire: le {len(registrate)} fasi dichiarate sono tutte nel registro")
        return 0
    for fase, kind in da_aprire:
        print(f"da aprire  {fase}  ({kind or 'senza tipo'})")
    if not args.apply:
        print(f"\n{len(da_aprire)} fasi da aprire. Rilancia con --apply per scriverle.")
        return 0

    testo = ws.state_path.read_text(encoding="utf-8")
    backup = Path(tempfile.mkstemp(prefix="sync-fasi-", suffix=".bak")[1])
    shutil.copy2(ws.state_path, backup)
    try:
        ws.state_path.write_text("\n".join(inserisci(testo, da_aprire)) + "\n", encoding="utf-8")
        valido, report = apply_transitions.validate(ws.root)
        if not valido:
            raise apply_transitions.TransitionError(report)
    except Exception as error:  # noqa: BLE001 - qualunque cosa vada storta: si torna indietro
        shutil.copy2(backup, ws.state_path)
        print(f"RIPRISTINATO {ws.state_path}: {error}")
        return 1
    finally:
        backup.unlink(missing_ok=True)
    print(f"\nscritte {len(da_aprire)} fasi in {ws.state_path} (registro valido)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
