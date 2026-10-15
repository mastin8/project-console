#!/usr/bin/env python3
"""Cosa c'e' da fare dopo: il testimone che chi finisce lascia a chi viene.

Perche' esiste: nei report c'e' GIA' scritto cosa succede dopo — misurato sul progetto di origine
il 2026-10-15: `next` 141 volte, `next_tasks` 254, `next_task` e `next_required` qualche decina — e
la pagina non l'ha mai mostrato. Chi apriva il coordinatore vedeva lo stato e non le istruzioni,
quindi l'unico modo di sapere cosa fare era leggere a mano i report. Questa e' la lettura che
mancava, piu' la misura di chi NON l'ha lasciato.

Le chiavi lette sono quelle che nei fatti contengono la direzione:

  `next`          in prosa, di solito nel puntatore: «next: ratifica D008; QA02/QA03 possono partire»
  `next_tasks`    una lista: «DOC04 accettata: DOC01A diventa il candidato»
  `next_task`, `next_actions`, `next_required`   varianti singolari

NON si legge `recommendation`: nei puntatori e' il VERDETTO (`accept_unit`,
`pass_with_declared_limits`), non una direzione. E non si legge `handoff_frozen_at_take`, che
malgrado il nome sono le impronte congelate alla presa.

Sola lettura, tranne una cosa: `scrivi()` deposita una transizione che mette una nota di testimone
sulla fase, per chi finisce senza avere un report da scrivere.

Uso::

    python3 registers/handoff.py --workspace <progetto>            # cosa c'e' da fare dopo
    python3 registers/handoff.py --workspace <progetto> --gaps      # chi non l'ha lasciato
    python3 registers/handoff.py --workspace <progetto> --next OVR01E --note "testo"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def _carica(flusso):
    """Legge un registro col parser veloce quando c'e' (libyaml): 17 volte piu' rapido su un
    registro da 2 MB (misurato: 0,09 s contro 1,55 s). Stesso sottoinsieme sicuro di YAML, nessun
    costruttore custom: e' `safe_load` scritto in C, non un'altra sintassi."""
    return yaml.load(flusso, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import apply_transitions  # noqa: E402
from workspace import Workspace, lock_file  # noqa: E402

#: Le chiavi che dicono la direzione, in ordine di fiducia.
CHIAVI = ("next", "next_tasks", "next_task", "next_actions", "next_required")
DONE = ("accepted",)
LIVE = ("active", "taken", "pre_registered", "ready", "active_extension")


def _testi(valore):
    """Scalare, lista o mappa: si normalizza in una lista di righe leggibili."""
    if valore is None:
        return []
    if isinstance(valore, str):
        return [valore.strip()] if valore.strip() else []
    if isinstance(valore, (int, float, bool)):
        return [str(valore)]
    if isinstance(valore, list):
        fuori = []
        for voce in valore:
            fuori.extend(_testi(voce))
        return fuori
    if isinstance(valore, dict):
        # Una voce strutturata (`id` + `note`) e' UNA istruzione, non due: si tiene insieme, che e'
        # come l'ha scritta chi ha finito.
        identificativo = valore.get("id") or valore.get("task") or valore.get("phase")
        testo = valore.get("note") or valore.get("what") or valore.get("text") or valore.get("why")
        if identificativo and testo:
            return [f"{identificativo} — {' '.join(str(testo).split())}"]
        # Una mappa di istruzioni: si tiene il contenuto, non la sintassi.
        fuori = []
        for chiave, dentro in valore.items():
            righe = _testi(dentro)
            fuori.extend(f"{chiave}: {riga}" if len(righe) == 1 else righe for riga in (righe or [""]))
        return [riga for riga in fuori if str(riga).strip()]
    return [str(valore)]


def _momento(valore):
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.replace(tzinfo=timezone.utc)
    testo = str(valore or "").strip().strip("'\"")
    for candidato in (testo, testo.replace(" ", "T", 1)):
        try:
            momento = datetime.fromisoformat(candidato)
        except ValueError:
            continue
        return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
    return None


def _leggi(path):
    try:
        return _carica(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def ultimo_report(ws, state, fase):
    """(percorso, documento) del tentativo corrente: dal puntatore, dal registro, o dal disco."""
    puntatore = ws.reports_dir / f"{fase}.yaml"
    documento = _leggi(puntatore) if puntatore.exists() else {}
    riferimento = documento.get("report") or documento.get("report_ref")
    if riferimento:
        target = ws.root / str(riferimento)
        if target.is_file():
            return target, puntatore, documento, _leggi(target)
    dal_registro = ((state.get("tasks") or {}).get(fase) or {}).get("report")
    if dal_registro and (ws.root / str(dal_registro)).is_file():
        target = ws.root / str(dal_registro)
        return target, puntatore, documento, _leggi(target)
    cartella = ws.reports_dir / fase
    if cartella.is_dir():
        tentativi = sorted(cartella.glob("attempt-*.yaml"), key=lambda p: p.stat().st_mtime)
        if tentativi:
            return tentativi[-1], puntatore, documento, _leggi(tentativi[-1])
    return None, puntatore, documento, {}


def _quando(documento, percorso):
    for chiave in ("published_at", "prepared_at", "dated", "completed_at"):
        momento = _momento(documento.get(chiave))
        if momento:
            return momento
    if percorso and percorso.exists():
        return datetime.fromtimestamp(percorso.stat().st_mtime, tz=timezone.utc)
    return None


def dichiarazioni(ws, state=None, tasks_doc=None):
    """Cosa c'e' da fare dopo, dichiarato da chi ha finito: una voce per fase, la piu' recente."""
    state = state if state is not None else (_leggi(ws.state_path))
    tasks_doc = tasks_doc if tasks_doc is not None else (_leggi(ws.path(ws.tasks)))
    unita = {str(u.get("id")): u for u in tasks_doc.get("units") or [] if u.get("id")}
    fasi = {}
    for task in tasks_doc.get("tasks") or []:
        if task.get("id"):
            fasi[str(task["id"])] = str(task.get("unit_id") or "")
    per_unita = {}
    for fase_id, unit_id in fasi.items():
        per_unita.setdefault(unit_id, []).append(fase_id)
    registrate = state.get("tasks") or {}
    chiuse = {
        unit_id
        for unit_id, elenco in per_unita.items()
        if elenco and all((registrate.get(f) or {}).get("status") in DONE for f in elenco)
    }
    fuori = []
    for fase in sorted(fasi):
        percorso, puntatore, doc_puntatore, doc_report = ultimo_report(ws, state, fase)
        if percorso is None:
            continue
        voci = []
        for chiave in CHIAVI:
            for testo in _testi(doc_report.get(chiave)) + _testi(doc_puntatore.get(chiave)):
                if testo and testo not in [v["text"] for v in voci]:
                    voci.append({"key": chiave, "text": testo})
        fuori.append(
            {
                "phase": fase,
                "unit": fasi[fase],
                "block": str((unita.get(fasi[fase]) or {}).get("domain") or "senza-dominio"),
                "status": (registrate.get(fase) or {}).get("status", "pending"),
                "verdict": doc_puntatore.get("verdict") or doc_report.get("verdict"),
                "source": str(percorso.relative_to(ws.root)),
                "when": _quando(doc_puntatore, percorso) or _quando(doc_report, percorso),
                "unit_open": fasi[fase] not in chiuse,
                "items": voci,
            }
        )
    # Prima le fasi la cui unita' e' ancora aperta (li' il testimone serve adesso), poi le piu' recenti.
    fuori.sort(key=lambda v: (not v["unit_open"], -(v["when"].timestamp() if v["when"] else 0)))
    return fuori


def lacune(ws, state=None):
    """Chi ha consegnato senza dire cosa fare dopo: la misura dell'obbligo mancato.

    Una consegna senza direzione lascia il lavoro fermo al primo che apre la pagina: e' l'obbligo
    che l'utente ha chiesto di rendere visibile, e una lacuna si vede solo se la si conta.
    """
    fuori = []
    for voce in dichiarazioni(ws, state):
        if not voce["items"]:
            fuori.append(
                {
                    "phase": voce["phase"],
                    "unit": voce["unit"],
                    "block": voce["block"],
                    "status": voce["status"],
                    "source": voce["source"],
                    "when": voce["when"],
                    "unit_open": voce["unit_open"],
                }
            )
    # Prima le lacune che contano adesso: quelle di un'unita' ancora aperta.
    fuori.sort(key=lambda v: (not v["unit_open"], -(v["when"].timestamp() if v["when"] else 0)))
    return fuori


def scrivi(ws, fase, testo):
    """Una nota di testimone sulla fase, per chi finisce senza avere un report da scrivere.

    Si scrive nel registro, con la coda di sempre (lock, validazione, ripristino): un testimone
    lasciato a mano in un file libero non lo leggerebbe nessuno.
    """
    state = _leggi(ws.state_path)
    if fase not in (state.get("tasks") or {}):
        raise apply_transitions.TransitionError(f"fase non nel registro: {fase}")
    adesso = datetime.now().strftime("%Y-%m-%d")
    richiesta = {
        "schema": apply_transitions.SCHEMA,
        "file": ws.state,
        "anchor": f"  {fase}:",
        "field": f"handoff_{adesso.replace('-', '_')}",
        "text": (
            f"{testo.strip()} — lasciato dalla pagina di coordinamento il "
            f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')}"
        ),
    }
    import fcntl

    # Lo stesso lock delle corsie: due scrittori sugli stessi registri non devono mai sovrapporsi.
    lock = Path(lock_file(ws.root))
    with open(lock, "a+") as maniglia:
        fcntl.flock(maniglia, fcntl.LOCK_EX)
        try:
            apply_transitions.apply_request(richiesta, pack=ws.root, validate_after=True)
        finally:
            fcntl.flock(maniglia, fcntl.LOCK_UN)
    return {"applied": f"{ws.state}#handoff_{adesso.replace('-', '_')}", "phase": fase}


def testi_dalla_registry(ws, fase):
    """Anche le note di testimone scritte a mano nel registro, che non stanno in un report."""
    state = _leggi(ws.state_path)
    voce = (state.get("tasks") or {}).get(fase) or {}
    return [
        {"key": chiave, "text": _testi(valore)[0]}
        for chiave, valore in voce.items()
        if str(chiave).startswith("handoff_")
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    parser.add_argument("--gaps", action="store_true", help="chi ha consegnato senza dire cosa fare dopo")
    parser.add_argument("--next", dest="fase", help="la fase su cui lasciare una nota di testimone")
    parser.add_argument("--note", help="il testo della nota")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    if args.fase:
        if not args.note:
            parser.error("--next vuole --note")
        print(scrivi(ws, args.fase, args.note))
        return 0
    if args.gaps:
        for voce in lacune(ws):
            quando = voce["when"].strftime("%m-%d %H:%M") if voce["when"] else "?"
            print(f"{voce['phase']:<14} {voce['block']:<14} {voce['status']:<12} {quando}  {voce['source']}")
        print(f"\nlacune: {len(lacune(ws))}")
        return 0
    for voce in dichiarazioni(ws):
        if not voce["items"]:
            continue
        quando = voce["when"].strftime("%m-%d %H:%M") if voce["when"] else "?"
        print(
            f"{voce['phase']:<14} {voce['block']:<14} {voce['status']:<11} {quando} "
            f"unita' {'APERTA' if voce.get('unit_open') else 'chiusa'}"
        )
        for item in voce["items"]:
            print(f"    [{item['key']}] {item['text'][:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
