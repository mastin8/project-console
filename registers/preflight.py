#!/usr/bin/env python3
"""Il cancello prima di un atto di accettazione: la base e' ancora quella giusta?

Perche' esiste. Un atto di accettazione (la fase `R`) deve GIUDICARE, non rimisurare: legge i criteri,
legge i byte, decide, dichiara i limiti. Ma perche' sia corto, l'apparato va controllato **prima** da
una macchina — altrimenti chi giudica spende il turno a scoprire che il puntatore e' indietro, che la
revisione si e' mossa, che c'e' un'altra corsia sugli stessi byte.

Misurato sul progetto di origine il 2026-10-16: `UPL04ZR` ha dieci atti di ratifica respinti, tutti
per apparato (`UPL04Z-T-ON-CURRENT-REVISION` in 10 su 10, `UPL04Z-DISTINCT-SIGNATURE` in 6) e **zero
informazioni di prodotto**. Non era pigrizia degli agenti: nessuno aveva detto loro, prima di
cominciare, che la base su cui giudicavano non esisteva piu'.

Questo comando risponde a una domanda sola: **si puo' giudicare adesso?** E lo dice con le misure:

* i registri si leggono;
* la coda delle transizioni non ha richieste non applicate su questa fase o sulla sua unita'
  (altrimenti si giudica una base vecchia: il registro non ha ancora imparato cosa e' successo);
* il puntatore del report esiste, nomina un file che c'e', ed e' il tentativo piu' recente;
* nessun'altra corsia sta scrivendo su questa unita' (prese vive);
* le impronte che il report dichiara sono ancora quelle dei byte vivi — se il report ne dichiara.

Esito: `PRONTA` oppure `NON ANCORA`, coi motivi. Non scrive niente.

Uso::

    python3 registers/preflight.py --workspace <progetto> --phase A11Y03R
    python3 registers/preflight.py --workspace <progetto> --phase A11Y03R --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import coda  # noqa: E402 - la coda delle transizioni: se e' piena, la base puo' essere vecchia
import report_contract  # noqa: E402 - usage e provenienza Git obbligatori nei progetti nuovi
import validate_registries  # noqa: E402 - i registri si leggono?
from workspace import Workspace  # noqa: E402

#: Le chiavi con cui i report dichiarano le impronte di cio' che hanno giudicato. I nomi sono quelli
#: che i progetti usano davvero; se un progetto non ne dichiara nessuna, il controllo non si applica.
CHIAVI_IMPRONTE = (
    "fingerprints",
    "fingerprint",
    "revision",
    "frozen_revision",
    "inputs",
    "impronte",
)


def _leggi(percorso: Path):
    try:
        return yaml.load(
            percorso.read_text(encoding="utf-8", errors="replace"),
            Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
        ) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _sha256(percorso: Path):
    try:
        return hashlib.sha256(percorso.read_bytes()).hexdigest()
    except OSError:
        return None


def _radici(ws):
    """Dove si risolvono i path dichiarati: il workspace, e il repository che lo contiene."""
    return [ws.root, *[r for _, r in _radici_repo(ws)]]


def _radici_repo(ws):
    import subprocess

    try:
        esito = subprocess.run(
            ["git", "-C", str(ws.root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    radice = (esito.stdout or "").strip()
    if esito.returncode == 0 and radice and Path(radice).resolve() != ws.root:
        return [("repository", Path(radice).resolve())]
    return []


def _impronte_dichiarate(documento):
    """(percorso, impronta) dichiarate da un report, in qualunque forma le abbia scritte."""
    fuori = []
    for chiave in CHIAVI_IMPRONTE:
        valore = documento.get(chiave)
        if isinstance(valore, dict):
            for percorso, impronta in valore.items():
                if isinstance(impronta, dict):
                    impronta = impronta.get("sha256") or impronta.get("hash") or impronta.get("impronta")
                if isinstance(impronta, str) and impronta.strip():
                    fuori.append((str(percorso), impronta.strip().split("…")[0].lower()))
        elif isinstance(valore, list):
            for voce in valore:
                if isinstance(voce, dict) and (voce.get("path") or voce.get("file")):
                    impronta = voce.get("sha256") or voce.get("hash") or voce.get("impronta") or ""
                    fuori.append((str(voce.get("path") or voce.get("file")), str(impronta).split("…")[0].lower()))
    return fuori


def _impronte_consegnate(documento):
    """Le impronte dei file che l'atto HA SCRITTO (l'impronta di DOPO, se la dichiara).

    Un atto che consegna un file lo dichiara fra gli `inputs` con l'impronta di PRIMA e fra i
    `delivered`/`files` con quella di DOPO. Confrontare solo la prima fa sembrare mosso un file che
    l'atto ha cambiato di proposito: misurato il 2026-10-17 su `QA05E`, che aggiorna
    `docs/qa-associations.md` (prima `764d72…`, dopo `a808e8…`) e risultava «revisione cambiata».
    """
    fuori = {}
    for chiave in ("delivered", "files"):
        for voce in documento.get(chiave) or []:
            if not isinstance(voce, dict):
                continue
            percorso = voce.get("path") or voce.get("file")
            impronta = (
                voce.get("sha256_after")
                or voce.get("sha256")
                or voce.get("hash")
                or voce.get("impronta")
            )
            if percorso and isinstance(impronta, str) and impronta.strip():
                fuori[str(percorso)] = impronta.strip().split("…")[0].lower()
    return fuori


def _e_registro(ws, radice, percorso):
    """Il file dichiarato e' un REGISTRO del workspace, non un byte di prodotto?

    Un report puo' dichiarare l'impronta di `state.yaml` per dire cosa ha letto. Quell'impronta
    cambia per costruzione: ogni presa, rilascio o atto di un'altra corsia riscrive il registro.
    Trattarla come «la revisione giudicata e' cambiata» rende l'accettazione impossibile per sempre:
    misurato il 2026-10-17 su `QA05A`, il cui report dichiara `state.yaml` con la nota esplicita
    «e' un registro condiviso e si muove anche per le altre corsie». Il cancello deve fermare i byte
    di prodotto che si muovono, non il quaderno che li annota.
    """
    try:
        target = (radice / percorso).resolve()
        target.relative_to(ws.root.resolve())
    except (OSError, ValueError):
        return False
    nomi = (ws.state, ws.tasks, ws.questions, ws.decisions, ws.user_decisions, ws.queue, ws.view)
    for nome in nomi:
        try:
            if target == ws.path(str(nome)).resolve():
                return True
        except OSError:
            continue
    for nome in (ws.reports, ws.transitions, ws.inbox):
        try:
            target.relative_to(ws.path(str(nome)).resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def leggi(ws, fase, state=None, tasks_doc=None):
    """(esito, motivi, avvisi, misure) per l'atto di accettazione di quella fase."""
    state = state if state is not None else _leggi(ws.state_path)
    tasks_doc = tasks_doc if tasks_doc is not None else _leggi(ws.path(ws.tasks))
    task = next((t for t in tasks_doc.get("tasks") or [] if str(t.get("id")) == str(fase)), None)
    unita = str((task or {}).get("unit_id") or "")
    registrata = (state.get("tasks") or {}).get(str(fase)) or {}
    motivi, avvisi, misure = [], [], {}

    # 0. La fase esiste? Senza questo, un nome sbagliato (o il workspace sbagliato) rispondeva
    #    «PRONTA» — che e' il modo peggiore di sbagliare: un via libera su niente.
    if task is None:
        motivi.append(f"la fase {fase} non e' dichiarata in {ws.tasks}: niente da giudicare")

    # 1. I registri si leggono.
    rotti = []
    for nome in validate_registries.REGISTRIES:
        percorso = ws.path(nome)
        if percorso.exists() and validate_registries.duplicate_keys(str(percorso)):
            rotti.append(nome)
    if rotti:
        motivi.append(f"registri con chiavi duplicate: {', '.join(rotti)}")

    # 2. La coda. Si distingue, e la distinzione e' il punto: una richiesta NON applicata su QUESTA
    #    fase invalida la base (il registro non ha ancora imparato cosa e' successo a lei); una
    #    richiesta altrove nell'unita' e' un avviso, non uno stop. Senza questa distinzione il cancello
    #    diventerebbe un freno generale — la coda e' quasi sempre piena — e non farebbe giudicare piu'
    #    niente, che e' la malattia curata con un altro nome.
    richieste = coda.richieste(ws)
    # SEGNALATE ≠ BLOCCANTI. Una richiesta che il tool stesso non applichera' (una presa fantasma, un
    # numero che tornerebbe indietro) non puo' bloccare per sempre la firma: altrimenti la fase resta
    # non accettabile all'infinito, e il cancello diventa una gabbia — misurato il 2026-10-16 su
    # `UPL04ZR` (3 richieste segnalate, 0 applicabili, firma rifiutata).
    segnalate = {voce["file"] for voce in coda.leggi(ws)["sospette"]}
    sulla_fase = [voce for voce in richieste if voce["fase"] == str(fase)]
    bloccanti = [voce for voce in sulla_fase if voce["file"] not in segnalate]
    sulla_unita = [
        voce for voce in richieste
        if unita
        and str(voce["fase"]).startswith(unita)
        and voce["fase"] != str(fase)
        and voce["file"] not in segnalate
    ]
    misure["coda_sulla_fase"] = len(sulla_fase)
    misure["coda_sulla_unita"] = len(sulla_unita)
    if bloccanti:
        motivi.append(
            f"la coda ha {len(bloccanti)} richieste applicabili SU QUESTA FASE: il registro non ha "
            "ancora imparato cosa e' successo a lei, e si giudicherebbe una base vecchia"
        )
    elif sulla_fase:
        avvisi.append(
            f"{len(sulla_fase)} richieste su questa fase sono SEGNALATE e non si applicano da sole "
            "(guardale nell'elenco della coda): se toccano i byte che giudichi, la base e' vecchia"
        )
    if sulla_unita:
        avvisi.append(
            f"{len(sulla_unita)} richieste non applicate altrove nell'unita' {unita}: se riguardano i "
            "byte che stai giudicando, la base e' vecchia — guarda cosa dicono prima di decidere"
        )

    # 3. Il puntatore del report, e il tentativo piu' recente su disco.
    puntatore = ws.reports_dir / f"{fase}.yaml"
    documento_puntatore = _leggi(puntatore) if puntatore.exists() else {}
    riferimento = documento_puntatore.get("report") or documento_puntatore.get("report_ref")
    cartella = ws.reports_dir / str(fase)
    tentativi = sorted(
        (int(trovato.group(1)) for p in cartella.glob("attempt-*.yaml") if (trovato := __import__("re").match(r"attempt-(\d+)\.yaml$", p.name)))
    ) if cartella.is_dir() else []
    misure["tentativi"] = tentativi[-1] if tentativi else 0
    # L'attempt che il puntatore NOMINA: i progetti lo scrivono in modi diversi — `attempt`,
    # `current_attempt`, o solo nel percorso del report (`attempt-2.yaml`). Leggere un campo solo
    # produceva un falso allarme («il puntatore dice attempt ? mentre su disco c'è l'attempt 2») su un
    # puntatore che era giusto. Misurato il 2026-10-17 su `REG03R`.
    dichiarato = documento_puntatore.get("attempt") or documento_puntatore.get("current_attempt")
    if not dichiarato and riferimento:
        trovato = __import__("re").search(r"attempt-(\d+)\.ya?ml$", str(riferimento))
        dichiarato = trovato.group(1) if trovato else None
    misure["puntatore"] = str(dichiarato or "")
    if not riferimento:
        avvisi.append("il puntatore del report non dichiara quale tentativo e' quello corrente")
    elif not (ws.root / str(riferimento)).is_file():
        motivi.append(f"il puntatore nomina un report che non esiste: {riferimento}")
    if tentativi and str(dichiarato or "") != str(tentativi[-1]):
        motivi.append(
            f"il puntatore nomina l'attempt {dichiarato or '?'} mentre su disco "
            f"c'e' l'attempt {tentativi[-1]}: si giudicherebbe l'atto superato"
        )

    # 4. Prese vive nell'unita': se qualcuno sta scrivendo quegli stessi byte, non e' il momento.
    vive = [
        voce for voce in state.get("active_claims") or []
        if voce.get("status") in ("active", "taken", "pre_registered", "ready", "active_extension")
        and not str(voce.get("released_at") or "").strip()
        and (unita and str(voce.get("task_id") or "").startswith(unita))
    ]
    misure["prese_vive_unita"] = [str(voce.get("task_id")) for voce in vive]
    if len(vive) > 1:
        avvisi.append(
            "prese vive nell'unita': " + ", ".join(sorted(misure["prese_vive_unita"]))
            + ". Se scrivono gli stessi path, il giudizio nasce vecchio"
        )

    # 5. Le impronte dichiarate dal report che si deve giudicare, contro i byte vivi.
    da_giudicare = (ws.root / str(riferimento)) if riferimento and (ws.root / str(riferimento)).is_file() else (
        cartella / f"attempt-{tentativi[-1]}.yaml" if tentativi else None
    )
    giudicato = _leggi(da_giudicare) if da_giudicare else {}
    violazioni_contratto = report_contract.validate(ws, giudicato) if giudicato else []
    if violazioni_contratto:
        motivi.append(
            "il report non rispetta il contratto obbligatorio: "
            + "; ".join(violazioni_contratto)
        )
    dichiarate = _impronte_dichiarate(giudicato)
    consegnate = _impronte_consegnate(giudicato)
    cambiate = []
    saltate = 0
    for percorso, dichiarata in dichiarate:
        # Se l'atto ha CONSEGNATO quel file, l'impronta da pretendere e' quella di dopo.
        attesa = consegnate.get(percorso, dichiarata)
        for radice in _radici(ws):
            vivo = _sha256(radice / percorso)
            if vivo:
                if _e_registro(ws, radice, percorso):
                    # Il registro e' cambiato per costruzione: si dichiara, non si blocca.
                    saltate += 1
                    break
                if not vivo.startswith(attesa[:16]):
                    cambiate.append(f"{percorso} (dichiarato {attesa[:12]}…, adesso {vivo[:12]}…)")
                break
    misure["impronte_controllate"] = len(dichiarate)
    misure["impronte_del_registro"] = saltate
    misure["impronte_consegnate"] = len(consegnate)
    misure["impronte_cambiate"] = len(cambiate)
    if cambiate:
        motivi.append("la revisione giudicata e' cambiata: " + "; ".join(cambiate[:4]))

    return {
        "esito": "PRONTA" if not motivi else "NON ANCORA",
        "phase": str(fase),
        "unit": unita,
        "status": registrata.get("status"),
        "attempt": registrata.get("attempt"),
        "motivi": motivi,
        "avvisi": avvisi,
        "misure": misure,
    }


def main(argv=None):
    analizzatore = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizzatore.add_argument("--workspace", required=True)
    analizzatore.add_argument("--phase", required=True, help="la fase che si vuole giudicare")
    analizzatore.add_argument("--json", action="store_true")
    argomenti = analizzatore.parse_args(argv)
    ws = Workspace.load(argomenti.workspace)
    esito = leggi(ws, argomenti.phase)
    if argomenti.json:
        print(json.dumps(esito, ensure_ascii=False, default=str, indent=1))
        return 0
    print(f"{esito['esito']} — {esito['phase']} (unita' {esito['unit']}, "
          f"stato {esito['status']}, attempt {esito['attempt']})")
    for motivo in esito["motivi"]:
        print(f"  STOP  {motivo}")
    for avviso in esito["avvisi"]:
        print(f"  nota  {avviso}")
    if esito["esito"] == "PRONTA":
        print("  si puo' giudicare: leggi i criteri, leggi i byte, decidi. Non rimisurare cio' che")
        print("  il tester ha gia' misurato; dichiara cio' che non hai ripercorso.")
    return 0 if esito["esito"] == "PRONTA" else 1


if __name__ == "__main__":
    raise SystemExit(main())
