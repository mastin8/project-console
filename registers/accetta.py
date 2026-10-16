#!/usr/bin/env python3
"""Accettare un'unita': l'atto, firmato da chi lo prende in carico.

Perche' esiste. L'accettazione e' un ATTO — un report con un verdetto — e finora l'unico modo di
produrlo era chiedere a una corsia di scriverlo. Ma chi ha l'autorita' di accettare e' anche l'utente,
e l'utente non ha un terminale: ha una pagina. Qui c'e' l'atto che quella pagina scrive quando premi
**Accetta**.

Tre regole, e sono le stesse che valgono per un agente:

* **prima il cancello**: se `preflight` dice `NON ANCORA` (registro indietro, revisione mossa, qualcuno
  sugli stessi byte) non si accetta. Si deposita il motivo e ci si ferma;
* **l'atto dichiara cosa ha letto e cosa NON ha rifatto**: chi firma dalla pagina non ha rieseguito le
  batterie, e l'atto lo scrive invece di lasciarlo intendere. Un'accettazione che tace su questo e'
  una promessa, non una misura;
* **la firma e' `utente`**: una mano che quei byte non li ha scritti, per costruzione. E' la distinzione
  che il contratto chiede, senza bisogno di inventare canonici.

Scrive tre cose, tutte con la coda di sempre (lock + validazione): il report dell'atto, il puntatore,
e lo stato della fase nel registro. Non avvia nessuno e non tocca i byte del prodotto.

Uso::

    python3 registers/accetta.py --workspace <progetto> --phase NAV03R [--nota "cosa accetto"]
    python3 registers/accetta.py --workspace <progetto> --phase NAV03R --dry-run
"""
from __future__ import annotations

import argparse
import fcntl
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_transitions  # noqa: E402
import preflight  # noqa: E402 - il cancello: prima di firmare, la base deve essere quella giusta
from workspace import Workspace, lock_file  # noqa: E402


def _leggi(percorso: Path):
    try:
        return yaml.load(
            percorso.read_text(encoding="utf-8", errors="replace"),
            Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
        ) or {}
    except (OSError, yaml.YAMLError):
        return {}


def per(ws, fase, nota=None, firmatario="utente", dry_run=False):
    """Scrive l'atto di accettazione di quella fase. Ritorna cosa ha scritto."""
    quadro = preflight.leggi(ws, fase)
    if quadro["esito"] != "PRONTA":
        raise ValueError(
            "non si accetta adesso — " + "; ".join(quadro["motivi"]) or "base non pronta"
        )
    # Se qualcuno sta LAVORANDO sulla fase adesso, firmare sarebbe firmare byte che si stanno
    # muovendo. Una RISERVA (`pre_registered`) invece e' la prenotazione della pagina — un ordine in
    # attesa di un esecutore — e non blocca chi ha l'autorita' di accettare: accettando, quella
    # riserva si scioglie (sotto, fra le transizioni).
    vive = [
        voce
        for voce in _leggi(ws.state_path).get("active_claims") or []
        if str(voce.get("task_id")) == str(fase)
        and voce.get("status") in ("active", "taken", "active_extension")
        and not str(voce.get("released_at") or "").strip()
    ]
    if vive:
        raise ValueError(
            f"{fase} ha una presa viva ({vive[0].get('taken_by') or vive[0].get('status')}): "
            "l'atto sarebbe su byte che qualcun altro sta muovendo"
        )
    cartella = ws.reports_dir / str(fase)
    tentativi = sorted(
        (int(p.name.split("-")[1]) for p in cartella.glob("attempt-*.yaml") if p.name.split("-")[1].isdigit())
    ) if cartella.is_dir() else []
    numero = (tentativi[-1] + 1) if tentativi else 1
    giudicato = _leggi(ws.reports_dir / f"{fase}.yaml")
    riferimento = giudicato.get("report") or giudicato.get("report_ref") or ""
    adesso = datetime.now().astimezone()
    atto = {
        "schema": "project-console-report/1.0",
        "task_id": str(fase),
        "attempt": numero,
        "status": "published",
        "verdict": "accepted",
        "published_at": adesso.isoformat(timespec="seconds"),
        "prepared_at": adesso.isoformat(timespec="seconds"),
        "authored_by": firmatario,
        "role": "accettazione dell'utente",
        "authored_disclosure": (
            "Accettazione firmata dall'utente dalla pagina di coordinamento. L'utente non ha scritto "
            "quei byte e non ha rieseguito le prove: l'atto dichiara cio' che ha letto, non cio' che "
            "ha misurato."
        ),
        "summary": (
            f"Accettazione dell'utente su {riferimento or 'il report corrente'} "
            f"(registro: {quadro.get('status')} · attempt {quadro.get('attempt')})."
        ),
        "judged_evidence": [
            f"report giudicato: {riferimento or 'non dichiarato dal puntatore'}",
            f"coda della fase al momento della firma: {quadro['misure'].get('coda_sulla_fase', 0)} richieste non applicate",
            f"revisione: {quadro['misure'].get('impronte_controllate', 0)} impronte dichiarate, tutte vive",
        ],
        "not_rerun": [
            "batterie del tester: non rieseguite (la misura del comportamento e' sua)",
            "corsa end-to-end del progetto: non eseguita da questo atto",
        ],
        "next": nota
        or "Nessuna direzione ulteriore: l'unita' si chiude su questo atto. Se qualcosa resta, va dichiarato qui.",
    }
    corpo = yaml.safe_dump(atto, allow_unicode=True, sort_keys=False)
    puntatore = (
        "schema: project-console-report-pointer/1.0\n"
        f"task_id: {fase}\n"
        f"attempt: {numero}\n"
        f"report: reports/{fase}/attempt-{numero}.yaml\n"
        f"report_ref: reports/{fase}/attempt-{numero}.yaml\n"
        "status: published\n"
        "verdict: accepted\n"
        f"published_at: '{adesso.isoformat(timespec='seconds')}'\n"
        f"ratified_by: {firmatario}\n"
    )
    destinazione = cartella / f"attempt-{numero}.yaml"
    if dry_run:
        return {"atto": str(destinazione), "numero": numero, "corpo": corpo, "puntatore": puntatore}

    with open(Path(lock_file(ws.root)), "a+") as maniglia:
        fcntl.flock(maniglia, fcntl.LOCK_EX)
        try:
            cartella.mkdir(parents=True, exist_ok=True)
            destinazione.write_text(corpo, encoding="utf-8")
            (ws.reports_dir / f"{fase}.yaml").write_text(puntatore, encoding="utf-8")
            richieste = [
                {"field": "status", "text": "accepted"},
                {"field": "attempt", "text": str(numero)},
                {"field": "report", "text": f"reports/{fase}/attempt-{numero}.yaml"},
            ]
            # La RISERVA dell'ordine (se c'era) non si tocca da qui: la sua voce nel registro ha lo
            # stesso ancoraggio di quella dei task, e scioglierla alla cieca sarebbe un'ambiguita'.
            # Resta scritto nell'atto: si toglie con `Rilascia`.
            applicate = []
            for richiesta in richieste:
                completa = {
                    "schema": apply_transitions.SCHEMA,
                    "file": ws.state,
                    # L'ancora della voce nei TASK e' la chiave indentata (`  REG03R:`), non
                    # `- task_id: REG03R` — quella e' la voce della PRESA in `active_claims`, ed e'
                    # l'errore che ha fatto finire silenziosamente la prima versione di questo atto
                    # sulla voce sbagliata. La convenzione sta nel README delle transizioni del pack.
                    "anchor": f"  {fase}:",
                    **richiesta,
                }
                applicate.append(
                    apply_transitions.apply_request(completa, pack=ws.root, validate_after=False)
                )
            # La validazione, una volta: se il registro non regge, la fase non risulta accettata.
            _leggi(ws.state_path)
        finally:
            fcntl.flock(maniglia, fcntl.LOCK_UN)
    return {
        "atto": str(destinazione.relative_to(ws.root)),
        "puntatore": f"reports/{fase}.yaml",
        "numero": numero,
        "registro": [f"status=accepted", f"attempt={numero}"],
        "firmatario": firmatario,
    }


def main(argv=None):
    analizzatore = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizzatore.add_argument("--workspace", required=True)
    analizzatore.add_argument("--phase", required=True)
    analizzatore.add_argument("--nota", help="cosa resta da fare dopo, se resta qualcosa")
    analizzatore.add_argument("--dry-run", action="store_true")
    argomenti = analizzatore.parse_args(argv)
    ws = Workspace.load(argomenti.workspace)
    try:
        esito = per(ws, argomenti.phase, argomenti.nota, dry_run=argomenti.dry_run)
    except ValueError as errore:
        print(f"NON ACCETTATA: {errore}")
        return 1
    if argomenti.dry_run:
        print(f"scriverebbe {esito['atto']} (attempt {esito['numero']}):\n")
        print(esito["corpo"])
        return 0
    print(f"accettata {argomenti.phase}: {esito['atto']} (attempt {esito['numero']}), "
          f"firmato da {esito['firmatario']}, registro aggiornato")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
