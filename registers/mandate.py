#!/usr/bin/env python3
"""Il prompt di una fase: quello del quaderno se c'e', altrimenti composto dal registro.

Perche' esiste: attivare una fase riservava la fase e depositava l'ordine, ma se il quaderno non
aveva una sezione per QUELLA fase l'ordine usciva con `prompt: null` — e chi attivava non trovava
niente da incollare in una chat. Misurato il 2026-10-15: su `OVR01E` e `HIST01A` il quaderno tace,
quindi attivarle non dava nessun prompt da consegnare a un esecutore.

Il prompt composto non inventa lavoro: mette in fila quello che il registro GIA' sa — la fase, il
tipo, il file di consegna atteso, i criteri di accettazione, il perimetro dichiarato con le sue
impronte, e le tre regole che valgono sempre (prendi la fase prima di scrivere, prova solo cio' che
tocchi, lascia scritto cosa c'e' da fare dopo). Quello che il registro NON sa — il contenuto
tecnico del lavoro — resta scritto come tale: `DA COMPLETARE`, invece di essere riempito di prosa
inventata.

Sola lettura. Uso::

    python3 registers/mandate.py --workspace <progetto> --phase OVR01E
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def _carica(flusso):
    """Legge un registro col parser veloce quando c'e' (libyaml): 17 volte piu' rapido su un
    registro da 2 MB (misurato: 0,09 s contro 1,55 s). Stesso sottoinsieme sicuro di YAML, nessun
    costruttore custom: e' `safe_load` scritto in C, non un'altra sintassi."""
    return yaml.load(flusso, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import activate  # noqa: E402 - le impronte del perimetro sono sue
import next_prompts  # noqa: E402 - il quaderno, per il prompt che esiste gia'
from workspace import Workspace  # noqa: E402

#: Che ruolo tocca, dal tipo di fase. E' un'etichetta, non un permesso: la mappa vera e' in
#: `agents/agents.yaml` del workspace, e chi dispatcha la usa.
RUOLI = {
    "analysis": "analisi",
    "implementation": "esecuzione",
    "independent_verification": "verifica indipendente",
    "functional_acceptance": "accettazione",
}


def _leggi(path):
    try:
        return _carica(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def componi(ws, fase, state=None, tasks_doc=None):
    """Un prompt per quella fase, costruito da cio' che il registro sa."""
    state = state if state is not None else _leggi(ws.state_path)
    tasks_doc = tasks_doc if tasks_doc is not None else _leggi(ws.path(ws.tasks))
    task = next((t for t in tasks_doc.get("tasks") or [] if str(t.get("id")) == fase), None)
    if task is None:
        raise SystemExit(f"fase non dichiarata in {ws.tasks}: {fase}")
    unita = next(
        (u for u in tasks_doc.get("units") or [] if str(u.get("id")) == str(task.get("unit_id"))),
        {},
    )
    registro = (state.get("tasks") or {}).get(fase) or {}
    tipo = str(task.get("kind") or "")
    ruolo = RUOLI.get(tipo, "esecuzione")
    attempt = 1
    numeri = [
        int(v.get("attempt") or 0)
        for v in state.get("active_claims") or []
        if str(v.get("task_id")) == fase and str(v.get("attempt") or "").isdigit()
    ]
    if numeri:
        attempt = max(numeri) + 1 if registro.get("status") in ("needs_changes", "failed") else max(numeri)
    consegna = f"{ws.deliverable_prefix}{fase}/attempt-{attempt}.yaml"
    revisione, fonte_revisione = activate.impronte(ws, state, fase)
    criteria = task.get("acceptance_criteria") or []
    if isinstance(criteria, dict):
        criteria = [f"{k}: {v}" for k, v in criteria.items()]

    # Dove si lavora: il repository che contiene il workspace, se c'e' — il codice sta li'.
    radici = activate.radici(ws)
    radice_lavoro = next((r for nome, r in radici if nome == "repository"), ws.root)
    righe = [
        f"Lavora in {radice_lavoro}. Sei un agente di {ruolo}: non coordinare, non dispatchare",
        "figli, non chiedere conferme.",
        "",
        f"FASE: {fase} — {task.get('title') or 'senza titolo'}",
        f"UNITA': {unita.get('id') or task.get('unit_id')} "
        f"({unita.get('domain') or 'senza blocco'}) — {unita.get('title') or ''}".rstrip(),
        f"TIPO: {tipo or 'non dichiarato'}"
        + (
            f" · stato nel registro: {registro.get('status')}"
            + (f" (tentativo {registro.get('attempt')})" if registro.get("attempt") else "")
            if registro
            else ""
        ),
    ]
    if unita.get("deliverable"):
        righe += ["", f"RISULTATO ATTESO DELL'UNITA': {unita['deliverable']}"]
    if registro.get("status") in ("needs_changes", "failed"):
        righe += [
            "",
            "QUESTA FASE E' STATA RESPINTA IN VERIFICA: leggi il report precedente e il suo verdetto",
            f"({registro.get('report') or 'il report della fase'}) prima di ricominciare. Il nuovo",
            "tentativo si misura sugli stessi casi che l'hanno respinta.",
        ]
    if criteria:
        righe += ["", "CRITERI DI ACCETTAZIONE (dal registro):"]
        righe += [f"- {str(c).strip()}" for c in criteria]
    righe += [
        "",
        "COSA FARE (il registro non lo dice: va scritto qui prima di cominciare)",
        "DA COMPLETARE — in una riga: cosa deve esistere quando questa fase e' finita.",
        "",
        f"CONSEGNA: {consegna} (verifica che NON esista) e il puntatore "
        f"{ws.deliverable_prefix}{fase}.yaml.",
    ]
    if revisione:
        righe += [
            "",
            f"PERIMETRO E REVISIONE ({fonte_revisione}, impronte di adesso):",
        ]
        righe += [f"- {voce['path']}  {voce['sha256'][:16]}…" for voce in revisione]
    else:
        righe += [
            "",
            "PERIMETRO: dichiara qui i file che tocchi — il registro per questa fase non ne ha.",
        ]
    righe += [
        "",
        f"REGISTRO: in {ws.state} esiste la voce di claim {fase}: e' tua. NON scrivere il registro",
        f"a mano: deposita in {ws.transitions}/ la presa con taken_by = il tuo nome canonico PRIMA",
        f"del primo byte, e la richiesta di rilascio alla fine (formato in {ws.transitions}/README.md).",
        "Se un'altra corsia l'ha gia' presa, fermati e dillo.",
        "",
        "VERIFICA: prova SOLO cio' che tocchi, UNA volta, subito prima di consegnare. Dichiara",
        "comando, esito, durata e cio' che NON hai rieseguito, col motivo.",
        "",
        "TESTIMONE: nel report scrivi `next` con cosa c'e' da fare dopo. Chi prende il lavoro da te",
        "lo deve leggere dalla pagina del coordinatore, non da una chat.",
    ]
    return {
        "source": "composto dal registro (il quaderno non ha una sezione per questa fase)",
        "role": ruolo,
        "text": "\n".join(righe).strip() + "\n",
        "missing": [] if criteria else ["criteri di accettazione"],
        "revision_source": fonte_revisione,
    }


def per(ws, fase, state=None):
    """Il prompt della fase: prima il quaderno, che e' scritto a mano e vale di piu'.

    `state` si passa gia' caricato quando c'e': evita di rileggere un registro da 1,9 MB per ogni
    riga della pagina.
    """
    # Cache per fase: la pagina chiede il prompt di ogni riga attivata insieme, e senza questa
    # ogni riga ricostruiva il quaderno (o componeva da capo) — misurato 4-5 s per prompt.
    chiave = (str(ws.root), fase)
    if chiave in _CACHE:
        return _CACHE[chiave]
    dal_quaderno = activate.prompt_per(ws, fase)
    if dal_quaderno and dal_quaderno.get("text"):
        esito = {
            "source": dal_quaderno["source"],
            "role": None,
            "text": dal_quaderno["text"],
            "missing": [],
        }
    else:
        esito = componi(ws, fase, state=state)
    _CACHE[chiave] = esito
    return esito


def impronta(testo):
    """L'impronta del prompt: serve a dire se quello congelato e' ancora quello giusto."""
    import hashlib

    return hashlib.sha256(str(testo or "").encode("utf-8")).hexdigest()


def da_ordine(ws, fase):
    """Il prompt congelato nell'ordine depositato per quella fase, se c'e'.

    E' il testo che un esecutore ha ricevuto: si legge da li' invece di ricomporlo, perche' un
    prompt che cambia dopo essere stato consegnato e' un prompt perso.
    """
    for nome in sorted(activate.ordini_aperti(ws).get(fase) or []):
        percorso = ws.root / nome
        if not percorso.is_file():
            continue
        documento = _leggi(percorso)
        testo = documento.get("prompt")
        if testo:
            return {
                "file": nome,
                "text": testo,
                "sha256": documento.get("prompt_sha256") or impronta(testo),
                "frozen_at": documento.get("prompt_frozen_at"),
                "source": documento.get("prompt_source"),
            }
    return None


#: Cache dei prompt composti, per (workspace, fase).
_CACHE = {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    parser.add_argument("--phase", required=True, help="la fase di cui comporre il prompt")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    next_prompts.configure(queue=ws.queue, deliverable_prefix=ws.deliverable_prefix)
    esito = per(ws, args.phase)
    print(f"# fonte: {esito['source']}")
    print(esito["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
