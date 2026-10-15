#!/usr/bin/env python3
"""Attivare una fase: riservarla nel registro e lascia l'ordine che un esecutore raccoglie.

Perche' esiste: il coordinatore sapeva MOSTRARE il lavoro e non farlo partire. Su un progetto in
cui non ci sono domande, decisioni o prompt da lanciare, la pagina restava muta: nessun campo,
nessun pulsante, nessun modo di cominciare — misurato il 2026-10-15 sul progetto di origine, con
dieci unita' aperte e niente da premere.

Attivare fa DUE cose, e non finge la terza:

1. deposita un ORDINE DUREVOLE in `<workspace>/dispatch-queue/` con il testo da incollare, il
   perimetro, i criteri di accettazione e le impronte dei file che la fase deve misurare;
2. riserva la fase nel registro con `status: pre_registered` — lo stato che il registro usa per
   «voce pronta, nessun titolare» — cosi' una seconda attivazione della stessa fase viene
   rifiutata invece di produrre due esecutori.

Quello che NON fa: non avvia nessun agente. Un ordine e' una promessa in attesa di un esecutore, e
la pagina lo dice con quelle parole. Chi prende la fase la porta a `taken` col proprio nome, ed e'
lui che risponde di quei byte.

La riserva si puo' togliere: `release` riscrive la presa come rilasciata, e l'ordine resta sul disco
come prova di cosa era stato chiesto.

Uso::

    python3 registers/activate.py --workspace <progetto> --list
    python3 registers/activate.py --workspace <progetto> --target A11Y03T
    python3 registers/activate.py --workspace <progetto> --release A11Y03T
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import apply_transitions  # noqa: E402 - la scrittura sui registri passa sempre da li'
import next_prompts  # noqa: E402 - il quaderno, per il testo del prompt
from workspace import Workspace  # noqa: E402

LIVE = ("active", "taken", "pre_registered", "ready", "active_extension")
STALLED = ("needs_changes", "failed")


def _rilasciata(voce):
    return bool(str(voce.get("released_at") or "").strip())


def prese(state):
    """Le prese VIVE per fase. Il registro ripete le voci e l'ordine non e' cronologico: si
    guardano tutte, e una voce viva con `released_at` vuoto vale come presa."""
    out = {}
    for voce in state.get("active_claims") or []:
        fase = voce.get("task_id")
        if not fase or voce.get("status") not in LIVE or _rilasciata(voce):
            continue
        out[str(fase)] = voce
    return out


def fasi(tasks_doc):
    """(id, unit_id, kind, title) nell'ordine del file."""
    return [
        (str(t.get("id")), str(t.get("unit_id") or ""), str(t.get("kind") or ""), str(t.get("title") or ""))
        for t in tasks_doc.get("tasks") or []
        if t.get("id")
    ]


def ordini_aperti(ws):
    """Gli ordini depositati e non ancora chiusi, per fase.

    Riconosce i due schemi che convivono nella coda (`project-console-work-order/1.0` e
    `binche.ux-dispatch-order/1.0`, il rilancio di una fase respinta): chi legge un ordine non deve
    sapere da quale porta e' entrato.

    Serve a una cosa sola: NON depositarne un secondo. La pagina poteva chiedere un rilancio per una
    fase che aveva gia' il suo ordine, e l'unica risposta era «Non depositato» — un vicolo cieco,
    segnalato dall'utente.
    """
    fuori = {}
    coda = ws.path("dispatch-queue")
    if not coda.is_dir():
        return fuori
    for percorso in sorted(coda.glob("*.yaml")):
        try:
            documento = yaml.safe_load(percorso.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(documento, dict):
            continue
        fase = documento.get("code") or documento.get("task_id")
        if not fase:
            continue
        if documento.get("fulfilled_status") or documento.get("superseded_by") or documento.get("done_at"):
            continue
        fuori.setdefault(str(fase), []).append(str(percorso.relative_to(ws.root)))
    return fuori


def attivabili(ws, state=None, tasks_doc=None):
    """Cosa si puo' far partire adesso, e perche' — misurato, non indovinato.

    Regola: una fase senza presa viva, la cui unita' non aspetta altre unita' aperte. Le fasi
    respinte in verifica restano attivabili (sono lavoro da rifare) e lo dichiarano.
    """
    state = state if state is not None else (yaml.safe_load(ws.state_path.read_text(encoding="utf-8")) or {})
    tasks_doc = tasks_doc if tasks_doc is not None else (yaml.safe_load(ws.path(ws.tasks).read_text(encoding="utf-8")) or {})
    registrate = state.get("tasks") or {}
    vive = prese(state)
    ordini = ordini_aperti(ws)
    unita = {str(u.get("id")): u for u in tasks_doc.get("units") or [] if u.get("id")}
    accettate = {
        uid
        for uid, u in unita.items()
        if (u.get("tasks") or [])
    }
    # Unita' chiuse: tutte le loro fasi accettate (stessa regola della vista).
    per_unita = {}
    for fase, unit_id, *_ in fasi(tasks_doc):
        per_unita.setdefault(unit_id, []).append(fase)
    chiuse = {
        unit_id
        for unit_id, elenco in per_unita.items()
        if elenco and all((registrate.get(f) or {}).get("status") == "accepted" for f in elenco)
    }
    fuori = []
    for fase, unit_id, kind, titolo in fasi(tasks_doc):
        stato = (registrate.get(fase) or {}).get("status", "pending")
        if stato == "accepted" or fase in vive:
            continue
        unita_dati = unita.get(unit_id) or {}
        attese = [d for d in (unita_dati.get("depends_on_units") or []) if str(d) not in chiuse]
        fuori.append(
            {
                "phase": fase,
                "unit": unit_id,
                "block": str(unita_dati.get("domain") or "senza-dominio"),
                "kind": kind,
                "title": titolo or str(unita_dati.get("title") or ""),
                "status": stato,
                "rework": stato in STALLED,
                "waiting_on": attese,
                # Se un ordine c'e' gia', la pagina lo mostra invece di offrire un pulsante che
                # verrebbe rifiutato.
                "orders": ordini.get(fase, []),
                # Il file di consegna e' il PROSSIMO tentativo, non sempre il primo: un rifacimento
                # che chiedesse `attempt-1` chiederebbe di riscrivere un artefatto consegnato.
                "deliverable": f"{ws.deliverable_prefix}{fase}/attempt-{prossimo_tentativo(state, fase)}.yaml",
            }
        )
    fuori.sort(key=lambda voce: (bool(voce["waiting_on"]), voce["rework"] is False, voce["phase"]))
    return fuori


def radici(ws):
    """Dove si risolvono i path dichiarati: la cartella dei registri, e il repository che la
    contiene se c'e'. In un progetto vero i path di prodotto sono relativi al repository
    (`tenders/tests/...`), i file del coordinamento alla cartella dei registri (`reports/...`):
    senza entrambe le basi, meta' delle impronte non si trova (misurato il 2026-10-15)."""
    fuori = [("workspace", ws.root)]
    import subprocess

    try:
        esito = subprocess.run(
            ["git", "-C", str(ws.root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return fuori
    radice = (esito.stdout or "").strip()
    if esito.returncode == 0 and radice and Path(radice).resolve() != ws.root:
        fuori.append(("repository", Path(radice).resolve()))
    return fuori


def _sha256(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def impronte(ws, state, fase):
    """I file di prodotto che questa fase deve misurare, con la loro impronta ADESSO.

    L'ordine congela la revisione che si aspetta: se i byte cambiano prima che qualcuno prenda la
    fase, chi la prende lo vede invece di misurarne una diversa.

    Si guardano prima i path dichiarati dalla fase stessa. Se sono solo consegne (i report che la
    fase produce), si guardano quelli delle ALTRE fasi dell'unita': per una fase di verifica il
    prodotto da misurare lo dichiara chi l'ha eseguita, non lei. La fonte finisce nell'ordine,
    cosi' chi lo legge sa da dove viene la revisione congelata.
    """
    def percorsi_di(elenco):
        fuori = []
        for voce in state.get("active_claims") or []:
            if str(voce.get("task_id")) not in elenco:
                continue
            for raw in voce.get("exact_paths") or []:
                valore = str(raw).strip().strip("`").split(" (")[0].strip()
                if valore.startswith("docs/ux-context-pack/"):
                    valore = valore[len("docs/ux-context-pack/") :]
                if not valore or valore.startswith(ws.reports) or valore in fuori:
                    continue
                fuori.append(valore)
        return fuori

    unita = fase.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") or fase
    sorelle = [
        str(t.get("id"))
        for t in (yaml.safe_load(ws.path(ws.tasks).read_text(encoding="utf-8")) or {}).get("tasks") or []
        if str(t.get("unit_id") or "") == unita
    ]
    percorsi = percorsi_di({fase})
    fonte = "path dichiarati da questa fase"
    if not percorsi and sorelle:
        percorsi = percorsi_di(set(sorelle))
        fonte = f"path dichiarati dalle fasi dell'unita' {unita}"
    fuori = []
    for relativo in percorsi[:20]:
        for base, radice in radici(ws):
            target = (radice / relativo).resolve()
            if not str(target).startswith(str(radice)) or not target.is_file():
                continue
            fuori.append({"path": relativo, "base": base, "sha256": _sha256(target)})
            break
    return fuori, fonte


def _order_path(ws, fase):
    quando = datetime.now().strftime("%Y%m%dT%H%M%S")
    return ws.path("dispatch-queue") / f"{quando}-{fase}-attivazione.yaml"


def costruisci_ordine(ws, voce, state, prompt=None):
    """Il file che un esecutore trova: cosa fare, con quale testo, su quale revisione, con quale
    criterio di accettazione."""
    revisione, fonte_revisione = impronte(ws, state, voce["phase"])
    return {
        "schema": "project-console-work-order/1.0",
        "code": voce["phase"],
        "action": "rework" if voce["rework"] else "execute",
        "unit": voce["unit"],
        "block": voce["block"],
        "kind": voce["kind"],
        "title": voce["title"],
        "status_at_activation": voce["status"],
        "deliverable": voce["deliverable"],
        "prompt_source": prompt.get("source") if prompt else ws.queue,
        "prompt": (prompt or {}).get("text"),
        "registry": {
            "file": ws.state,
            "anchor": f"- task_id: {voce['phase']}",
            "expected_status": "pre_registered",
        },
        "revision": revisione,
        "revision_source": fonte_revisione if revisione else "nessun file di prodotto dichiarato",
        "activated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "activated_by": "pagina di attivazione",
        "notes": (
            "Attivazione depositata dal coordinatore. Nessun agente e' stato avviato: chi prende "
            "questa fase la porta a `taken` col proprio nome e deposita il rilascio alla fine. "
            "L'ordine resta sul disco come prova di cosa era stato chiesto."
        ),
    }


def prompt_per(ws, fase):
    """Il testo del prompt che riguarda quella fase, se il quaderno ne ha uno."""
    for voce in next_prompts.build(ws.root):
        if voce.get("anchor") == fase:
            return {
                "source": f"{ws.queue}#{voce['number']}",
                "text": voce.get("prompt"),
                "number": voce["number"],
            }
    return None


def _ultima_ancora(state):
    """(ancora, occorrenza) dell'ULTIMA voce di claim, per appenderne una nuova dopo di lei.

    L'occorrenza serve: il registro ripete gli id, e senza dirla l'applicatore rifiuta l'ancora
    ambigua — giustamente, perche' non deve scegliere lui quale voce intendevi.
    """
    voci = [str(v.get("task_id")) for v in state.get("active_claims") or [] if v.get("task_id")]
    if not voci:
        raise apply_transitions.TransitionError("nessuna voce di claim nel registro")
    ultima = voci[-1]
    return f"- task_id: {ultima}", sum(1 for v in voci if v == ultima)


def prossimo_tentativo(state, fase):
    """Il numero del tentativo che questa attivazione apre: mai uno gia' presente."""
    numeri = [
        int(v.get("attempt") or 0)
        for v in state.get("active_claims") or []
        if str(v.get("task_id")) == fase and str(v.get("attempt") or "").isdigit()
    ]
    return (max(numeri) if numeri else 0) + 1


def _occorrenze(state, fase):
    return sum(1 for v in state.get("active_claims") or [] if str(v.get("task_id")) == fase)


def _applica(ws, richieste):
    applicate, fallite = [], []
    import fcntl

    lock = Path(
        os.environ.get("CONSOLE_REGISTRY_LOCK")
        or f"/tmp/project-console-{hashlib.sha1(str(ws.root).encode()).hexdigest()[:12]}.lock"
    )
    with open(lock, "a+") as maniglia:
        fcntl.flock(maniglia, fcntl.LOCK_EX)
        for indice, richiesta in enumerate(richieste):
            try:
                apply_transitions.apply_request(
                    richiesta, pack=ws.root, validate_after=indice == len(richieste) - 1
                )
                applicate.append(f"{richiesta['file']}#{richiesta.get('field') or richiesta.get('item', {}).get('status', 'voce')}")
            except apply_transitions.TransitionError as errore:
                fallite.append(str(errore))
        fcntl.flock(maniglia, fcntl.LOCK_UN)
    if fallite:
        raise apply_transitions.TransitionError("; ".join(fallite))
    return applicate


def attiva(ws, fase, dry_run=False):
    """Riserva la fase e deposita l'ordine. Rifiuta se qualcuno l'ha gia' presa."""
    state = yaml.safe_load(ws.state_path.read_text(encoding="utf-8")) or {}
    tasks_doc = yaml.safe_load(ws.path(ws.tasks).read_text(encoding="utf-8")) or {}
    voce = next((v for v in attivabili(ws, state, tasks_doc) if v["phase"] == fase), None)
    if voce is None:
        presa = prese(state).get(fase)
        if presa:
            raise apply_transitions.TransitionError(
                f"{fase} ha gia' una presa viva ({presa.get('owner_agent') or presa.get('taken_by') or presa.get('status')}): "
                "attivarla di nuovo farebbe due esecutori sugli stessi byte"
            )
        raise apply_transitions.TransitionError(f"fase non attivabile o inesistente: {fase}")
    ordine = costruisci_ordine(ws, voce, state, prompt_per(ws, fase))
    # Un ordine per fase: se ce n'e' gia' uno aperto si usa QUELLO, non se ne scrive un secondo.
    esistenti = voce.get("orders") or []
    percorso = (ws.root / esistenti[-1]) if esistenti else _order_path(ws, fase)
    if dry_run:
        return {"order": str(percorso), "order_body": ordine, "applied": []}
    if not esistenti:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(
            yaml.safe_dump(ordine, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    ancora, occorrenza = _ultima_ancora(state)
    richiesta = {
        "schema": apply_transitions.SCHEMA,
        "file": ws.state,
        "anchor": ancora,
        "occurrence": occorrenza,
        "item": {
            "task_id": fase,
            "unit": voce["unit"],
            "phase": (fase[len(voce["unit"]) :] or "?"),
            "status": "pre_registered",
            "attempt": prossimo_tentativo(state, fase),
            "registered_at": ordine["activated_at"],
            "registered_by": "pagina di attivazione",
            "order": str(percorso.relative_to(ws.root)),
            "owner": "NESSUN TITOLARE: attivazione in attesa di un esecutore",
        },
        "position": "after",
    }
    try:
        applicate = _applica(ws, [richiesta])
    except Exception:
        # Un ordine senza riserva e' un ordine che qualcun altro puo' raccogliere mentre la fase
        # resta libera: si toglie invece di lasciarlo sul disco (misurato al primo giro, quando un
        # ancora ambigua ha lasciato un ordine orfano). Se l'ordine c'era GIA' — un rilancio
        # depositato prima — non si tocca: non e' mio.
        if not esistenti:
            percorso.unlink(missing_ok=True)
        raise
    return {
        "order": str(percorso.relative_to(ws.root)),
        "applied": applicate,
        "prompt": ordine.get("prompt"),
        "action": ordine["action"],
    }


def rilascia(ws, fase):
    """Toglie la riserva: l'ordine resta come prova, la fase torna disponibile."""
    state = yaml.safe_load(ws.state_path.read_text(encoding="utf-8")) or {}
    # `occurrence` conta le voci CON QUELL'ANCORA, non la posizione nella lista: chiedere la 245ª
    # corrispondenza di un'ancora che ne ha 6 e' l'errore che il registro mi ha rimandato indietro.
    indice = None
    quante = 0
    for voce in state.get("active_claims") or []:
        if str(voce.get("task_id")) != fase:
            continue
        quante += 1
        if voce.get("status") in LIVE and not _rilasciata(voce):
            indice = quante
    if indice is None:
        raise apply_transitions.TransitionError(f"{fase} non ha una presa viva da rilasciare")
    adesso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    richieste = [
        {
            "schema": apply_transitions.SCHEMA,
            "file": ws.state,
            "anchor": f"- task_id: {fase}",
            "occurrence": indice,
            "field": campo,
            "text": valore,
        }
        for campo, valore in (
            ("status", "released"),
            ("released_at", adesso),
            (
                "release_note",
                "Rilasciata dalla pagina di attivazione: la riserva e' tolta e la fase torna "
                "disponibile. L'ordine depositato resta su disco come prova.",
            ),
        )
    ]
    return {"applied": _applica(ws, richieste)}


def elenco(ws):
    for voce in attivabili(ws):
        stato = "da rifare" if voce["rework"] else voce["status"]
        attesa = f" · attende {', '.join(voce['waiting_on'])}" if voce["waiting_on"] else ""
        print(f"{voce['phase']:<14} {voce['block']:<14} {stato:<12} {voce['title'][:44]}{attesa}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    parser.add_argument("--list", action="store_true", help="cosa si puo' attivare adesso")
    parser.add_argument("--target", help="la fase da attivare")
    parser.add_argument("--release", help="la fase da rilasciare")
    parser.add_argument("--dry-run", action="store_true", help="mostra l'ordine senza scrivere")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    next_prompts.configure(queue=ws.queue, deliverable_prefix=ws.deliverable_prefix)
    if args.release:
        print(rilascia(ws, args.release))
        return 0
    if args.target:
        esito = attiva(ws, args.target, dry_run=args.dry_run)
        print(f"ordine: {esito['order']}")
        print(f"scritto nel registro: {', '.join(esito['applied']) or 'niente (dry-run)'}")
        if esito.get("prompt"):
            print("prompt pronto: si', dal quaderno")
        return 0
    elenco(ws)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
