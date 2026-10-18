#!/usr/bin/env python3
"""Il coordinatore: una pagina locale per leggere e muovere un progetto.

Legge un WORKSPACE — una cartella di registri — e ne mostra lo stato in quattro viste: il percorso
nel tempo, cosa aspetta l'utente, i prompt da eseguire, il percorso per blocchi. Dove serve
scrivere (rispondere a una domanda, chiudere una decisione di governo, depositare un ordine di
lavoro) scrive passando dal lock e dalla validazione dei registri, mai con una riscrittura libera.

Il coordinatore non conosce nessun progetto: i nomi dei file, il nome del progetto, il titolo della
vista e i comandi di verifica si dichiarano nel workspace (`console.yaml`, vedi `workspace.py`).

Uso::

    python3 console/server.py --workspace /percorso/progetto      # http://127.0.0.1:8899
    python3 console/server.py --workspace /tmp/copia --port 9000  # prova su una copia
    CONSOLE_WORKSPACE=/percorso/progetto python3 console/server.py
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml


def _carica(flusso):
    """Legge un registro col parser veloce quando c'e' (libyaml): 17 volte piu' rapido su un
    registro da 2 MB (misurato: 0,09 s contro 1,55 s). Stesso sottoinsieme sicuro di YAML, nessun
    costruttore custom: e' `safe_load` scritto in C, non un'altra sintassi."""
    return yaml.load(flusso, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent / "ui"
CONSOLE_BRAND = Path(__file__).resolve().parent / "brand"


def consegna_misurata(workspace, task_id):
    """La consegna MISURATA sui FILE, non sulla riga del registro.

    Perche' esiste, misurato il 2026-10-16: cinque fasi avevano report e puntatore su disco mentre
    la riga diceva `pending` / `attempt 0` (QA05A, ZIP02A, HIST01A, NAV03R, REG03R) — la pagina
    leggeva solo il registro e le mostrava come non consegnate, quindi il prompt sembrava ancora da
    mandare mentre il lavoro era fatto e consegnato. La riga e' un INDICE: quando e' in ritardo,
    quello che conta e' il file. Chi decide non deve mai dipendere da un indice aggiornato a mano.

    Ritorna `delivered`, `path`, `attempt` (il piu' alto fra i file `attempt-N.yaml`) e
    `pointer_attempt` (quello dichiarato dal puntatore). Nessuna scrittura: sola lettura.
    """
    root = Path(workspace.root)
    prefix = str(getattr(workspace, "deliverable_prefix", "reports/"))
    cartella = root / prefix / str(task_id)
    attempt = 0
    path = None
    for candidate in sorted(cartella.glob("attempt-*.yaml")) if cartella.is_dir() else []:
        trovato = re.search(r"attempt-(\d+)\.yaml$", candidate.name)
        if trovato and int(trovato.group(1)) > attempt:
            attempt, path = int(trovato.group(1)), candidate
    pointer = root / f"{prefix}{task_id}.yaml"
    pointer_attempt = None
    if pointer.is_file():
        try:
            dichiarato = _carica(pointer.read_text(encoding="utf-8")) or {}
            pointer_attempt = dichiarato.get("attempt")
        except yaml.YAMLError:
            pointer_attempt = None
        if path is None:
            path = pointer
    return {
        "delivered": path is not None,
        "path": str(path.relative_to(root)) if path else None,
        "attempt": attempt,
        "pointer_attempt": pointer_attempt,
    }


#: Il codice del coordinatore (questo repo) e quello dei registri (il workspace) sono due cose:
#: il primo si importa da qui, il secondo non si importa affatto — si legge.
sys.path[:0] = [str(ROOT), str(ROOT / "registers"), str(Path(__file__).resolve().parent)]
sys.path.insert(0, str(ROOT))

import apply_transitions  # noqa: E402
import activate  # noqa: E402 - attivare: riserva la fase e deposita l'ordine
import esiti  # noqa: E402 - gli esiti di un atto in punti: criteri, casi, finding, limiti
import handoff  # noqa: E402 - cosa c'e' da fare dopo: il testimone lasciato da chi ha finito
import inbox  # noqa: E402 - la posta in arrivo: i messaggi depositati interi, uno per file
import mandate  # noqa: E402 - il prompt di una fase: dal quaderno, o composto dal registro
import next_prompts  # noqa: E402 - una sola implementazione della regola, condivisa con STATUS.html
import coda  # noqa: E402 - la coda delle transizioni: il registro che non sa cosa e' successo
import accetta  # noqa: E402 - l'atto di accettazione firmato da chi lo prende in carico
import rework  # noqa: E402 - quante volte una fase torna indietro, per la domanda in parole povere
import timeline  # noqa: E402 - la linea del tempo, con le date dichiarate dagli artefatti
from workspace import Workspace, lock_file  # noqa: E402 - il contratto dei nomi: qui non c'e' nessun progetto

PACK_DEFAULT = Path(os.environ.get("CONSOLE_WORKSPACE") or Path.cwd()).expanduser().resolve()

LIVE_STATUSES = ("active", "taken", "pre_registered", "ready", "active_extension")
DONE = ("accepted",)
PHASES = ("A", "E", "T", "R")
PHASE_KIND = {
    "analysis": "Analisi",
    "implementation": "Esecuzione",
    "independent_verification": "Test indipendente",
    "functional_acceptance": "Accettazione",
}


class NotStalledError(Exception):
    """La fase non e' (piu') respinta: quasi sempre la pagina e' un'istantanea vecchia."""

    def __init__(self, task_id, current_status):
        self.task_id = task_id
        self.current_status = current_status
        super().__init__(
            f"{task_id} nel registro e' in stato «{current_status}»: un ordine di rilancio "
            f"si prepara solo per una fase respinta. La pagina che stai guardando e' un'istantanea: "
            f"il registro e' cambiato mentre la tenevi aperta."
        )


class ReviewState:
    def __init__(self, workspace):
        # `workspace` e' un oggetto Workspace: radice + nomi. `pack` resta come scorciatoia verso
        # la radice perche' e' il nome che il corpo di questo file usa da sempre.
        self.workspace = workspace
        self.pack = workspace.root
        #: I registri letti, con il loro tempo di modifica: vedi `_load`.
        self._loaded = {}
        #: L'ultima applicazione della coda, per il pulsante: `in_corso`, `esito`, quante fatte.
        self.applicazione = {"in_corso": False, "esito": "", "quando": ""}
        #: Il lock e' per PROGETTO e il nome si deriva dal percorso con un digest STABILE: `hash()`
        #: cambia a ogni processo (sale casuale), quindi due processi non si vedrebbero.
        self.lock_path = lock_file(self.pack)
        self._queue()

    # ------------------------------------------------------------------ lettura
    def _load(self, name):
        """Un registro, dalla cache se non e' cambiato.

        Perche' la cache serve: un registro da 1,9 MB si legge in ~1,5 s, e la pagina lo chiede a
        ogni richiesta — compreso il prompt di OGNI riga attivata. Senza cache nove righe
        sembravano non aprirsi affatto (misurato: 4-5 s per prompt). La chiave e' il tempo di
        modifica, quindi qualunque scrittura la invalida da sola: nessuna copia stantia.
        """
        path = self.pack / name
        if not path.exists():
            return None
        istante = path.stat().st_mtime_ns
        memoria = self._loaded.get(name)
        if memoria and memoria[0] == istante:
            return memoria[1]
        dato = _carica(path.read_text(encoding="utf-8"))
        self._loaded[name] = (istante, dato)
        return dato

    def versione(self):
        """Quando sono stati scritti i registri che contano: solo `stat`, non una rilettura."""

        def mtime(percorso):
            try:
                return percorso.stat().st_mtime_ns
            except OSError:
                return 0

        return {
            "state_mtime_ns": mtime(self.workspace.state_path),
            "tasks_mtime_ns": mtime(self.workspace.path(self.workspace.tasks)),
        }

    def _queue(self):
        """Le due convenzioni del quaderno si dichiarano prima di leggerlo."""
        next_prompts.configure(
            queue=self.workspace.queue, deliverable_prefix=self.workspace.deliverable_prefix
        )
        timeline.configure(self.workspace)

    def snapshot(self):
        state = self._load(self.workspace.state) or {}
        tasks_doc = self._load(self.workspace.tasks) or {}
        questions = self._load(self.workspace.questions) or {}
        # `or {}`: un registro con la chiave presente e vuota (`tasks:`) si legge come None, e
        # `.get(chiave, default)` NON applica il default in quel caso — e' la forma che il modello
        # di workspace usa proprio perche' ci si possa appendere. Misurato su un progetto nuovo.
        tasks = state.get("tasks") or {}

        blocks = {}
        for unit in tasks_doc.get("units") or []:
            unit_id = unit.get("id")
            if not unit_id:
                continue
            phases = []
            for task in tasks_doc.get("tasks") or []:
                if task.get("unit_id") != unit_id:
                    continue
                task_id = task.get("id")
                registered = tasks.get(task_id) or {}
                # La riga del registro puo' essere in ritardo: la consegna si MISURA sui file, e
                # `register_behind` dice che le due cose non coincidono invece di nasconderlo.
                consegna = consegna_misurata(self.workspace, task_id)
                registrato_attempt = registered.get("attempt") or 0
                phases.append(
                    {
                        "id": task_id,
                        "suffix": task_id[len(unit_id) :],
                        "kind": PHASE_KIND.get(task.get("kind"), task.get("kind")),
                        "title": task.get("title"),
                        "status": registered.get("status", "pending"),
                        "attempt": registrato_attempt,
                        "report": registered.get("report"),
                        "delivered": consegna["delivered"],
                        "delivery_path": consegna["path"],
                        "delivery_attempt": consegna["attempt"] or consegna["pointer_attempt"],
                        # Una divergenza DICHIARATA (`pointer_attempt_declared`) e' una scelta, non
                        # un ritardo: la voce accettata resta sull'attempt accettato mentre sul disco
                        # c'e' un tentativo successivo. Misurato il 2026-10-16 su A11Y03T (accettata
                        # t3, file t5, dichiarata) — se la si segnalasse come «indice in ritardo» si
                        # manderebbe qualcuno a «riparare» una voce corretta.
                        "pointer_attempt_declared": registered.get("pointer_attempt_declared"),
                        "register_behind": bool(
                            consegna["delivered"]
                            and (consegna["attempt"] or consegna["pointer_attempt"] or 0)
                            > int(registrato_attempt or 0)
                            and not registered.get("pointer_attempt_declared")
                        ),
                    }
                )
            order = {key: index for index, key in enumerate(PHASES)}
            phases.sort(key=lambda item: order.get(item["suffix"], 9))
            accepted = bool(phases) and all(p["status"] in DONE for p in phases)
            # La fase di accettazione e' quella che chiude l'unita'. Se e' accettata mentre
            # un'altra voce e' respinta, il registro non e' coerente: e' il caso di QA01T, dove
            # l'unita' era accettata da ieri (QA01R) e la voce T diceva ancora needs_changes.
            acceptance = next((p for p in phases if p["suffix"] == "R"), None)
            accepts_unit = bool(acceptance) and acceptance["status"] in DONE
            blocks.setdefault(unit.get("domain") or "senza-dominio", []).append(
                {
                    "id": unit_id,
                    "title": unit.get("title"),
                    "deliverable": unit.get("deliverable"),
                    "requirements": unit.get("requirement_ids") or [],
                    "depends_on": unit.get("depends_on_units") or [],
                    "accepted": accepted,
                    "accepted_by_phase": accepts_unit,
                    "phases": phases,
                }
            )
            if accepts_unit and not accepted:
                blocks[unit.get("domain") or "senza-dominio"][-1]["incoherent_with"] = acceptance["id"]

        for units in blocks.values():
            units.sort(key=lambda item: item["id"])

        # Quanto pesa una unita' ferma: quante altre la aspettano, direttamente o in catena,
        # e che NON siano gia' chiuse. Contare anche le unita' accettate gonfiava il numero:
        # misurato su QA01T, "blocca 24" includeva unita' gia' chiuse da ieri.
        dependents = {}
        for unit in tasks_doc.get("units") or []:
            for needed in unit.get("depends_on_units") or []:
                dependents.setdefault(needed, set()).add(unit.get("id"))
        done_units = {
            unit["id"] for units in blocks.values() for unit in units if unit["accepted"]
        }
        for units in blocks.values():
            for unit in units:
                seen, frontier = set(), list(dependents.get(unit["id"], ()))
                while frontier:
                    current = frontier.pop()
                    if current in seen or current == unit["id"]:
                        continue
                    seen.add(current)
                    frontier.extend(dependents.get(current, ()))
                unit["blocked"] = sum(1 for name in seen if name not in done_units)
                unit["waiting_total"] = len(seen)
                stalled = [p for p in unit["phases"] if p["status"] in ("needs_changes", "failed")]
                for phase in stalled:
                    phase["why_stalled"] = self._stall_reason(phase["id"], phase.get("report"))
                    phase["report_age"] = self._report_age(phase.get("report"), phase["id"])
                    if unit.get("incoherent_with"):
                        phase["while_unit_accepted"] = unit["incoherent_with"]

        claims = [
            {
                "task_id": c.get("task_id"),
                "phase": c.get("phase"),
                "owner": c.get("owner_agent") or c.get("owner"),
                "taken_at": c.get("taken_at"),
            }
            for c in state.get("active_claims", []) or []
            if c.get("status") in LIVE_STATUSES and not c.get("released_at")
        ]

        open_questions = []
        for q in questions.get("questions") or []:
            if q.get("status") != "asked":
                continue
            opzioni = self._opzioni(q.get("suggested_answers"))
            # «In parole povere»: i codici che la domanda nomina, col loro stato misurato, e le
            # firme del registro quando la scelta riguarda l'indipendenza. Il testo resta quello di
            # chi l'ha scritta; i numeri no, perche' i numeri li ha la piattaforma.
            testi = [q.get("topic"), q.get("question"), q.get("why_unresolved"), q.get("blocked_scope")]
            testi += [voce["label"] + " " + voce["description"] for voce in opzioni]
            testi += list(q.get("affected_tasks") or [])
            open_questions.append(
                {
                    "id": q.get("id"),
                    "topic": q.get("topic"),
                    "question": q.get("question"),
                    "why": q.get("why_unresolved"),
                    "options": opzioni,
                    "asked_on": q.get("asked_on"),
                    "blocks": q.get("affected_tasks") or [],
                    "blocked_scope": q.get("blocked_scope"),
                    "tocca": self._tocca(testi, state, tasks_doc),
                    "firme": self._firme(state)
                    if re.search(r"firm|indipend|ratific", " ".join(str(t or "") for t in testi), re.I)
                    else None,
                }
            )
        answered = [
            {
                "id": q.get("id"),
                "topic": q.get("topic"),
                "question": q.get("question"),
                "answer": q.get("answer"),
                "decision_ref": q.get("decision_ref"),
                "date": q.get("answered_on"),
                "context": self._decision_context(q.get("decision_ref")),
            }
            for q in (questions.get("questions") or [])
            if q.get("status") == "answered"
        ]
        total = sum(len(units) for units in blocks.values())
        done = sum(1 for units in blocks.values() for unit in units if unit["accepted"])
        incoherent = sum(
            1 for units in blocks.values() for unit in units if unit.get("incoherent_with")
        )
        # Le decisioni di governo: appartengono all'utente, non a un task, e stanno in un file a
        # parte proprio per questo. La sezione «Cosa aspetta te» le mostra accanto alle domande.
        decisions_doc = self._load(self.workspace.user_decisions) or {}
        open_decisions = []
        for item in decisions_doc.get("decisions") or []:
            if item.get("status") == "closed":
                continue
            # Se la voce dichiara le alternative, la pagina le offre come scelte; se non le dichiara,
            # si scrive la decisione con parole proprie. Nessuna opzione inventata dal testo della
            # domanda: dedurle dalla prosa sarebbe attribuire all'utente alternative che nessuno ha
            # scritto. La `description` di ogni alternativa e' quello che succede scegliendola, ed e'
            # la parte che nell'UD-5 mancava.
            opzioni = self._opzioni(item.get("options"))
            testi = [item.get("topic"), item.get("question"), item.get("why_yours"), item.get("evidence")]
            testi += [voce["label"] + " " + voce["description"] for voce in opzioni]
            open_decisions.append(
                {
                    "id": item.get("id"),
                    "topic": item.get("topic"),
                    "question": item.get("question"),
                    "evidence": item.get("evidence"),
                    "why": item.get("why_yours"),
                    "options": opzioni,
                    "tocca": self._tocca(testi, state, tasks_doc),
                    "firme": self._firme(state)
                    if re.search(r"firm|indipend|ratific", " ".join(str(t or "") for t in testi), re.I)
                    else None,
                }
            )
        closed_decisions = [
            {
                "id": item.get("id"),
                "topic": item.get("topic") or "decisione di governo",
                "question": item.get("question"),
                "answer": item.get("answer"),
                "decision_ref": item.get("decision_ref"),
                "date": item.get("answered_on"),
                "context": item.get("closed_note"),
            }
            for item in decisions_doc.get("decisions") or []
            if item.get("status") == "closed"
        ]
        # Le direzioni dichiarate dai report (i campi `next`/`next_tasks`): si leggono UNA volta e
        # servono a due cose — la coda (quali fasi hanno la palla altrove) e il blocco «quello che il
        # registro dice che e' dovuto». Leggerle due volte costava il doppio su ogni caricamento.
        dovuto = handoff.dovuto(self.workspace, state, tasks_doc, prese=set(activate.prese(state)))
        return {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            # L'impronta di TEMPO dei registri: due `stat`, nessun parse. La pagina la usa per
            # accorgersi che la sua istantanea e' vecchia (una presa applicata dopo il caricamento
            # restava invisibile finche' non si premeva «Ricarica»).
            "versione": self.versione(),
            # Chi firma nel registro: una firma sola vuol dire che la condizione «chi accetta non
            # deve aver eseguito quei byte» puo' non essere soddisfatta da nessuno che esista. E' il
            # fatto che serve accanto a un ostacolo di firma, e senza il quale l'utente resta con un
            # prompt in mano e nessuna azione.
            "signers": self._firme(state),
            "summary": {
                "blocks": len(blocks),
                "units": total,
                "accepted": done,
                "open_units": total - done,
                "incoherent": incoherent,
                "claims": len(claims),
                "open_questions": len(open_questions),
            },
            "blocks": [
                {"domain": domain, "units": units}
                for domain, units in sorted(blocks.items(), key=lambda item: item[0])
            ],
            "questions": open_questions,
            # La storia tiene insieme le risposte ai task E le decisioni di governo chiuse: sono
            # la stessa cosa per chi le ha date, e senza questo la decisione appena presa
            # sparirebbe dalla pagina invece di finire fra le risposte gia' date.
            "answered": answered + closed_decisions,
            "claims": claims,
            "decisions": open_decisions,
            # I prompt del quaderno con lo stato RICAVATO (registri + file di consegna). Non c'e'
            # un ripiego silenzioso: se questo fallisce la vista esce in errore e lo dice. Una
            # lista vuota mandata al posto di un guasto si leggerebbe «non c'e' nessun prompt»,
            # che e' una cosa falsa detta con parole nostre.
            "next_prompts": next_prompts.build(self.pack, state=state),
            # Cosa si puo' far partire adesso: e' l'input che manca quando non ci sono domande,
            # decisioni o prompt da lanciare. Il calcolo sta in `registers/activate.py`.
            # Una sola lettura delle direzioni dichiarate: la usano sia la coda (per sapere quali
            # fasi hanno la palla altrove) sia il blocco «quello che il registro dice che e' dovuto».
            "activatable": activate.attivabili(self.workspace, state, tasks_doc, dovuto=dovuto),
            # Cosa c'e' da fare dopo: le direzioni che chi ha finito ha GIA' lasciato nei report,
            # e chi invece non le ha lasciate. Sta qui perche' la pagina non l'ha mai mostrato e
            # l'unico modo di saperlo era leggere i report a mano.
            "handoff": {
                "declarations": [
                    {
                        "phase": voce["phase"],
                        "unit": voce["unit"],
                        "block": voce["block"],
                        "status": voce["status"],
                        "verdict": voce["verdict"],
                        "source": voce["source"],
                        "when": voce["when"],
                        "unit_open": voce["unit_open"],
                        "items": voce["items"],
                    }
                    for voce in handoff.dichiarazioni(self.workspace, state, tasks_doc)
                    if voce["items"]
                ],
                "gaps": handoff.lacune(self.workspace, state),
            },
            # Cosa il registro dice che e' DOVUTO adesso: le fasi nominate nei `next` dei report.
            # Perche' serve, misurato il 2026-10-16: i quattro atti dovuti di quel momento
            # (NAV03E attempt 4, TODO03T attempt 5, TODO03R attempt 2, UPL04ZT attempt 2) erano
            # invisibili in pagina, perche' ognuno nominava una fase GIA' ACCETTATA e la coda mostra
            # solo le non accettate. Chi cercava «cosa mando adesso?» non aveva risposta.
            "owed": [
                {
                    "from_phase": voce["from_phase"],
                    "from_unit": voce["from_unit"],
                    "from_status": voce["from_status"],
                    "from_open": voce["from_open"],
                    "source": voce["source"],
                    "when": voce["when"],
                    "text": voce["text"],
                    "codes": voce["codes"],
                }
                for voce in dovuto
            ],
            # La posta in arrivo: quello che e' arrivato e non e' ancora finito in un report. E'
            # l'unico posto della pagina che non legge i registri — legge una cartella di
            # messaggi — perche' un messaggio non deve morire solo perche' non ha un campo dove
            # stare. Senza la cartella l'elenco e' vuoto e la pagina non finge niente.
            "inbox": {
                "cartella": self.workspace.inbox,
                "non_lavorate": inbox.non_lavorate(self.workspace),
                "items": [
                    {
                        "ricevuta": voce["ricevuta"],
                        "file": voce["file"],
                        "phase": voce["phase"],
                        "unit": voce["unit"],
                        "sender": voce["sender"],
                        "kind": voce["kind"],
                        "when": voce["received_at"],
                        "text": voce["testo"],
                        "chars": voce["caratteri"],
                        "worked_by": voce["worked_by"],
                        "closed": bool(voce["closed_at"]),
                        "open": voce["aperta"],
                    }
                    for voce in inbox.voci(self.workspace, tutte=True)
                ],
            },
            # LA CODA DELLE TRANSIZIONI. Gli agenti non scrivono i registri: depositano richieste, e
            # un programma le applica. Quando nessuno le applica, il registro racconta il passato — e
            # con lui tutto quello che ci legge sopra, compresa questa pagina. Misurato il
            # 2026-10-16: 129 richieste in coda, 93 depositate da piu' di dodici ore, e una fase
            # consegnata alle 10:53 che il registro leggeva ancora «respinta, attempt 3».
            "queue": coda.leggi(self.workspace),
            # IL PERCORSO: una riga per unità aperta, col suo prossimo atto. È la sorgente della coda
            # in pagina — non le dichiarazioni dei report, che nominano anche fasi vecchie o di unità
            # mai iniziate (49 «mandabili» su Binche, fra cui la R di un'unità ferma alla A).
            "percorso": activate.prossimi(self.workspace, state, tasks_doc),
            # Lo stato dell'applicazione della coda avviata dal pulsante: la pagina lo mostra mentre
            # lavora e quando ha finito, senza che nessuno debba guardare un terminale.
            "applicazione": dict(self.applicazione),
            "activated": [
                {
                    "phase": fase,
                    # Chi tiene la fase lo dice `taken_by`; `owner` puo' essere un residuo
                    # dell'attivazione («NESSUN TITOLARE: …») e non va mostrato come titolare.
                    "owner": (voce.get("taken_by") or voce.get("owner_agent") or voce.get("owner") or ""),
                    "order": voce.get("order"),
                    "status": voce.get("status"),
                    "since": voce.get("registered_at") or voce.get("taken_at"),
                }
                for fase, voce in activate.prese(state).items()
            ],
        }

    def timeline_payload(self):
        """La linea del tempo: blocchi, unita', fasi, commit.

        Lo stato si carica una volta sola e si passa sia alle fasi sia al quaderno dei prompt: due
        letture dello stesso registro da 1,9 MB possono cadere a cavallo di una scrittura e
        descrivere due stati diversi.
        """
        state = self._load(self.workspace.state) or {}
        return timeline.build(
            self.pack,
            state=state,
            tasks_doc=self._load(self.workspace.tasks) or {},
            questions_doc=self._load(self.workspace.questions) or {},
            decisions_doc=self._load(self.workspace.user_decisions) or {},
            prompt_entries=next_prompts.build(self.pack, state=state),
        )

    def _stall_reason(self, task_id, report_path=None):
        """Perche' la fase e' stata respinta: dal pointer, e se tace dal file del tentativo.

        Il pointer puo' essere scarno (QA01T ha la nota vuota): li' il contenuto sta nel report
        del tentativo, e il primo finding e' la riga piu' utile per chi deve correggere.
        """
        # Prima il report del TENTATIVO (porta i finding), poi il pointer (puo' essere scarno).
        candidates = []
        if report_path:
            candidates.append(self.pack / report_path)
        candidates.append(self.workspace.reports_dir / f"{task_id}.yaml")
        trivial = {
            "needs_changes", "pass", "fail", "failed", "accepted",
            "blocked_verification", "pass_with_declared_residuals", "pending",
        }
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                data = _carica(candidate.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            findings = data.get("findings") or []
            if isinstance(findings, list):
                for finding in findings:
                    if not isinstance(finding, dict):
                        continue
                    for key in ("what", "statement", "detail", "description", "finding"):
                        text = " ".join(str(finding.get(key) or "").split())
                        if text:
                            return f"{finding.get('id', 'finding')} — {text}"[:320]
            for key in ("note", "next", "summary", "recommendation", "verdict"):
                value = data.get(key)
                if isinstance(value, (list, tuple)):  # alcuni report scrivono una lista di passi
                    value = " · ".join(str(item) for item in value)
                text = " ".join(str(value or "").split())
                if text and text.lower() not in trivial:
                    return text[:320]
        return None

    # ------------------------------------------------------------------ scrittura
    def next_decision_id(self):
        decisions = self._load(self.workspace.decisions) or {}
        numbers = []
        for decision in decisions.get("decisions") or []:
            raw = str(decision.get("id", ""))
            if raw.startswith("D") and raw[1:].isdigit():
                numbers.append(int(raw[1:]))
        return f"D{max(numbers, default=0) + 1:03d}"

    def answer(self, question_id, answer_text, label=None):
        questions = self._load(self.workspace.questions) or {}
        found = None
        for question in questions.get("questions") or []:
            if question.get("id") == question_id:
                found = question
                break
        if found is None:
            raise apply_transitions.TransitionError(f"domanda sconosciuta: {question_id}")
        if found.get("status") == "answered":
            raise apply_transitions.TransitionError(f"{question_id} risulta gia' risposta")

        decision_id = self.next_decision_id()
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
        requests = [
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.questions,
                "anchor": f"- id: {question_id}",
                "field": "status",
                "text": "answered",
            },
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.questions,
                "anchor": f"- id: {question_id}",
                "field": "answer",
                "text": answer_text,
            },
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.questions,
                "anchor": f"- id: {question_id}",
                "field": "answer_source",
                "text": "user (pagina di review)",
            },
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.questions,
                "anchor": f"- id: {question_id}",
                "field": "answered_on",
                "text": datetime.now().strftime("%Y-%m-%d"),
            },
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.questions,
                "anchor": f"- id: {question_id}",
                "field": "decision_ref",
                "text": decision_id,
            },
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.decisions,
                "anchor": "- id: D011" if self.next_decision_id() == "D012" else None,
                "item": {
                    "id": decision_id,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "question_id": question_id,
                    "status": "confirmed",
                    "source_user_message": label or answer_text[:80],
                    "user_answer_registered_at": now,
                    "statement": answer_text,
                    "further_questions": [],
                },
                "position": "after",
            },
        ]
        # L'ancora della decisione nuova: l'ULTIMA voce registrata, qualunque essa sia.
        requests[-1]["anchor"] = self.last_decision_anchor()

        applied, failed = [], []
        with open(self.lock_path, "a+") as maniglia:
            fcntl.flock(maniglia, fcntl.LOCK_EX)
            for index, request in enumerate(requests):
                try:
                    # Una sola validazione, sull'ULTIMA richiesta: i sei campi validati uno a uno
                    # costavano 27 s per un solo submit.
                    apply_transitions.apply_request(
                        request,
                        pack=self.pack,
                        validate_after=index == len(requests) - 1,
                    )
                    applied.append(f"{request['file']}#{request.get('field') or decision_id}")
                except apply_transitions.TransitionError as error:
                    failed.append(str(error))
            fcntl.flock(maniglia, fcntl.LOCK_UN)
        if failed:
            raise apply_transitions.TransitionError("; ".join(failed))

        view = ROOT / "registers" / "static_view.py"
        if view.exists():
            subprocess.run(
                [sys.executable, str(view), "--workspace", str(self.pack)],
                cwd=str(self.pack),
                check=False,
            )
        return {"decision_id": decision_id, "applied": applied}

    def decision(self, decision_id, answer_text, label=None):
        """Chiude una decisione di GOVERNO con la risposta dell'utente.

        Le decisioni di governo erano l'unica cosa che l'utente vedeva e non poteva toccare: la
        pagina le mostrava, e per rispondere serviva che una corsia le promuovesse a domanda
        formale (e' quello che e' successo a `UD-3` -> `Q015`). Il canale di scrittura e' lo STESSO
        delle domande — lock di registro, transizioni ancorate, una sola validazione dopo l'ultima
        — perche' due canali di scrittura sugli stessi registri sono due modi di romperli.

        Non cancella la domanda: la chiude, con la risposta e il riferimento alla decisione, e
        lascia la storia dov'e'. Chi deve APPLICARLA la legge in `decisions.yaml`.
        """
        document = self._load(self.workspace.user_decisions) or {}
        found = None
        for item in document.get("decisions") or []:
            if item.get("id") == decision_id:
                found = item
                break
        if found is None:
            raise apply_transitions.TransitionError(
                f"decisione di governo sconosciuta: {decision_id}"
            )
        if found.get("status") == "closed":
            raise apply_transitions.TransitionError(f"{decision_id} risulta gia' chiusa")

        new_id = self.next_decision_id()
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
        fields = {
            "status": "closed",
            "answered_on": datetime.now().strftime("%Y-%m-%d"),
            "answer": answer_text,
            "answer_source": "user (pagina di review)",
            "decision_ref": new_id,
            "closed_note": (
                "Chiusa dall'utente dalla pagina di review. La decisione vive in "
                f"decisions.yaml#{new_id}: le corsie la leggono da li', e chi deve applicarla la "
                "applica come atto, non come interpretazione."
            ),
        }
        requests = [
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.user_decisions,
                "anchor": f"- id: {decision_id}",
                "field": field,
                "text": value,
            }
            for field, value in fields.items()
        ]
        requests.append(
            {
                "schema": apply_transitions.SCHEMA,
                "file": self.workspace.decisions,
                "anchor": self.last_decision_anchor(),
                "item": {
                    "id": new_id,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "user_decision_id": decision_id,
                    "status": "confirmed",
                    "source_user_message": label or answer_text[:80],
                    "user_answer_registered_at": now,
                    "statement": answer_text,
                    "further_questions": [],
                },
                "position": "after",
            }
        )

        applied, failed = [], []
        with open(self.lock_path, "a+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            for index, request in enumerate(requests):
                try:
                    apply_transitions.apply_request(
                        request,
                        pack=self.pack,
                        validate_after=index == len(requests) - 1,
                    )
                    applied.append(f"{request['file']}#{request.get('field') or new_id}")
                except apply_transitions.TransitionError as error:
                    failed.append(str(error))
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        if failed:
            raise apply_transitions.TransitionError("; ".join(failed))

        view = ROOT / "registers" / "static_view.py"
        if view.exists():
            subprocess.run(
                [sys.executable, str(view), "--workspace", str(self.pack)],
                cwd=str(self.pack),
                check=False,
            )
        return {"decision_id": new_id, "applied": applied}

    def last_decision_anchor(self):
        decisions = self._load(self.workspace.decisions) or {}
        ids = [
            str(d.get("id"))
            for d in decisions.get("decisions") or []
            if str(d.get("id", "")).startswith("D")
        ]
        if not ids:
            raise apply_transitions.TransitionError("nessuna decisione in decisions.yaml")
        return f"- id: {ids[-1]}"

    # -------------------------------------------------------- ordini di lavoro
    def dispatch_draft(self, task_id, note=None):
        """Deposita in dispatch-queue/ un ordine di lavoro per RILANCIARE una fase respinta.

        Non esegue nulla e non tocca i registri: scrive un file autosufficiente in una coda che
        vive su disco, perche' il canale dei messaggi oggi perde i mandati (24 consegne a vuoto su
        24 il 2026-10-14). Chi raccoglie l'ordine trova dentro: fase, esito che l'ha respinta,
        revisione congelata del report, cosa blocca e che cosa va corretto.
        """
        state = self._load(self.workspace.state) or {}
        registered = (state.get("tasks") or {}).get(task_id)
        if registered is None:
            raise apply_transitions.TransitionError(f"fase sconosciuta: {task_id}")
        status = registered.get("status")
        if status not in ("needs_changes", "failed"):
            # Caso frequente e non un errore dell'utente: la pagina e' un'istantanea, il registro
            # e' vivo, e qualcuno puo' aver accettato la fase mentre la guardavi.
            raise NotStalledError(task_id, status)
        report = registered.get("report")
        frozen = None
        if report:
            path = self.pack / report
            if path.exists():
                import hashlib

                frozen = hashlib.sha256(path.read_bytes()).hexdigest()
        queue = self.pack / "dispatch-queue"
        queue.mkdir(parents=True, exist_ok=True)
        # Un ordine APERTO per fase, non uno per minuto: il nome porta il timestamp, quindi
        # clic in minuti diversi creavano file diversi per la stessa fase (misurato: tre ordini
        # UPL04ZE in quattro minuti). Il controllo e' sulla fase, non sul nome.
        open_orders = []
        for existing in sorted(queue.glob("*.yaml")):
            try:
                data = _carica(existing.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if (
                data.get("task_id") == task_id
                and not data.get("fulfilled_status")
                and not data.get("superseded_by")
            ):
                open_orders.append(existing.name)
        if open_orders:
            raise apply_transitions.TransitionError(
                f"esiste gia' un ordine aperto per {task_id}: {', '.join(open_orders)}. "
                f"Non ne deposito un secondo: un ordine per fase, finche' quello non e' chiuso."
            )
        stamp = datetime.now().strftime("%Y-%m-%dT%H%M")
        target = queue / f"{stamp}-{task_id}-relaunch.yaml"
        if target.exists():
            raise apply_transitions.TransitionError(f"{target.name} esiste gia': non lo sovrascrivo")
        payload = {
            "schema": "binche.ux-dispatch-order/1.0",
            "task_id": task_id,
            "requested_by": "pagina di verifica (utente)",
            "requested_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
            "why": "fase respinta in verifica: va ripresa con il mandato corretto",
            "previous_attempt": registered.get("attempt"),
            "previous_status": status,
            "report": report,
            "report_sha256": frozen,
            "blocked_units": None,
            "what_to_fix": self._stall_reason(task_id, registered.get("report")),
            "user_note": note,
            "acceptance": "il nuovo tentativo si misura sugli stessi casi che l'hanno respinta",
        }
        for block in self.snapshot()["blocks"]:
            for unit in block["units"]:
                if unit["id"] == self.unit_of(task_id):
                    payload["blocked_units"] = unit.get("blocked")
                    if unit.get("incoherent_with"):
                        # L'ordine non deve mentire come il registro: se la fase e' respinta
                        # mentre l'unita' risulta accettata, chi lo raccoglie lo deve sapere.
                        payload["warning_unit_already_accepted_by"] = unit["incoherent_with"]
        target.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {"file": str(target.relative_to(self.pack)), "task_id": task_id}

    @staticmethod
    def unit_of(task_id):
        """AUTO03T -> AUTO03. La fase e' l'ultimo carattere, quando e' A/E/T/R."""
        return task_id[:-1] if task_id[-1:] in ("A", "E", "T", "R") else task_id

    def _report_age(self, report_path, task_id):
        """Da quanto tempo quel report e' fermo: una fase respinta da giorni su un'unita' che
        intanto e' stata accettata e' un residuo di registro, non un lavoro da riprendere."""
        # Il prefisso delle consegne lo dichiara il workspace: `reports/` e' solo il predefinito.
        for candidate in (
            report_path,
            f"{self.workspace.deliverable_prefix}{task_id}/attempt-1.yaml",
        ):
            if not candidate:
                continue
            path = self.pack / candidate
            if not path.exists():
                continue
            seconds = max(0.0, datetime.now().timestamp() - path.stat().st_mtime)
            minutes = int(seconds // 60)
            if minutes < 60:
                return f"{minutes} min fa" if minutes else "adesso"
            hours = minutes // 60
            if hours < 24:
                return f"{hours} h fa"
            return f"{hours // 24} g fa"
        return None

    def _decision_context(self, decision_ref):
        """Il contesto registrato sulla decisione, se c'e': e' cio' che rende leggibile un
        'Si' fra un mese."""
        if not decision_ref:
            return None
        decisions = self._load(self.workspace.decisions) or {}
        for decision in decisions.get("decisions") or []:
            if decision.get("id") == decision_ref:
                return decision.get("statement_context")
        return None

    # ------------------------------------------------------- la domanda, in parole povere
    def _tocca(self, testi, state, tasks_doc):
        """I codici che una domanda nomina, ciascuno col suo stato MISURATO.

        Perche' esiste. Una domanda che chiede di scegliere parla di cose che hanno un nome nel
        registro — `UPL04ZR`, `NAV03R` — e chi risponde ha il diritto di sapere in che stato sono
        PRIMA di scegliere. Il 2026-10-15 l'utente ha risposto a una domanda sulle ratifiche senza
        che nulla gli dicesse che quella risposta le avrebbe lasciate respinte per sempre, e la
        misura era li': dieci atti respinti per la stessa ragione, un agente solo in tutto l'albero.
        Il testo della domanda non si riscrive e non si riassume — quello lo scrive chi la pone —
        ma i numeri li mette la piattaforma, perche' quelli sono suoi.
        """
        registrate = state.get("tasks") or {}
        noti = {str(t.get("id")) for t in tasks_doc.get("tasks") or [] if t.get("id")}
        testo = " ".join(str(t or "") for t in testi)
        parole = set(re.findall(r"[A-Z][A-Z0-9]{2,}", testo))
        nominati = sorted(noti & parole)
        if not nominati:
            return []
        misure = rework.per_fase(self.workspace, nominati) if nominati else {}
        fuori = []
        for codice in nominati[:6]:
            misura = misure.get(codice) or {}
            ostacolo = (misura.get("ricorrenti") or [{}])[0]
            fuori.append(
                {
                    "code": codice,
                    "status": (registrate.get(codice) or {}).get("status", "pending"),
                    "tentativi": misura.get("tentativi", 0),
                    "respinte": misura.get("respinte", 0),
                    "ostacolo": ostacolo.get("id") or "",
                    "bloccante": bool(ostacolo.get("bloccante")),
                    "chi": ostacolo.get("chi") or "",
                }
            )
        return fuori

    def _firme(self, state):
        """Chi firma nel registro, e quante volte: la misura che decide le domande sull'indipendenza.

        La domanda `UD-5` chiedeva se fornire una firma distinta da `/root` o accettare il debito; la
        risposta e' stata «si fornisce una firma distinta», ma nel registro le firme restano una
        sola, e le quattro ratifiche sono ancora li'. Questo conto, accanto alla domanda, l'avrebbe
        detto subito: si legge dai campi di presa, non si deduce.
        """
        # Una firma e' un IDENTIFICATORE, non una frase: `taken_by` porta spesso prosa
        # («da assegnare alla prima slot libera», «NESSUNO — voce pre-registrata»), e contarli come
        # firme gonfiava il numero a 11 su un registro dove le identita' sono due. Misurato oggi.
        conta = {}
        for voce in state.get("active_claims") or []:
            chi = str(voce.get("taken_by") or "").strip()
            if not chi[:1].isalnum() and not chi.startswith("/"):
                continue
            if " " in chi:
                continue
            canonico = "/".join(chi.split("/")[:2]) if chi.startswith("/") else chi.split("(")[0].strip()
            if not canonico:
                continue
            conta[canonico] = conta.get(canonico, 0) + 1
        elenco = sorted(conta.items(), key=lambda coppia: -coppia[1])
        return {
            "distinte": len(elenco),
            "elenco": [{"chi": chi, "prese": n} for chi, n in elenco[:6]],
        }

    @staticmethod
    def _opzioni(valore):
        """Le alternative di una domanda o di una decisione, sempre come `label` + `description`.

        Sul progetto di origine convivono due forme — la stringa secca e il dizionario con la
        spiegazione — e la pagina le trattava come stringhe: un dizionario finiva a schermo come
        «[object Object]», e la spiegazione, che e' la parte che serve a decidere, spariva.
        """
        fuori = []
        for voce in valore or []:
            if isinstance(voce, dict):
                fuori.append(
                    {
                        "label": str(voce.get("label") or voce.get("answer") or "").strip(),
                        "description": str(
                            voce.get("description") or voce.get("consequence") or voce.get("what") or ""
                        ).strip(),
                    }
                )
            else:
                fuori.append({"label": str(voce).strip(), "description": ""})
        return [voce for voce in fuori if voce["label"]]


def build_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silenzio: il log e' la pagina, non la console
            return

        def _send(self, status, body, content_type, no_store=False):
            payload = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if no_store:
                # La pagina cambia mentre la si guarda: il browser non deve tenere la copia vecchia
                # di app.js e mostrare pulsanti che nel file non ci sono piu'.
                self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status, data):
            # default=str: i registri portano date YAML (answered_on, asked_on) che json rifiuta.
            self._send(status, json.dumps(data, default=str), "application/json; charset=utf-8")

        def do_GET(self):
            parsed = urlparse(self.path)
            route = parsed.path
            if route in ("/", "/index.html"):
                return self._send(200, (UI_DIR / "index.html").read_text("utf-8"), "text/html; charset=utf-8", no_store=True)
            if route == "/app.js":
                return self._send(200, (UI_DIR / "app.js").read_text("utf-8"), "application/javascript; charset=utf-8", no_store=True)
            if route == "/style.css":
                return self._send(200, (UI_DIR / "style.css").read_text("utf-8"), "text/css; charset=utf-8", no_store=True)
            if route == "/config.json":
                # L'interfaccia non sa niente del progetto: nome, vista e fasi arrivano da qui, e
                # il workspace li dichiara. Un progetto nuovo non tocca una riga di HTML.
                return self._json(200, {
                    "project": state.workspace.project,
                    "surface": state.workspace.surface,
                    "phases": list(state.workspace.phases),
                })
            if route == "/api/state":
                try:
                    return self._json(200, state.snapshot())
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
            if route == "/api/versione":
                # Due `stat`: la pagina lo chiede spesso e non deve costare una rilettura.
                try:
                    return self._json(200, state.versione())
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
            if route == "/api/timeline":
                # Endpoint a parte: la linea del tempo legge ~280 puntatori e interroga git, e la
                # pagina non deve aspettare tutto questo per mostrare le domande e i prompt.
                try:
                    return self._json(200, state.timeline_payload())
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
            if route == "/api/prompt":
                # Il prompt di UNA fase, a richiesta: dal quaderno se c'e', altrimenti composto dal
                # registro. Non sta nel carico generale perche' sono migliaia di caratteri per fase.
                target = (parse_qs(parsed.query).get("target") or [""])[0]
                if not target:
                    return self._json(400, {"error": "serve target: la fase del prompt"})
                try:
                    esito = mandate.per(
                        state.workspace,
                        target,
                        # `state` e' il ReviewState, non l'handler: `_load` sta su di lui.
                        state=state._load(state.workspace.state),
                    )
                    # Un ordine depositato porta un prompt CONGELATO: si mostra QUELLO, perche' e' il
                    # testo consegnato a un esecutore e non deve cambiare sotto. Se il ricomposto
                    # adesso e' diverso, lo si dichiara invece di sostituirlo in silenzio.
                    congelato = mandate.da_ordine(state.workspace, target)
                    # Ma un ordine che punta a un attempt gia' su disco non e' il prompt di un
                    # NUOVO atto: mostrarlo manderebbe a scrivere sopra una consegna (HIST02A,
                    # 2026-10-17: ordine dell'attempt 1, attempt-1 esistente).
                    if congelato and mandate.consegna_gia_scritta(
                        state.workspace, target, congelato["text"]
                    ):
                        congelato = None
                    if congelato:
                        # Il corpo congelato è quello consegnato, ma non deve perdere il testimone:
                        # senza, END03E non sapeva dei tre bloccanti di END03A (misurato il 2026-10-18).
                        aggiunta = mandate.testimone(
                            state.workspace, target, state._load(state.workspace.state)
                        )
                        corpo = congelato["text"] + (
                            "\n\n" + aggiunta.strip() if aggiunta else ""
                        )
                        esito = {
                            **esito,
                            # La busta si mette anche davanti al corpo congelato: un ordine nato
                            # prima della busta non deve arrivare all'esecutore senza la
                            # dichiarazione del lavoro.
                            "text": mandate.con_busta(state.workspace, target, corpo),
                            "source": f"ordine {congelato['file']} (corpo congelato)",
                            "order": congelato["file"],
                            "order_prompt_sha256": congelato["sha256"],
                            # Il confronto e' fra CORPI: la busta cambia quando cambia, il mandato no.
                            "diverges_from_registry": congelato["sha256"]
                            != mandate.impronta(mandate.senza_busta(esito["text"])),
                        }
                    return self._json(200, {"phase": target, **esito})
                except Exception as error:  # noqa: BLE001
                    return self._json(400, {"error": str(error)})
            if route == "/api/esiti":
                # Gli esiti di UNA fase, a richiesta: leggere tutti i report a ogni giro
                # costerebbe centinaia di file per un elenco che si apre solo quando serve.
                target = (parse_qs(parsed.query).get("phase") or [""])[0].strip()
                if not target:
                    return self._json(400, {"error": "serve phase: la fase di cui leggere gli esiti"})
                try:
                    tasks_doc = state._load(state.workspace.tasks) or {}
                    nota = any(
                        str(task.get("id")) == target for task in tasks_doc.get("tasks") or []
                    )
                    if not nota:
                        return self._json(404, {"error": f"fase sconosciuta: {target}"})
                    percorso, _, _, documento = handoff.ultimo_report(
                        state.workspace, state._load(state.workspace.state) or {}, target
                    )
                    if not documento:
                        return self._json(404, {"error": f"nessun report pubblicato per {target}"})
                    relativo = str(percorso.relative_to(state.workspace.root)) if percorso else ""
                    return self._json(200, esiti.estrai(documento, relativo))
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
            if route == "/file":
                wanted = (parse_qs(parsed.query).get("path") or [""])[0]
                target = (state.pack / wanted).resolve()
                if not str(target).startswith(str(state.pack.resolve())) or not target.is_file():
                    return self._send(404, "non trovato", "text/plain; charset=utf-8")
                return self._send(200, target.read_text("utf-8", errors="replace"), "text/plain; charset=utf-8")
            if route == "/logo":
                # La casella del logo nell'header. Ordine: il file del WORKSPACE (il suo `brand/`)
                # vince sempre; poi il marchio di serie del coordinatore; senza nemmeno quello si
                # risponde 404 e la pagina mostra un monogramma col nome del progetto. Sola
                # lettura, e confinata alle due cartelle del marchio.
                variant = (parse_qs(parsed.query).get("variant") or ["light"])[0]
                scuro = variant == "dark"
                nomi = (
                    ["logo-dark.svg", "logo-dark.png", "logo.svg", "logo.png"]
                    if scuro
                    else ["logo.svg", "logo.png"]
                )
                for cartella, elenco in (
                    (state.workspace.brand_dir, nomi),
                    (CONSOLE_BRAND, ["logo-dark.png", "logo.png"] if scuro else ["logo.png"]),
                ):
                    base = cartella.resolve()
                    for name in elenco:
                        target = (base / name).resolve()
                        if not str(target).startswith(str(base)) or not target.is_file():
                            continue
                        kind = "image/svg+xml" if target.suffix == ".svg" else "image/png"
                        return self._send(200, target.read_bytes(), kind)
                return self._send(404, "nessun logo", "text/plain; charset=utf-8")
            # Le pagine del coordinatore: `/`, `/tempo`, `/testimone`, `/prompt`, `/percorso` sono la
            # stessa interfaccia, che disegna la pagina chiesta dal percorso. Un percorso sconosciuto
            # che non e' ne' un'API ne' un file torna alla coda, invece di dare un 404.
            return self._send(
                200, (UI_DIR / "index.html").read_text("utf-8"), "text/html; charset=utf-8"
            )

        def do_POST(self):
            route = urlparse(self.path).path
            if route == "/api/accept":
                # «Dove accolgo i cambiamenti»: qui. Scrive un ATTO di accettazione firmato `utente`
                # (una mano che quei byte non li ha scritti), col cancello davanti: se la base non e'
                # pronta, non firma e dice perche'.
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as error:
                    return self._json(400, {"error": f"JSON non valido: {error}"})
                fase = str(payload.get("phase") or "").strip()
                if not fase:
                    return self._json(400, {"error": "serve phase"})
                try:
                    esito = accetta.per(state.workspace, fase, payload.get("nota"))
                except ValueError as error:
                    return self._json(409, {"error": str(error)})
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
                return self._json(200, {"ok": True, **esito})
            if route == "/api/coda/apply":
                # Il pulsante che fa il lavoro: la coda si applica in un PROCESSO A PARTE. Perche' non
                # in un thread: misurato il 2026-10-16, un'applicazione da 90 richieste su un server a
                # un processo solo (con tre browser che interrogavano la pagina) ha portato la CPU al
                # 97% e l'API a non rispondere piu'. Un figlio si puo' uccidere; un server no.
                if state.applicazione.get("in_corso"):
                    return self._json(409, {"error": "una applicazione e' gia' in corso"})
                import threading

                registro = Path("/tmp/console-coda.log")
                def sorveglia(processo):
                    processo.wait()
                    righe = []
                    try:
                        righe = registro.read_text("utf-8", errors="replace").strip().splitlines()
                    except OSError:
                        pass
                    esito = next((r for r in reversed(righe) if "applicate" in r), "")
                    state.applicazione = {
                        "in_corso": False,
                        "esito": esito or f"finito (uscita {processo.returncode})",
                        "quando": datetime.now().strftime("%H:%M:%S"),
                        "rifiutate": [r.strip() for r in righe if "rifiutata" in r][:8],
                        "copie": [r.split("copie:", 1)[1].strip() for r in righe if r.startswith("copie:")][:1],
                    }
                state.applicazione = {"in_corso": True, "esito": "", "quando": "", "fatte": 0, "totali": 0}
                with open(registro, "w", encoding="utf-8") as uscita:
                    processo = subprocess.Popen(
                        [
                            sys.executable,
                            str(ROOT / "registers" / "coda.py"),
                            "--workspace",
                            str(state.workspace.root),
                            "--applica",
                        ],
                        stdout=uscita,
                        stderr=subprocess.STDOUT,
                        cwd=str(state.workspace.root),
                    )
                threading.Thread(target=sorveglia, args=(processo,), daemon=True).start()
                return self._json(200, {"ok": True, "avviata": True})
            if route == "/api/inbox":
                # Depositare un messaggio nella posta: e' l'unica scrittura della pagina che non
                # passa dai registri, e per questo non puo' rompere niente. Il testo si salva
                # intero — la pagina non lo riassume e non lo interpreta.
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as error:
                    return self._json(400, {"error": f"JSON non valido: {error}"})
                testo = str(payload.get("text") or "")
                if not testo.strip():
                    return self._json(400, {"error": "serve text: il messaggio da depositare"})
                try:
                    esito = inbox.archivia(
                        state.workspace,
                        testo,
                        phase=str(payload.get("phase") or "").strip(),
                        unit=str(payload.get("unit") or "").strip(),
                        sender=str(payload.get("sender") or "").strip(),
                        kind=str(payload.get("kind") or "").strip() or None,
                    )
                except ValueError as error:
                    return self._json(400, {"error": str(error)})
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
                return self._json(200, {"ok": True, **esito})
            if route == "/api/dispatch-draft":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as error:
                    return self._json(400, {"error": f"JSON non valido: {error}"})
                task_id = str(payload.get("task_id") or "")
                if not task_id:
                    return self._json(400, {"error": "serve task_id"})
                try:
                    result = state.dispatch_draft(task_id, payload.get("note"))
                except NotStalledError as error:
                    return self._json(
                        409,
                        {
                            "error": str(error),
                            "code": "not_stalled",
                            "task_id": error.task_id,
                            "current_status": error.current_status,
                        },
                    )
                except apply_transitions.TransitionError as error:
                    return self._json(409, {"error": str(error)})
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
                return self._json(200, {"ok": True, **result})
            if route == "/api/activate":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as error:
                    return self._json(400, {"error": f"JSON non valido: {error}"})
                target = str(payload.get("target") or "").strip()
                azione = str(payload.get("action") or "activate")
                if not target:
                    return self._json(400, {"error": "serve target: la fase da attivare o rilasciare"})
                try:
                    esito = (
                        activate.rilascia(state.workspace, target)
                        if azione == "release"
                        else activate.attiva(state.workspace, target)
                    )
                except apply_transitions.TransitionError as error:
                    return self._json(409, {"error": str(error)})
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
                return self._json(200, {"ok": True, "action": azione, "target": target, **esito})
            if route == "/api/handoff":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as error:
                    return self._json(400, {"error": f"JSON non valido: {error}"})
                target = str(payload.get("target") or "").strip()
                testo = str(payload.get("note") or "").strip()
                if not target or not testo:
                    return self._json(400, {"error": "servono target e note: quale fase, e cosa fare dopo"})
                try:
                    esito = handoff.scrivi(state.workspace, target, testo)
                except apply_transitions.TransitionError as error:
                    return self._json(409, {"error": str(error)})
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
                return self._json(200, {"ok": True, **esito})
            if route == "/api/decision":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as error:
                    return self._json(400, {"error": f"JSON non valido: {error}"})
                decision_id = str(payload.get("decision_id") or "")
                answer_text = str(payload.get("answer") or "").strip()
                if not decision_id or not answer_text:
                    return self._json(400, {"error": "servono decision_id e answer"})
                try:
                    result = state.decision(decision_id, answer_text, payload.get("label"))
                except apply_transitions.TransitionError as error:
                    return self._json(409, {"error": str(error)})
                except Exception as error:  # noqa: BLE001
                    return self._json(500, {"error": str(error)})
                return self._json(200, {"ok": True, **result})
            if route != "/api/answer":
                return self._json(404, {"error": "rotta sconosciuta"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as error:
                return self._json(400, {"error": f"JSON non valido: {error}"})
            question_id = str(payload.get("question_id") or "")
            answer_text = str(payload.get("answer") or "").strip()
            label = payload.get("label")
            if not question_id or not answer_text:
                return self._json(400, {"error": "servono question_id e answer"})
            try:
                result = state.answer(question_id, answer_text, label)
            except apply_transitions.TransitionError as error:
                return self._json(409, {"error": str(error)})
            except Exception as error:  # noqa: BLE001
                return self._json(500, {"error": str(error)})
            return self._json(200, {"ok": True, **result})

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--workspace",
        "--pack-root",  # nome storico: lo usano le corsie dei progetti gia' avviati
        dest="workspace",
        help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)",
    )
    args = parser.parse_args(argv)
    workspace = Workspace.load(args.workspace)
    missing = workspace.writable_check()
    state = ReviewState(workspace)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(state))
    print(f"coordinatore su http://{args.host}:{args.port}")
    print(f"workspace: {workspace.describe()}")
    if missing:
        # Un workspace incompleto si dice all'avvio, non si scopre rompendo una pagina.
        print(f"ATTENZIONE: manca {', '.join(missing)} — la pagina mostrera' vuoti, non errori finti.")
    print("Ctrl-C per fermare. Nessuna scrittura fuori dal workspace; le risposte passano dal lock.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nfermato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
