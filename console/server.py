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
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent / "ui"
CONSOLE_BRAND = Path(__file__).resolve().parent / "brand"
#: Il codice del coordinatore (questo repo) e quello dei registri (il workspace) sono due cose:
#: il primo si importa da qui, il secondo non si importa affatto — si legge.
sys.path[:0] = [str(ROOT), str(ROOT / "registers"), str(Path(__file__).resolve().parent)]
sys.path.insert(0, str(ROOT))

import apply_transitions  # noqa: E402
import activate  # noqa: E402 - attivare: riserva la fase e deposita l'ordine
import handoff  # noqa: E402 - cosa c'e' da fare dopo: il testimone lasciato da chi ha finito
import mandate  # noqa: E402 - il prompt di una fase: dal quaderno, o composto dal registro
import next_prompts  # noqa: E402 - una sola implementazione della regola, condivisa con STATUS.html
import timeline  # noqa: E402 - la linea del tempo, con le date dichiarate dagli artefatti
from workspace import Workspace  # noqa: E402 - il contratto dei nomi: qui non c'e' nessun progetto

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
        #: Il lock e' per PROGETTO e il nome si deriva dal percorso con un digest STABILE: `hash()`
        #: cambia a ogni processo (sale casuale), quindi due processi non si vedrebbero.
        self.lock_path = os.environ.get(
            "CONSOLE_REGISTRY_LOCK",
            "/tmp/project-console-"
            + hashlib.sha1(str(self.pack).encode("utf-8")).hexdigest()[:12]
            + ".lock",
        )
        self._queue()

    # ------------------------------------------------------------------ lettura
    def _load(self, name):
        path = self.pack / name
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None

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
                phases.append(
                    {
                        "id": task_id,
                        "suffix": task_id[len(unit_id) :],
                        "kind": PHASE_KIND.get(task.get("kind"), task.get("kind")),
                        "title": task.get("title"),
                        "status": registered.get("status", "pending"),
                        "attempt": registered.get("attempt", 0),
                        "report": registered.get("report"),
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

        open_questions = [
            {
                "id": q.get("id"),
                "topic": q.get("topic"),
                "question": q.get("question"),
                "why": q.get("why_unresolved"),
                "options": q.get("suggested_answers") or [],
                "asked_on": q.get("asked_on"),
                "blocks": q.get("affected_tasks") or [],
            }
            for q in (questions.get("questions") or [])
            if q.get("status") == "asked"
        ]
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
        open_decisions = [
            {
                "id": item.get("id"),
                "topic": item.get("topic"),
                "question": item.get("question"),
                "evidence": item.get("evidence"),
                "why": item.get("why_yours"),
                # Se la voce dichiara le alternative, la pagina le offre come scelte; se non le
                # dichiara, si scrive la decisione con parole proprie. Nessuna opzione inventata
                # dal testo della domanda: dedurle dalla prosa sarebbe attribuire all'utente
                # alternative che nessuno ha scritto.
                "options": item.get("options") or [],
            }
            for item in decisions_doc.get("decisions") or []
            if item.get("status") != "closed"
        ]
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
        return {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
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
            "activatable": activate.attivabili(self.workspace, state, tasks_doc),
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
            "activated": [
                {
                    "phase": fase,
                    "owner": (voce.get("owner") or voce.get("owner_agent") or voce.get("taken_by") or ""),
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
                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
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
        with open(self.lock_path, "a+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
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
                data = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
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
        for candidate in (report_path, f"reports/{task_id}/attempt-1.yaml"):
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


def build_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silenzio: il log e' la pagina, non la console
            return

        def _send(self, status, body, content_type):
            payload = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status, data):
            # default=str: i registri portano date YAML (answered_on, asked_on) che json rifiuta.
            self._send(status, json.dumps(data, default=str), "application/json; charset=utf-8")

        def do_GET(self):
            parsed = urlparse(self.path)
            route = parsed.path
            if route in ("/", "/index.html"):
                return self._send(200, (UI_DIR / "index.html").read_text("utf-8"), "text/html; charset=utf-8")
            if route == "/app.js":
                return self._send(200, (UI_DIR / "app.js").read_text("utf-8"), "application/javascript; charset=utf-8")
            if route == "/style.css":
                return self._send(200, (UI_DIR / "style.css").read_text("utf-8"), "text/css; charset=utf-8")
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
                    return self._json(200, {"phase": target, **mandate.per(state.workspace, target)})
                except Exception as error:  # noqa: BLE001
                    return self._json(400, {"error": str(error)})
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
            return self._send(404, "non trovato", "text/plain; charset=utf-8")

        def do_POST(self):
            route = urlparse(self.path).path
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
