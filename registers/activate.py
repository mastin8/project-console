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

import apply_transitions  # noqa: E402 - la scrittura sui registri passa sempre da li'
import next_prompts  # noqa: E402 - il quaderno, per il testo del prompt
import rework  # noqa: E402 - quante volte una fase e' tornata indietro, e per cosa
import handoff  # noqa: E402 - cosa il registro dice che e' dovuto dopo
from workspace import Workspace, lock_file  # noqa: E402

LIVE = ("active", "taken", "pre_registered", "ready", "active_extension")
STALLED = ("needs_changes", "failed")


def _rilasciata(voce):
    return bool(str(voce.get("released_at") or "").strip())


def prese(state):
    """Le prese VIVE per fase. Il registro ripete le voci e l'ordine non e' cronologico: si
    guardano tutte, e una voce viva con `released_at` vuoto vale come presa.

    Fra piu' voci vive della stessa fase si prende la PIU' RECENTE per data, non l'ultima scritta:
    e' la differenza fra mostrare «in corso» e mostrare «in attesa di un esecutore» per una fase che
    un agente ha gia' preso (misurato il 2026-10-15 su un registro con piu' voci per fase).
    """
    raccolte = {}
    for voce in state.get("active_claims") or []:
        fase = voce.get("task_id")
        if not fase or voce.get("status") not in LIVE or _rilasciata(voce):
            continue
        raccolte.setdefault(str(fase), []).append(voce)

    def quando(voce):
        for campo in ("taken_at", "registered_at", "released_at"):
            valore = voce.get(campo)
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

    return {
        fase: max(voci, key=lambda v: quando(v) or datetime.min.replace(tzinfo=timezone.utc))
        for fase, voci in raccolte.items()
    }


def fasi(tasks_doc):
    """(id, unit_id, kind, title) nell'ordine del file."""
    return [
        (str(t.get("id")), str(t.get("unit_id") or ""), str(t.get("kind") or ""), str(t.get("title") or ""))
        for t in tasks_doc.get("tasks") or []
        if t.get("id")
    ]


def _prima_di(ws, tasks_doc, fase):
    """Le fasi della stessa unita' che nel ciclo vengono PRIMA di questa, e che non sono accettate.

    IL PERCORSO E' OBBLIGATO DALL'ALFA ALL'OMEGA. Il ciclo (`ws.phases`: A, E, T, R) non e' una
    convenzione: ogni fase MISURA l'output della precedente, quindi partire dalla `R` di un'unita' mai
    iniziata — cosa che la pagina offriva, perche' un report la nominava — produce atti su niente.
    Misurato il 2026-10-16: la coda offriva `HIST01R`, l'ultima fase di un'unita' ferma alla prima.

    Il parallelismo resta possibile dove NON c'e' dipendenza: fra unita' diverse i cui prerequisiti
    dichiarati sono accettati. Questo cancello e' per unita', non per progetto.
    """
    ordine = [str(s).upper() for s in (ws.phases or ("A", "E", "T", "R"))]
    unita = next(
        (uid for uid, *_ in fasi(tasks_doc) if str(fase).startswith(uid)),
        str(fase)[:-1],
    )
    suffisso = str(fase)[len(unita) :].upper()
    if suffisso not in ordine:
        return []
    return [unita + s for s in ordine[: ordine.index(suffisso)]]


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
            documento = _carica(percorso.read_text(encoding="utf-8")) or {}
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


def _motivo_scaduto(documento):
    """Perche' un ordine non va piu' consegnato, o None se vale ancora.

    Convenzione nata sul campo: chi si accorge che un ordine e' superato lo scrive DENTRO l'ordine,
    con un campo che comincia per `stale` (`stale_declared_20261015T1600`, `stale_20261015T1620`).
    L'ordine resta sul disco — e' la storia di cosa era stato chiesto — ma non si consegna piu'.

    Perche' serve un guardiano qui: misurato il 2026-10-16, la pagina ha consegnato lo stesso ordine
    stantio di `TODO03E` a QUATTRO attivazioni (e sette sessioni l'hanno ricevuto e rifiutato, con la
    misura scritta nei loro atti). La causa era questa funzione che non c'era: `attiva()` riusava il
    primo ordine aperto, anche quando l'ordine dichiarava di essere morto. Un tool che riconsegna un
    mandato scaduto brucia il turno di chi lo riceve.
    """
    for chiave, valore in (documento or {}).items():
        if str(chiave).lower().startswith("stale") and str(valore or "").strip():
            return str(valore).strip()
    return None


def mandati(ws):
    """Ogni ordine in coda, col suo stato: {percorso: {"scaduto", "consumato_da", "quando"}}.

    Due modi perche' un ordine non vada piu' consegnato, e sono due misure diverse:

    * **si dichiara scaduto**: chi si accorge che il lavoro ordinato e' atterrato altrove lo scrive
      dentro l'ordine, con un campo che comincia per `stale`;
    * **e' consumato**: un tentativo della fase e' stato pubblicato DOPO la data dell'ordine. Il
      mandato ha gia' prodotto il suo atto: riconsegnarlo significa dare a qualcuno un ordine che
      parla di byte e criteri di prima, e chi lo riceve lo rifiuta — oppure, peggio, lo esegue.

    La seconda misura e' quella che il 2026-10-16 spiegava dodici ordini aperti su diciotto: lo
    stesso mandato di `NAV03R` riconsegnato a cinque attivazioni, quello di `TODO03E` a quattro,
    quello di `UPL04ZR` a tre, con le fasi respinte ogni volta su un oggetto che si era mosso.
    """
    fuori = {}
    coda = ws.path("dispatch-queue")
    if not coda.is_dir():
        return fuori
    for percorso in sorted(coda.glob("*.yaml")):
        try:
            documento = _carica(percorso.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(documento, dict):
            continue
        quando = _quando_ordine(documento, percorso)
        fase = str(documento.get("code") or documento.get("task_id") or "")
        fuori[str(percorso.relative_to(ws.root))] = {
            "scaduto": _motivo_scaduto(documento) or "",
            "consumato_da": _tentativi_dopo(ws, fase, quando) if fase and quando else [],
            "quando": quando.isoformat() if quando else "",
            "fase": fase,
        }
    return fuori


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


def _quando_ordine(documento, percorso):
    """Quando un ordine e' stato depositato: la sua data dichiarata, o l'mtime del file."""
    for campo in ("activated_at", "requested_at", "prompt_frozen_at", "prepared_at"):
        momento = _momento(documento.get(campo))
        if momento:
            return momento
    try:
        return datetime.fromtimestamp(percorso.stat().st_mtime).astimezone()
    except OSError:
        return None


def _tentativi_dopo(ws, fase, quando):
    """Gli attempt di quella fase pubblicati DOPO l'ordine: il mandato e' gia' stato eseguito."""
    if not fase or not quando:
        return []
    cartella = ws.reports_dir / str(fase)
    if not cartella.is_dir():
        return []
    dopo = []
    for tentativo in sorted(cartella.glob("attempt-*.yaml")):
        try:
            documento = _carica(tentativo.read_text(encoding="utf-8", errors="replace")) or {}
        except (yaml.YAMLError, OSError):
            documento = {}
        momento = _momento(documento.get("published_at") or documento.get("prepared_at"))
        if momento is None:
            try:
                momento = datetime.fromtimestamp(tentativo.stat().st_mtime).astimezone()
            except OSError:
                continue
        if momento > quando:
            dopo.append(tentativo.name)
    return dopo


def _spedizioni(state, fase):
    """Quante volte un ordine di questa fase e' gia' stato consegnato (voci di presa nel registro).

    E' il numero che rende visibile lo spreco: un mandato consegnato quattro volte e rifiutato
    quattro volte non e' un mandato da consegnare una quinta.
    """
    conta = {}
    for voce in state.get("active_claims") or []:
        if str(voce.get("task_id") or "") != str(fase):
            continue
        percorso = str(voce.get("order") or "").strip()
        if percorso:
            conta[percorso] = conta.get(percorso, 0) + 1
    return conta


def attivabili(ws, state=None, tasks_doc=None, dovuto=None):
    """Cosa si puo' far partire adesso, e perche' — misurato, non indovinato.

    Regola: una fase senza presa viva, i cui PREREQUISITI DICHIARATI (`depends_on`: la catena
    A -> E -> T -> R, e le dipendenze fra unita') sono tutti accettati. Le fasi respinte in
    verifica restano attivabili — sono lavoro da rifare, e nel caso normale il loro prerequisito
    e' accettato — e lo dichiarano.

    Con un'eccezione misurata: una fase la cui ULTIMA dichiarazione manda a fasi tutte GIA'
    accettate non e' la prossima cosa da fare. Vuol dire che l'atto dovuto e' un tentativo NUOVO su
    una di quelle — «non e' questa fase a dover ripartire: la palla e' di `UPL04ZT` attempt 2» — e
    offrirla col pulsante «Attiva» e' la stessa bugia dell'ordine riconsegnato. Misurato il
    2026-10-16: era il caso di tutte e quattro le fasi in coda (`NAV03R`, `TODO03E`, `UPL04ZR`,
    `OVR01R`), mentre `REG03T` e `REG03R`, che nominano una fase NON accettata, restavano in catena.
    Quelle voci tornano con `altrove: True` e con `next_act`: la pagina le mostra in una riga sola,
    senza pulsante, e `attiva()` le rifiuta dicendo perche'.
    """
    state = state if state is not None else (_carica(ws.state_path.read_text(encoding="utf-8")) or {})
    tasks_doc = tasks_doc if tasks_doc is not None else (_carica(ws.path(ws.tasks).read_text(encoding="utf-8")) or {})
    registrate = state.get("tasks") or {}
    vive = prese(state)
    ordini = ordini_aperti(ws)
    stato_ordini = mandati(ws)
    if dovuto is None:
        dovuto = handoff.dovuto(ws, state, tasks_doc, limite=30, prese=set(vive))
    # `altrove` vuol dire: la sua ultima dichiarazione manda SOLO a fasi gia' accettate, quindi
    # l'atto e' un tentativo nuovo su quelle, non su questa.
    per_fase = {}
    for voce in dovuto:
        codici = voce.get("codes") or []
        per_fase[voce["from_phase"]] = {
            "codes": codici,
            "altrove": bool(codici) and all(c["status"] == "accepted" for c in codici),
        }
    unita = {str(u.get("id")): u for u in tasks_doc.get("units") or [] if u.get("id")}
    per_id = {str(t.get("id")): t for t in tasks_doc.get("tasks") or [] if t.get("id")}

    def stato_di(fase):
        return (registrate.get(fase) or {}).get("status", "pending")

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
    # UNA SOLA FASE VIVA PER UNITA'. Le fasi di un'unita' sono una catena (A -> E -> T -> R) perche'
    # ognuna misura l'output della precedente: due fasi vive insieme significano misurare byte che si
    # stanno muovendo — la classe di difetto che ha bruciato 11 atti su `UPL04ZR` (`T-ON-CURRENT-
    # REVISION` in 10 su 10) e invalidato piu' ratifiche di `NAV03R`. L'eccezione — derivare i casi dal
    # design mentre la E lavora — e' TESTO nel mandato, non una presa: non passa da qui.
    occupate = {}
    for fase_viva, voce_viva in vive.items():
        unita_viva = str(voce_viva.get("unit") or "")
        if not unita_viva:
            unita_viva = next(
                (uid for uid in sorted(unita, key=len, reverse=True) if str(fase_viva).startswith(uid)),
                "",
            )
        if unita_viva:
            occupate.setdefault(unita_viva, []).append(str(fase_viva))
    # La misura della ripetizione, solo per le fasi respinte: e' li' che serve, e sono poche. Una
    # fase respinta dieci volte per lo stesso motivo non si sblocca con un altro tentativo, e chi
    # legge la coda deve vederlo PRIMA di premere «Attiva».
    misure = rework.per_fase(
        ws, [fase for fase, *_ in fasi(tasks_doc) if stato_di(fase) in STALLED]
    )
    for fase, unit_id, kind, titolo in fasi(tasks_doc):
        stato = stato_di(fase)
        if stato == "accepted" or fase in vive:
            continue
        # I PREREQUISITI DELLA FASE, che fino a questa revisione non si leggevano. La misura che
        # li ha resi necessari: il 2026-10-15 la pagina ha offerto all'utente cinque fasi con il
        # prerequisito APERTO (`A11Y03R` mentre `A11Y03T` era respinta, `REG03R` mentre `REG03T`
        # era respinta, `OVR01E`/`OVR01R`/`OVR01T` mentre `OVR01VR` era in volo). L'attivazione ha
        # creato sei riserve su fasi che non potevano partire; chi ha letto quelle riserve come un
        # difetto le ha poi chiuse scrivendo su una voce STORICA del registro. Il pulsante si offre
        # col cancello aperto e non prima.
        gated = [
            str(dip)
            for dip in (per_id.get(fase) or {}).get("depends_on") or []
            if stato_di(str(dip)) != "accepted"
        ]
        if gated:
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
                "misura": misure.get(fase),
                # Cosa la sua ultima dichiarazione dice che va fatto dopo — e se manda altrove.
                "next_act": (per_fase.get(fase) or {}).get("codes") or [],
                "altrove": bool((per_fase.get(fase) or {}).get("altrove")),
                # La sua unita' ha gia' una fase viva: questa aspetta, e la pagina lo dice.
                "bloccata_da_unita": [
                    altra for altra in occupate.get(str(unit_id), []) if altra != str(fase)
                ],
                # Il ciclo interno dell'unita': le fasi che vengono prima e non sono accettate.
                "bloccata_da_ciclo": [
                    precedente
                    for precedente in _prima_di(ws, tasks_doc, fase)
                    if stato_di(precedente) != "accepted"
                ],
                "waiting_on": attese,
                # Se un ordine c'e' gia', la pagina lo mostra invece di offrire un pulsante che
                # verrebbe rifiutato.
                "orders": ordini.get(fase, []),
                # Il mandato che questa attivazione consegnerebbe: se e' scaduto, la pagina lo dice
                # e `attiva` ne deposita uno NUOVO invece di riconsegnare quello morto.
                "mandato": _mandato_di(ordini.get(fase, []), stato_ordini, _spedizioni(state, fase)),
                # Il file di consegna e' il PROSSIMO tentativo, non sempre il primo: un rifacimento
                # che chiedesse `attempt-1` chiederebbe di riscrivere un artefatto consegnato.
                "deliverable": f"{ws.deliverable_prefix}{fase}/attempt-{prossimo_tentativo(state, fase)}.yaml",
            }
        )
    fuori.sort(key=lambda voce: (bool(voce["waiting_on"]), voce["rework"] is False, voce["phase"]))
    return fuori


def _riusabile(stato):
    """Un ordine si puo' riconsegnare solo se non e' scaduto e non e' gia' stato eseguito."""
    return not stato.get("scaduto") and not stato.get("consumato_da")


def _mandato_di(percorsi, stato_ordini, spedizioni):
    """L'ordine che verrebbe consegnato, riusabile o scaduto, con quante volte e' gia' andato.

    Fra piu' ordini aperti si sceglie l'ultimo RIUSABILE: se il piu' recente e' scaduto, quello che
    conta e' che esiste un ordine ancora vivo da consegnare.
    """
    riusabili = [percorso for percorso in percorsi if _riusabile(stato_ordini.get(percorso) or {})]
    if riusabili:
        scelto = riusabili[-1]
    elif percorsi:
        scelto = percorsi[-1]
    else:
        return None
    stato = stato_ordini.get(scelto) or {}
    return {
        "path": scelto,
        "scaduto": not _riusabile(stato),
        "motivo": stato.get("scaduto") or "",
        # Gli attempt pubblicati dopo l'ordine: e' la misura del «gia' eseguito». I nomi, non un
        # numero, perche' in pagina si legge quali atti hanno consumato il mandato.
        "consumato_da": stato.get("consumato_da") or [],
        "consegnato_a": spedizioni.get(scelto, 0),
    }


def prossimi(ws, state=None, tasks_doc=None):
    """IL PERCORSO, DALLA PRIMA ALL'ULTIMA UNITA': una riga per unita' aperta, col suo prossimo atto.

    Perche' cosi' e non dalle dichiarazioni: i report nominano decine di fasi — anche vecchie, anche
    di unita' mai iniziate — e una coda costruita su quelli chiede cose che il percorso non permette
    (misurato il 2026-10-16: 49 «mandabili», fra cui la `R` di un'unita' ferma alla `A`). Qui invece
    la sorgente e' il REGISTRO: per ogni unita' non ancora accettata, la prima fase del ciclo non
    accettata, con lo stato, i prerequisiti che la tengono ferma e la leva (quante unita' la
    aspettano). Una riga per unita' = un atto alla volta per unita', e il parallelismo resta dove le
    unita' non si condizionano.
    """
    state = state if state is not None else (_carica(ws.state_path.read_text(encoding="utf-8")) or {})
    tasks_doc = tasks_doc if tasks_doc is not None else (_carica(ws.path(ws.tasks).read_text(encoding="utf-8")) or {})
    registrate = state.get("tasks") or {}
    vive = prese(state)
    unita = {str(u.get("id")): u for u in tasks_doc.get("units") or [] if u.get("id")}
    ordine = [str(s).upper() for s in (ws.phases or ("A", "E", "T", "R"))]
    stato_di = lambda fase: (registrate.get(fase) or {}).get("status", "pending")

    chiuse = {
        uid
        for uid in unita
        if all(stato_di(uid + s) == "accepted" for s in ordine)
    }
    blocca = {}
    for uid, u in unita.items():
        for dipendenza in u.get("depends_on_units") or []:
            blocca.setdefault(str(dipendenza), []).append(uid)

    fuori = []
    for uid, u in unita.items():
        if uid in chiuse:
            continue
        fasi_aperte = [uid + s for s in ordine if stato_di(uid + s) != "accepted"]
        if not fasi_aperte:
            continue
        prossima = fasi_aperte[0]
        attesa = [f"{f} ({stato_di(f)})" for f in fasi_aperte[1:]] if False else []
        for dipendenza in u.get("depends_on_units") or []:
            dipendenza = str(dipendenza)
            if dipendenza not in chiuse:
                attesa.append(f"{dipendenza} (unita' non accettata)")
        for dipendenza in (next((t for t in tasks_doc.get("tasks") or [] if str(t.get("id")) == prossima), {}) or {}).get("depends_on") or []:
            dipendenza = str(dipendenza)
            if stato_di(dipendenza) != "accepted":
                attesa.append(f"{dipendenza} ({stato_di(dipendenza)})")
        presa = vive.get(prossima) or {}
        stato_presa = str(presa.get("status") or "")
        # CONSEGNATA MA NON ACCETTATA. Un agente puo' aver gia' pubblicato il suo atto — la `A` di
        # un'unita', per esempio, con verdetto `ready_for_execution` — mentre il registro dice ancora
        # `pending`, perche' l'accettazione dell'handoff e' un atto del coordinamento. Senza questo
        # stato la pagina rimanda la stessa fase e l'analisi si rifa' da capo: il ciclo peggiore.
        percorso_report, _, _, documento = handoff.ultimo_report(ws, state, prossima)
        verdetto = ""
        if percorso_report is not None:
            verdetto = str((documento or {}).get("verdict") or "")
        consegnata = bool(verdetto) and any(
            verdetto.startswith(prefisso)
            # `accept*` copre `accepted` e i verdetti dei progetti (`accept_unit_with_declared_limits`):
            # un atto che accetta l'unita' E' una consegna, e senza questo la pagina non la vedeva.
            for prefisso in ("ready_for_execution", "pass", "delivered", "accept")
        )
        # UNA PRENOTAZIONE PIU' VECCHIA DELLA CONSEGNA E' SPAZZATURA. Se la fase e' stata consegnata
        # e la prenotazione (`pre_registered`) e' anteriore al report, quell'ordine e' stato consumato:
        # nessuno la "sta facendo", e mostrarla come riservata rimanda una fase gia' fatta. Misurato il
        # 2026-10-17: `REG03T` consegnata alle 10:13 e ancora «riservata» da un ordine delle 10:02.
        riserva_vecchia = False
        if consegnata and percorso_report is not None and stato_presa in ("pre_registered", "ready"):
            quando_presa = _momento(presa.get("registered_at") or presa.get("taken_at"))
            try:
                quando_report = datetime.fromtimestamp(
                    percorso_report.stat().st_mtime, tz=timezone.utc
                )
            except OSError:
                quando_report = None
            if quando_presa and quando_report and quando_presa < quando_report:
                riserva_vecchia = True
                stato_presa = ""
        fuori.append(
            {
                # `code` e `phase` sono la stessa cosa: la riga in pagina usa `code` per tutte le
                # sorgenti (dichiarazioni e percorso), e senza l'alias il disegno si fermava con
                # «Cannot read properties of undefined».
                "code": prossima,
                "phase": prossima,
                "unit": uid,
                "block": str(u.get("domain") or "senza-dominio"),
                "title": str(next((t.get("title") for t in tasks_doc.get("tasks") or [] if str(t.get("id")) == prossima), "") or u.get("title") or ""),
                "status": stato_di(prossima),
                "attempt": (registrate.get(prossima) or {}).get("attempt") or 0,
                "attesa": sorted(set(attesa)),
                "leva": len(blocca.get(uid, [])),
                # «In corso» e «riservata» non sono la stessa cosa: una presa `pre_registered` e' un
                # ordine depositato che nessuno ha raccolto, e la riga non deve dire che qualcuno ci
                # sta lavorando — ne' offrire di attivarla (l'attivazione la rifiuta).
                "live": stato_presa if stato_presa in ("taken", "active", "active_extension") else "",
                "riservata": stato_presa in ("pre_registered", "ready"),
                "riserva_vecchia": riserva_vecchia,
                "consegnata": consegnata,
                "verdetto": verdetto,
                "report": str(percorso_report.relative_to(ws.root)) if percorso_report else "",
                "owner": str(presa.get("taken_by") or presa.get("owner_agent") or ""),
                "apre": fasi_aperte[1:],
            }
        )
    # Prima le unita' che tengono piu' altre (percorso critico), poi quelle piu' vicine alla fine.
    fuori.sort(key=lambda voce: (-voce["leva"], len(voce["apre"]), voce["phase"]))
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
        for t in (_carica(ws.path(ws.tasks).read_text(encoding="utf-8")) or {}).get("tasks") or []
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
    coda = ws.path("dispatch-queue")
    percorso = coda / f"{quando}-{fase}-attivazione.yaml"
    # Due attivazioni nello stesso secondo non devono sovrascriversi: un ordine e' la prova di cosa
    # era stato chiesto, e una prova sovrascritta non prova niente.
    for tentativo in range(2, 100):
        if not percorso.exists():
            return percorso
        percorso = coda / f"{quando}-{fase}-attivazione-{tentativo}.yaml"
    return percorso


def costruisci_ordine(ws, voce, state, prompt=None):
    """Il file che un esecutore trova: cosa fare, con quale testo, su quale revisione, con quale
    criterio di accettazione."""
    revisione, fonte_revisione = impronte(ws, state, voce["phase"])
    testo = (prompt or {}).get("text")
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
        "prompt": testo,
        # L'impronta del prompt: se qualcuno lo ricompone piu' tardi e viene diverso, la differenza
        # si vede invece di essere silenziosa. E' la stessa disciplina delle impronte di revisione.
        "prompt_sha256": hashlib.sha256(testo.encode("utf-8")).hexdigest() if testo else None,
        "prompt_frozen_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
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


def _ultima_ancora(state, ws):
    """(ancora, occorrenza) dell'ULTIMA voce di claim, per appenderne una nuova dopo di lei.

    L'occorrenza serve: il registro ripete gli id, e senza dirla l'applicatore rifiuta l'ancora
    ambigua — giustamente, perche' non deve scegliere lui quale voce intendevi.

    Con `active_claims` VUOTO — un progetto al primo giorno — non c'e' nessuna voce dopo cui
    appendere: si usa la riga della chiave, che e' unica, e la voce nuova nasce subito sotto. Senza
    questo, la PRIMISSIMA attivazione di un progetto falliva (misurato sull'esempio del repository).
    """
    voci = [str(v.get("task_id")) for v in state.get("active_claims") or [] if v.get("task_id")]
    if voci:
        ultima = voci[-1]
        return f"- task_id: {ultima}", sum(1 for v in voci if v == ultima)
    # Nessuna presa: si usa la RIGA della chiave, riprodotta com'e' scritta nel file (l'ancora deve
    # combaciare alla lettera). Una sequenza COMPATTA non puo' ricevere una voce dopo di se':
    # `active_claims: []` seguito da `- task_id: ...` non e' YAML valido, e lo si dice invece di
    # farlo scoprire al validatore.
    for riga in ws.state_path.read_text(encoding="utf-8").splitlines():
        if riga.startswith("active_claims:"):
            if riga.strip() != "active_claims:":
                raise apply_transitions.TransitionError(
                    f"il registro tiene `{riga.strip()}` in forma compatta: per potervi appendere una "
                    "presa va scritto `active_claims:` su una riga sua, senza `[]`"
                )
            return riga, 1
    raise apply_transitions.TransitionError("il registro non ha la chiave `active_claims`")


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

    # Lo STESSO lock delle corsie: due scrittori sugli stessi registri non devono sovrapporsi.
    lock = Path(lock_file(ws.root))
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
    state = _carica(ws.state_path.read_text(encoding="utf-8")) or {}
    tasks_doc = _carica(ws.path(ws.tasks).read_text(encoding="utf-8")) or {}
    voce = next((v for v in attivabili(ws, state, tasks_doc) if v["phase"] == fase), None)
    if voce is None:
        presa = prese(state).get(fase)
        if presa:
            raise apply_transitions.TransitionError(
                f"{fase} ha gia' una presa viva ({presa.get('owner_agent') or presa.get('taken_by') or presa.get('status')}): "
                "attivarla di nuovo farebbe due esecutori sugli stessi byte"
            )
        # Perche' non e' attivabile: se il cancello dei prerequisiti e' chiuso il motivo e' MISURATO
        # e va detto, invece di rispondere «fase non attivabile o inesistente». Serve anche contro
        # una pagina vecchia, che offre un pulsante ormai chiuso.
        registrate = state.get("tasks") or {}
        per_id = {str(t.get("id")): t for t in tasks_doc.get("tasks") or [] if t.get("id")}
        gated = [
            str(dip)
            for dip in (per_id.get(fase) or {}).get("depends_on") or []
            if (registrate.get(str(dip)) or {}).get("status", "pending") != "accepted"
        ]
        if gated:
            raise apply_transitions.TransitionError(
                f"{fase} non e' attivabile adesso: attende "
                + ", ".join(
                    f"{dip} ({((registrate.get(dip) or {}).get('status') or 'pending')})"
                    for dip in gated
                )
                + ". Attivarla prima creerebbe una riserva su una fase che non puo' partire."
            )
        raise apply_transitions.TransitionError(f"fase non attivabile o inesistente: {fase}")
    # Il caso «la palla e' altrove»: la sua ultima dichiarazione manda a fasi GIA' accettate, quindi
    # l'atto dovuto e' un tentativo NUOVO su quelle. Attivare questa deposita un ordine per un lavoro
    # che il registro stesso ha spostato — la bugia peggiore, perche' e' un ordine durevole.
    if voce.get("altrove"):
        dovuti = ", ".join(c["code"] for c in voce.get("next_act") or [])
        raise apply_transitions.TransitionError(
            f"{fase} non va attivata: la sua ultima consegna dice che il prossimo atto e' un "
            f"tentativo NUOVO su {dovuti}. Deposita l'ordine per quella fase, invece di rimettere "
            "in coda questa."
        )
    # Le fasi di un'unita' sono sequenziali: se un'altra e' viva, questa aspetta.
    if voce.get("bloccata_da_unita"):
        raise apply_transitions.TransitionError(
            f"{fase} non si attiva adesso: nella sua unita' e' gia' in corso "
            f"{', '.join(voce['bloccata_da_unita'])}. Le fasi della stessa unita' sono sequenziali — "
            "ognuna misura l'output della precedente — e misurarne una mentre l'altra scrive produce "
            "un atto gia' vecchio. Aspetta che quella consegni."
        )
    # Il percorso e' obbligato dall'alfa all'omega: non si parte dalla `R` di un'unita' mai iniziata.
    if voce.get("bloccata_da_ciclo"):
        raise apply_transitions.TransitionError(
            f"{fase} non si attiva adesso: prima vengono {', '.join(voce['bloccata_da_ciclo'])} "
            "nel ciclo dell'unita'. Ogni fase misura l'output della precedente: partirne una senza "
            "l'altra produce atti su niente."
        )
    # Il prompt che l'esecutore trova NELL'ORDINE: dal quaderno se c'e', altrimenti composto dal
    # registro. Senza questo, attivare una fase senza sezione nel quaderno lasciava l'ordine con
    # `prompt: null` e nessun testo da incollare (segnalato dall'utente).
    import mandate  # noqa: PLC0415 - import locale: `mandate` usa `activate` per le impronte

    ordine = costruisci_ordine(ws, voce, state, mandate.per(ws, fase))
    # Un ordine per fase: se ce n'e' gia' uno aperto e ANCORA VALIDO si usa QUELLO, non se ne scrive
    # un secondo. Un ordine che si dichiara scaduto non si riconsegna: chi lo riceverebbe lo
    # rifiuterebbe, e il turno e' perso. Misurato il 2026-10-16 su `TODO03E`: quattro attivazioni
    # sullo stesso mandato morto, sette sessioni spese a rifiutarlo.
    esistenti = voce.get("orders") or []
    stato_ordini = mandati(ws)
    riusabili = [
        percorso for percorso in esistenti if _riusabile(stato_ordini.get(percorso) or {})
    ]
    percorso = (ws.root / riusabili[-1]) if riusabili else _order_path(ws, fase)
    # L'ancora si calcola PRIMA di scrivere l'ordine: se il registro non la regge (per esempio
    # `active_claims` vuoto su un progetto al primo giorno) si fallisce senza lasciare un ordine
    # orfano sul disco — che qualcun altro raccoglierebbe mentre la fase e' ancora libera.
    ancora, occorrenza = _ultima_ancora(state, ws)
    if dry_run:
        return {"order": str(percorso), "order_body": ordine, "applied": []}
    if not riusabili:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        if esistenti:
            # La catena resta leggibile: chi trova questo ordine sa quale sostituisce e perche'.
            precedente = esistenti[-1]
            stato = stato_ordini.get(precedente) or {}
            ordine["replaces"] = precedente
            ordine["replaces_why"] = (
                f"l'ordine precedente si dichiara scaduto: {stato.get('scaduto')[:200]}"
                if stato.get("scaduto")
                else "l'ordine precedente era gia' stato eseguito: "
                f"{len(stato.get('consumato_da') or [])} atti pubblicati dopo di lui "
                f"({', '.join(stato.get('consumato_da') or [])[:120]})"
            )
        percorso.write_text(
            yaml.safe_dump(ordine, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
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
        # ancora ambigua ha lasciato un ordine orfano). Se l'ordine c'era GIA' e vale ancora — un
        # rilancio depositato prima — non si tocca: non e' mio. Un ordine scaduto, invece, non si
        # tocca in nessun caso: e' la storia di cosa era stato chiesto.
        if not riusabili:
            percorso.unlink(missing_ok=True)
        raise
    return {
        "order": str(percorso.relative_to(ws.root)),
        "applied": applicate,
        "prompt": ordine.get("prompt"),
        "prompt_source": ordine.get("prompt_source"),
        "action": ordine["action"],
    }


def aggiorna_ordini(ws, solo_vuoti=True):
    """Mette il prompt negli ordini che non ce l'hanno.

    Perche' esiste: le prime attivazioni sono state depositate quando il prompt si prendeva solo dal
    quaderno, quindi per le fasi senza sezione l'ordine e' nato con `prompt:` vuoto — nove su nove
    sul progetto di origine, misurato il 2026-10-15. Il testo esisteva (si ricompone dal registro),
    ma stava solo in pagina: sul disco, dove un esecutore lo cerca, non c'era. **Un prompt che non
    sta sul disco si perde.**

    Non tocca gli ordini che il prompt ce l'hanno: quello e' il testo consegnato, e riscriverlo
    cambiare sotto chi lo sta eseguendo. Ritorna cosa ha scritto e cosa ha lasciato com'era.
    """
    import mandate  # noqa: PLC0415 - import locale: `mandate` usa questo modulo per le impronte

    aggiornati, lasciati = [], []
    coda = ws.path("dispatch-queue")
    if not coda.is_dir():
        return aggiornati, lasciati
    for percorso in sorted(coda.glob("*.yaml")):
        try:
            documento = _carica(percorso.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as errore:
            lasciati.append((percorso.name, f"illeggibile: {errore}"))
            continue
        if not isinstance(documento, dict):
            continue
        fase = documento.get("code") or documento.get("task_id")
        if not fase:
            continue
        if documento.get("fulfilled_status") or documento.get("superseded_by"):
            lasciati.append((percorso.name, "ordine chiuso"))
            continue
        if documento.get("prompt") and solo_vuoti:
            lasciati.append((percorso.name, "prompt gia' presente"))
            continue
        # Un ordine che qualcuno sta ESEGUENDO non si riscrive, nemmeno per arricchirlo: chi lo ha
        # in mano ha una copia, e il file deve restare quello che ha raccolto.
        presa_viva = prese(_carica(ws.state_path.read_text(encoding="utf-8")) or {}).get(str(fase))
        if presa_viva and presa_viva.get("status") in ("taken", "active", "active_extension"):
            lasciati.append((percorso.name, f"in esecuzione ({presa_viva.get('status')}): non lo tocco"))
            continue
        try:
            esito = mandate.per(ws, str(fase))
        except SystemExit as errore:  # fase non dichiarata: si dichiara, non si inventa
            lasciati.append((percorso.name, f"non componibile: {errore}"))
            continue
        documento["prompt"] = esito["text"]
        documento["prompt_source"] = esito["source"]
        documento["prompt_sha256"] = hashlib.sha256(esito["text"].encode("utf-8")).hexdigest()
        documento["prompt_frozen_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
        documento["prompt_added_note"] = (
            "Prompt aggiunto DOPO l'attivazione: l'ordine era nato senza. Il testo e' ricomposto "
            "dal registro; l'ordine resta quello depositato e cambia solo cio' che gli mancava."
        )
        percorso.write_text(
            yaml.safe_dump(documento, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        aggiornati.append(percorso.name)
    return aggiornati, lasciati


def rilascia(ws, fase):
    """Toglie la riserva: l'ordine resta come prova, la fase torna disponibile."""
    state = _carica(ws.state_path.read_text(encoding="utf-8")) or {}
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
    parser.add_argument(
        "--refresh-orders",
        action="store_true",
        help="mette il prompt negli ordini depositati che non ce l'hanno (non tocca gli altri)",
    )
    parser.add_argument("--dry-run", action="store_true", help="mostra l'ordine senza scrivere")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    next_prompts.configure(queue=ws.queue, deliverable_prefix=ws.deliverable_prefix)
    if args.release:
        print(rilascia(ws, args.release))
        return 0
    if args.refresh_orders:
        aggiornati, lasciati = aggiorna_ordini(ws)
        for nome in aggiornati:
            print(f"prompt scritto   {nome}")
        for nome, perche in lasciati:
            print(f"lasciato com'era  {nome}  ({perche})")
        print(f"\naggiornati: {len(aggiornati)} · lasciati: {len(lasciati)}")
        return 0
    if args.target:
        esito = attiva(ws, args.target, dry_run=args.dry_run)
        print(f"ordine: {esito['order']}")
        print(f"scritto nel registro: {', '.join(esito['applied']) or 'niente (dry-run)'}")
        if esito.get("prompt"):
            print(f"prompt nell'ordine: {len(esito['prompt'])} caratteri (fonte: {esito.get('prompt_source')})")
        return 0
    elenco(ws)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
