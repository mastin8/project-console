#!/usr/bin/env python3
"""La coda delle transizioni: il registro che non sa ancora cosa e' successo.

Perche' esiste. Gli agenti non scrivono i registri: depositano in `pending-transitions/` una
RICHIESTA per ogni modifica («su questa voce, cambia questo campo con questo testo»), e un programma
la applica — edit testuale calcolato, lock, validazione, backup. Se nessuno le applica, il registro
racconta il passato, e con lui tutto quello che ci legge sopra: questa pagina, i mandati, le
ratifiche.

Misurato il 2026-10-16: **129 richieste in coda, 93 depositate da piu' di dodici ore, 12 rilasci**,
mentre quattro fasi consegnavano in dieci minuti. `NAV03E` ha consegnato alle 10:53 e il registro la
leggeva ancora `needs_changes` attempt 3: chi apriva la pagina vedeva un ritardo che non era del
lavoro, era del registro. Una cosa cosi' non puo' stare fuori dalla pagina: non si manda avanti
quello che non si vede.

Questo modulo legge la coda e dice tre cose: quante sono e da quanto aspettano, quali NON vanno
applicate (con il motivo misurato), e quali fasi hanno il registro indietro rispetto ai file.

Uso::

    python3 registers/coda.py --workspace <progetto>
    python3 registers/coda.py --workspace <progetto> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workspace import Workspace  # noqa: E402

#: Oltre questa attesa, una richiesta non e' «in coda»: e' ferma.
SOGLIA_ORE = 12


def _carica(testo):
    return yaml.load(testo, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def _leggi(percorso: Path):
    try:
        return _carica(percorso.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _momento(valore):
    """Una data dichiarata. Senza fuso vale come ora locale, come in tutto il resto del tool."""
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.astimezone()
    testo = str(valore or "").strip().strip("'\"")
    for candidato in (testo, testo.replace(" ", "T", 1)):
        if not candidato:
            continue
        try:
            momento = datetime.fromisoformat(candidato.replace("Z", "+00:00"))
        except ValueError:
            continue
        return momento if momento.tzinfo else momento.astimezone()
    return None


def _richieste(ws):
    """Le richieste depositate e non ancora applicate, in ordine di arrivo (nome del file)."""
    fuori = []
    coda = ws.transitions_dir
    if not coda.is_dir():
        return fuori
    for percorso in sorted(coda.glob("*.yaml")):
        documento = _leggi(percorso)
        if not isinstance(documento, dict):
            continue
        voce = documento.get("item") if isinstance(documento.get("item"), dict) else {}
        ancora = str(documento.get("anchor") or "")
        fase = ""
        trovato = re.search(r"task_id:\s*([A-Za-z0-9_\-]+)", ancora) or re.search(
            r"id:\s*([A-Za-z0-9_\-]+)", ancora
        )
        if trovato:
            fase = trovato.group(1)
        else:
            # Ci sono anche ancore sulla sola chiave della voce (`anchor: "  UPL04ZE:"`): la fase e'
            # li', senza il nome del campo. Senza questo ripiego 34 richieste risultavano «senza
            # fase», come se non riguardassero niente.
            ripiego = re.match(r"[\s\"'\-]*([A-Za-z][A-Za-z0-9_\-]*)\s*:", ancora)
            if ripiego:
                fase = ripiego.group(1)
        fuori.append(
            {
                "file": percorso.name,
                "percorso": str(percorso.relative_to(ws.root)),
                "by": str(documento.get("requested_by") or ""),
                "at": _momento(documento.get("requested_at")),
                "destinazione": str(documento.get("file") or ""),
                "anchor": ancora,
                "occurrence": documento.get("occurrence"),
                "field": str(documento.get("field") or ""),
                "text": str(documento.get("text") or ""),
                "item": voce,
                "fase": str(voce.get("task_id") or fase),
            }
        )
    return fuori


def _attempt_su_disco(ws, fase):
    """Il numero di tentativo piu' alto che esiste su disco per quella fase."""
    cartella = ws.reports_dir / str(fase)
    if not cartella.is_dir():
        return 0
    numeri = [int(trovato.group(1)) for p in cartella.glob("attempt-*.yaml") if (trovato := re.match(r"attempt-(\d+)", p.name))]
    return max(numeri) if numeri else 0


def _registro_indietro(ws, state, limite: int = 8):
    """Le fasi in cui il registro e' piu' vecchio dei file: dice a cosa serve applicare la coda."""
    registrate = state.get("tasks") or {}
    fuori = []
    if not ws.reports_dir.is_dir():
        return fuori
    fasi = {p.parent.name for p in ws.reports_dir.glob("*/attempt-*.yaml")}
    for fase in sorted(fasi):
        # Solo le fasi che il registro CONOSCE: una cartella di report per qualcosa che nel registro
        # non esiste (una ratifica, una misura a se') non e' «registro indietro», e' un'altra cosa.
        # Senza questo filtro l'elenco si riempiva di voci «registro assente» che non dicono niente.
        registrata = registrate.get(fase)
        if not registrata:
            continue
        ultimo = _attempt_su_disco(ws, fase)
        dichiarato = int(registrata.get("attempt") or 0)
        if ultimo > dichiarato:
            fuori.append(
                {
                    "phase": fase,
                    "registro": f"{registrata.get('status') or 'assente'} · attempt {dichiarato}",
                    "disco": f"attempt {ultimo}",
                    "ritardo": ultimo - dichiarato,
                }
            )
    fuori.sort(key=lambda voce: -voce["ritardo"])
    return fuori[:limite]


def leggi(ws, adesso=None, limite_sospette: int = 12):
    """Cosa c'e' in coda, cosa non va applicato, e dove il registro e' indietro."""
    adesso = adesso or datetime.now().astimezone()
    richieste = _richieste(ws)
    state = _leggi(ws.state_path)
    registrate = state.get("tasks") or {}

    # Le prese vive per fase: serve a riconoscere un rilascio che il registro ha gia' registrato.
    vive = {
        str(voce.get("task_id"))
        for voce in state.get("active_claims") or []
        if voce.get("status") in ("active", "taken", "pre_registered", "ready", "active_extension")
        and not str(voce.get("released_at") or "").strip()
    }

    # 1) sostituite: stessa ancora e stesso campo, piu' di una volta. Vale l'ultima depositata.
    ultima = {}
    for voce in richieste:
        ultima[(voce["anchor"], voce["field"])] = voce["file"]

    # 2) l'ancora compare piu' volte nel file di destinazione e la richiesta non dice quale.
    occorrenze = {}
    for percorso in {ws.path(voce["destinazione"] or ws.state) for voce in richieste}:
        try:
            testo = percorso.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        righe = Counter(riga.strip() for riga in testo.splitlines())
        occorrenze[percorso] = righe

    sospette = []
    for voce in richieste:
        motivi = []
        gemella = ultima.get((voce["anchor"], voce["field"]))
        if gemella and gemella != voce["file"]:
            motivi.append(f"sostituita da `{gemella}`, depositata dopo")
        if voce["field"] == "attempt" and str(voce["text"]).strip().isdigit():
            su_disco = _attempt_su_disco(ws, voce["fase"])
            if su_disco and int(str(voce["text"]).strip()) <= su_disco:
                motivi.append(
                    f"riporterebbe il registro all'attempt {voce['text'].strip()} mentre su disco c'e' il {su_disco}"
                )
        if voce["item"].get("attempt") and voce["fase"]:
            su_disco = _attempt_su_disco(ws, voce["fase"])
            if su_disco and int(voce["item"]["attempt"]) <= su_disco:
                motivi.append(
                    f"inserirebbe una voce all'attempt {voce['item']['attempt']} mentre su disco c'e' il {su_disco}"
                )
        # Un INSERIMENTO di presa (`item:` con uno stato vivo) e' la richiesta piu' delicata: non
        # corregge un campo, aggiunge una voce che resta li'. Se la fase ha gia' una presa viva, o se
        # e' andata avanti, quella voce diventa un titolare che non esiste — e la fase resta «in
        # corso» per sempre, perche' nessuno rilascera' la presa di un fantasma. Misurato il
        # 2026-10-16: in coda ci sono due inserimenti di presa del giorno prima, mai applicati.
        stato_item = str(voce["item"].get("status") or "")
        if voce["item"] and stato_item in ("taken", "active", "pre_registered", "ready"):
            if voce["fase"] in vive:
                motivi.append("la fase ha GIA' una presa viva: questa ne aggiunge una seconda")
            else:
                su_disco = _attempt_su_disco(ws, voce["fase"])
                if su_disco and int(voce["item"].get("attempt") or 0) <= su_disco:
                    motivi.append(
                        f"inserisce una presa vecchia (attempt {voce['item'].get('attempt')}) su una fase "
                        f"gia' al attempt {su_disco}: resterebbe «in corso» con un titolare che non c'e' piu'"
                    )
        if voce["field"] == "status" and str(voce["text"]).strip() == "released":
            if voce["fase"] and voce["fase"] not in vive:
                motivi.append("il registro non mostra prese vive su questa fase: forse il rilascio e' gia' applicato")
        if voce["occurrence"] is None and voce["anchor"]:
            righe = occorrenze.get(ws.path(voce["destinazione"] or ws.state)) or Counter()
            if righe.get(voce["anchor"].strip(), 0) > 1:
                motivi.append("ancora ambigua e nessuna `occurrence`: l'applicatore la rifiuta")
        if motivi:
            # Prima quelle che possono CORROMPERE il registro (una presa fantasma, un numero che
            # torna indietro, un'ancora che l'applicatore rifiuta), poi quelle solo superate: l'elenco
            # in pagina e' tagliato, e a chi applica servono in quest'ordine.
            grave = any(
                parola in " ".join(motivi)
                for parola in ("GIA'", "inserisce", "riporterebbe", "inserirebbe", "ambigua")
            )
            sospette.append(
                {
                    **{k: voce[k] for k in ("file", "fase", "field", "by")},
                    "motivi": motivi,
                    "grave": grave,
                }
            )
    sospette.sort(key=lambda voce: (not voce["grave"], voce["file"]))

    per_fase = Counter(voce["fase"] or "(senza fase)" for voce in richieste)
    ferme = [voce for voce in richieste if voce["at"] and adesso - voce["at"] > timedelta(hours=SOGLIA_ORE)]
    radice = str(ws.root)
    # I comandi: la COPIA per prima, perche' i registri di questo progetto NON sono tracciati da git
    # e non c'e' nessun «annulla». E la prova a vuoto su UNA richiesta sola: sui 129 file stamperebbe
    # il registro INTERO (2,3 MB) una volta per ciascuno.
    prima = richieste[0]["percorso"] if richieste else "pending-transitions/<una-richiesta>.yaml"
    return {
        "totale": len(richieste),
        "ferme": len(ferme),
        "soglia_ore": SOGLIA_ORE,
        "piu_vecchia": min((voce["at"] for voce in richieste if voce["at"]), default=None),
        "per_fase": [[fase, numero] for fase, numero in per_fase.most_common(8)],
        "sospette": sospette[:limite_sospette],
        "sospette_totali": len(sospette),
        "da_applicare": len(richieste) - len(sospette),
        "indietro": _registro_indietro(ws, state),
        "comandi": {
            "copia": f"cd {radice} && cp state.yaml /tmp/state-prima-della-coda.yaml",
            "prova": f"cd {radice} && python3 tools/apply_transitions.py {prima} --dry-run | head -40",
            "applica": f"cd {radice} && python3 tools/registry_runner.py --once",
        },
    }


def main(argv=None):
    analizzatore = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizzatore.add_argument("--workspace", required=True)
    analizzatore.add_argument("--json", action="store_true")
    argomenti = analizzatore.parse_args(argv)
    ws = Workspace.load(argomenti.workspace)
    esito = leggi(ws)
    if argomenti.json:
        print(json.dumps(esito, ensure_ascii=False, default=str, indent=1))
        return 0
    print(
        f"coda: {esito['totale']} richieste · {esito['ferme']} ferme da piu' di "
        f"{esito['soglia_ore']} ore · {esito['sospette_totali']} da guardare prima di applicare"
    )
    for fase, numero in esito["per_fase"]:
        print(f"  {fase:<12} {numero}")
    for voce in esito["sospette"]:
        print(f"  ! {voce['file']} ({voce['fase']}): " + "; ".join(voce["motivi"]))
    for voce in esito["indietro"]:
        print(f"  > registro indietro: {voce['phase']} — registro {voce['registro']} / disco {voce['disco']}")
    print("\nprova:", esito["comandi"]["prova"])
    print("applica:", esito["comandi"]["applica"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
