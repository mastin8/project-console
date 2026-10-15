#!/usr/bin/env python3
"""La linea del tempo del pack: blocchi -> unita' -> fasi, con le date che gli artefatti DICHIARANO.

Perche' esiste: l'utente ha chiesto di vedere il percorso nel tempo, con i livelli apribili, prima
dell'elenco dei blocchi. Un grafico a barre si puo' disegnare in due modi: da un piano inventato o
da cio' che e' successo. Qui vale il secondo, e la differenza si dichiara a schermo:

  * se il puntatore del report porta `published_at`, quella e' la data DICHIARATA dall'artefatto;
  * altrimenti vale l'mtime del puntatore, che e' una misura del disco e viene mostrata come tale;
  * se non c'e' nemmeno il puntatore, la fase resta senza data e si conta, non si stima.

Nessuna barra e' quindi una previsione: una riga lunga vuol dire «questa unita' si e' mossa fra
questi due giorni», non «dovrebbe durare tanto».

L'asse e' a giorni: il pack ha nove giorni di storia e le singole fasi durano minuti, quindi la
risoluzione utile e' il giorno, non l'ora.

Sola lettura. Uso::

    python3 docs/ux-context-pack/review/timeline.py          # tabella di controllo
    python3 docs/ux-context-pack/review/timeline.py --json   # il carico che serve alla pagina
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import yaml


def _carica(flusso):
    """Legge un registro col parser veloce quando c'e' (libyaml): 17 volte piu' rapido su un
    registro da 2 MB (misurato: 0,09 s contro 1,55 s). Stesso sottoinsieme sicuro di YAML, nessun
    costruttore custom: e' `safe_load` scritto in C, non un'altra sintassi."""
    return yaml.load(flusso, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "registers")]

from workspace import Workspace  # noqa: E402 - i nomi li dichiara il workspace

PACK_DEFAULT = Path(os.environ.get("CONSOLE_WORKSPACE") or Path.cwd()).expanduser().resolve()

import next_prompts  # noqa: E402 - i prompt del quaderno, con lo stato gia' risolto

#: Il workspace in uso. Chi importa questo modulo lo dichiara con `configure()`; il valore di
#: partenza e' dedotto dall'ambiente, cosi' anche un uso diretto da riga di comando funziona.
WS = Workspace(root=PACK_DEFAULT)


def configure(workspace):
    """Il progetto di cui si sta parlando: nomi, quaderno e prefisso delle consegne."""
    global WS, PACK_DEFAULT
    WS = workspace
    PACK_DEFAULT = workspace.root
    next_prompts.configure(
        queue=workspace.queue, deliverable_prefix=workspace.deliverable_prefix
    )

PHASES = ("A", "E", "T", "R")
DONE = ("accepted",)
STALLED = ("needs_changes", "failed")
LIVE = ("active", "taken", "pre_registered", "ready", "active_extension")

#: `published_at` e' un campo di primo livello di un puntatore piccolo: si legge con una scansione,
#: non con un parse YAML. Misurato il 2026-10-15 su 236 puntatori: 277 ms col parse, 15 ms cosi'.
_PUBLISHED = re.compile(r"^published_at:\s*'?([^'\n]+?)'?\s*$", re.M)

#: Separatori di record/campo per leggere `git log` in una passata sola.
_RECORD, _FIELD = "\x1e", "\x1f"

STATE_LABEL = {
    "accettata": "accettata",
    "respinta": "respinta in verifica",
    "in_corso": "in corso",
    "da_fare": "da fare",
}


def repository_facts(pack):
    """Cosa dice il versionamento, misurato: i commit, e quanto lavoro NON e' in nessun commit.

    Serve a non raccontare una storia che non c'e': il 2026-10-15 il repository aveva 8 commit e
    l'ultimo era del 2025-07-24, mentre tutto il lavoro del pack (e l'applicazione) stava in
    albero senza essere tracciato. Un grafico con la riga dei commit vuota e' la verita'; la riga
    dei commit con sopra dei numeri inventati no.
    """
    root = pack

    def run(*args):
        try:
            done = subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as error:  # git assente o appeso
            return None, str(error)
        if done.returncode != 0:
            return None, (done.stderr or "").strip() or f"git rc={done.returncode}"
        return done.stdout, None

    # Il repository e' quello che CONTIENE il workspace, anche quando il workspace e' una
    # sottocartella di un progetto piu' grande: lo dice git, non una regola sui percorsi.
    top, _ = run("rev-parse", "--show-toplevel")
    if not (top or "").strip():
        return {"available": False, "reason": f"nessun repository git intorno a {root}"}
    repo = Path(top.strip())

    log, error = run(
        "log",
        f"--pretty=format:{_RECORD}%H{_FIELD}%ad{_FIELD}%s",
        "--date=iso-strict",
        "--name-only",
    )
    if log is None:
        return {"available": False, "reason": error or "git log non leggibile"}
    commits = []
    for record in log.split(_RECORD):
        lines = [line for line in record.split("\n") if line.strip()]
        if not lines:
            continue
        parts = lines[0].split(_FIELD)
        if len(parts) < 3:
            continue
        files = [line for line in lines[1:] if not line.startswith(" ")]
        commits.append(
            {
                "sha": parts[0][:7],
                "date": parts[1],
                "day": parts[1][:10],
                "subject": parts[2],
                "files": len(files),
                "paths": files[:40],
            }
        )
    status, status_error = run("status", "--porcelain", "--untracked-files=all")
    modified = untracked = 0
    if status is not None:
        for line in status.splitlines():
            if line.startswith("??"):
                untracked += 1
            elif line.strip():
                modified += 1
    # Quanti file DEL WORKSPACE sono tracciati: e' la domanda che conta («questo lavoro e' dentro
    # un commit?»), non quanti ne ha il repository intero.
    tracked_pack, _ = run("ls-files", ".")
    return {
        "available": True,
        "root": str(root),
        "repository": str(repo),
        "total": len(commits),
        "list": commits,
        "last": commits[0] if commits else None,
        "modified": modified,
        "untracked": untracked,
        "tracked_pack_files": len((tracked_pack or "").splitlines()),
        "status_error": status_error,
    }


def parse_moment(raw):
    """Una data dichiarata. `None` se non e' leggibile: non si inventa un giorno."""
    text = str(raw or "").strip().strip("'\"")
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def local_date(moment):
    if moment is None:
        return None
    return moment.astimezone().date() if moment.tzinfo else moment.date()


def phase_moment(pack, task_id, report_path, reports_dir=None):
    """(giorno, orario, come lo so) per una fase. Il puntatore e' la fonte piu' vicina."""
    pointer = (reports_dir or (pack / "reports")) / f"{task_id}.yaml"
    if pointer.exists():
        try:
            text = pointer.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        declared = _PUBLISHED.search(text)
        if declared:
            moment = parse_moment(declared.group(1))
            if moment:
                return local_date(moment), moment, "dichiarata"
            return local_date(datetime.fromtimestamp(pointer.stat().st_mtime)), None, "dichiarata_illeggibile"
        return (
            local_date(datetime.fromtimestamp(pointer.stat().st_mtime)),
            None,
            "mtime",
        )
    target = pack / report_path if report_path else None
    if target and target.exists():
        return local_date(datetime.fromtimestamp(target.stat().st_mtime)), None, "mtime"
    return None, None, "senza_data"


def _live_claims(state):
    out = {}
    for claim in state.get("active_claims") or []:
        task_id = claim.get("task_id")
        if not task_id:
            continue
        if claim.get("status") in LIVE and not claim.get("released_at"):
            out[str(task_id)] = claim
    return out


def _open_obligations(state):
    out = []
    for item in state.get("execution_attempts") or []:
        if not item.get("obligation_id"):
            continue
        if item.get("status") == "closed" or item.get("closure_kind"):
            continue
        out.append(
            {
                "id": str(item["obligation_id"]),
                "owner": next_prompts.shorten(item.get("owner"), 90),
                "required_before": item.get("required_before"),
                "what": next_prompts.shorten(item.get("what"), 160),
            }
        )
    return out


def _open_questions(questions_doc):
    return [
        {
            "id": q.get("id"),
            "topic": q.get("topic"),
            "question": next_prompts.shorten(q.get("question"), 160),
            "blocks": q.get("affected_tasks") or [],
        }
        for q in (questions_doc or {}).get("questions") or []
        if q.get("status") == "asked"
    ]


def declared_paths_by_unit(state):
    """I path di prodotto che ogni unita' dichiara, dalle voci di claim del registro.

    Serve a una cosa sola: dire se un commit tocca il lavoro di un blocco. Il confronto e' esatto
    (path normalizzato, senza il prefisso del pack): niente somiglianze, perche' un'attribuzione
    approssimata qui sarebbe un'invenzione travestita da misura.
    """
    out = {}
    for collection in ("active_claims", "execution_attempts"):
        for entry in state.get(collection) or []:
            task_id = entry.get("task_id")
            if not task_id:
                continue
            paths = entry.get("exact_paths") or []
            if not isinstance(paths, list):
                continue
            bucket = out.setdefault(str(task_id), set())
            for raw in paths:
                value = str(raw).strip().strip("`").split(" (")[0].strip()
                if value.startswith("docs/ux-context-pack/"):
                    value = value[len("docs/ux-context-pack/") :]
                if value:
                    bucket.add(value)
    return out


def commits_by_block(blocks, git_facts, declared, phase_to_unit):
    """I commit che toccano i path dichiarati dalle unita' di ciascun blocco.

    Con un repository in cui l'ultimo commit precede di quindici mesi questo lavoro, il risultato
    atteso e' ZERO per ogni blocco: quella e' l'informazione, e va scritta invece di lasciare la
    riga vuota.
    """
    commits = (git_facts or {}).get("list") or []
    for block in blocks:
        per_unita = {}
        tutti = set()
        dichiarati = 0
        for unit in block["units"]:
            riferimenti = set()
            for phase in unit["phases"]:
                riferimenti |= declared.get(phase["id"], set())
            dichiarati += len(riferimenti)
            if not riferimenti:
                continue
            for commit in commits:
                toccati = set(commit.get("paths") or []) & riferimenti
                if toccati:
                    tutti.add(commit["sha"])
                    per_unita.setdefault(commit["sha"], set()).add(unit["id"])
        block["commits"] = [
            {
                "sha": sha,
                "day": next((c["day"] for c in commits if c["sha"] == sha), None),
                "subject": next((c["subject"] for c in commits if c["sha"] == sha), ""),
                "units": sorted(per_unita.get(sha, set())),
            }
            for sha in sorted(tutti)
        ]
        block["paths_declared"] = dichiarati
    return blocks


def _matching_prompts(prompt_entries, unit_id, phase_ids):
    """I prompt agganciati a questa unita'.

    La regola e' una e si legge: il codice del prompt e' una fase dell'unita' (esatto), oppure
    comincia con l'id dell'unita'. Nessuna somiglianza approssimata: `UPL04ZR` sta con `UPL04Z`,
    `LOT03-UI-HALF-UNCOVERED` sta con `LOT03`, e non serve altro.
    """
    out = []
    for entry in prompt_entries or []:
        if entry["state"] == "fatto":
            continue
        anchor = entry["anchor"] or ""
        if anchor in phase_ids or (anchor and anchor.startswith(unit_id)):
            out.append(
                {
                    "kind": "prompt",
                    "label": f"§{entry['number']} {anchor or 'senza codice'}",
                    "detail": f"{next_prompts.STATE_LABEL.get(entry['state'], entry['state'])}"
                    + (f" · {entry['notes'][0]}" if entry.get("notes") else ""),
                    "target": f"#prompt-{anchor or entry['number']}",
                    "state": entry["state"],
                }
            )
    return out


def build(pack=PACK_DEFAULT, state=None, tasks_doc=None, questions_doc=None, decisions_doc=None,
          prompt_entries=None):
    """Il carico della sezione «percorso nel tempo». Nessuna scrittura, nessuna stima."""
    pack = Path(pack)
    state = state if state is not None else (_carica((pack / WS.state).read_text(encoding="utf-8")) or {})
    tasks_doc = tasks_doc if tasks_doc is not None else (_carica((pack / WS.tasks).read_text(encoding="utf-8")) or {})
    if prompt_entries is None:
        prompt_entries = next_prompts.build(pack, state=state)
    if decisions_doc is None:
        # Le decisioni di governo stanno in un file a parte proprio perche' non sono domande di un
        # task: senza caricarle, «cio' che devo fare io» resterebbe vuoto mentre due scelte sono
        # ferme (misurato il 2026-10-15: la sezione diceva 0 decisioni con UD-1 e UD-2 aperte).
        path = pack / WS.user_decisions
        decisions_doc = (
            _carica(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
    registered = state.get("tasks") or {}
    live = _live_claims(state)
    obligations = _open_obligations(state)
    questions = _open_questions(questions_doc)
    decisions = [
        {
            "id": item.get("id"),
            "topic": item.get("topic"),
            "question": next_prompts.shorten(item.get("question"), 200),
        }
        for item in (decisions_doc or {}).get("decisions") or []
        if item.get("status") != "closed"
    ]

    phases_by_unit = {}
    for task in tasks_doc.get("tasks") or []:
        phases_by_unit.setdefault(task.get("unit_id"), []).append(task)

    units = {}
    counters = {"dichiarata": 0, "mtime": 0, "dichiarata_illeggibile": 0, "senza_data": 0}
    for unit in tasks_doc.get("units") or []:
        unit_id = unit.get("id")
        if not unit_id:
            continue
        phases = []
        for task in phases_by_unit.get(unit_id, []):
            task_id = task.get("id")
            registered_entry = registered.get(task_id) or {}
            suffix = str(task_id)[len(str(unit_id)) :] or "?"
            day, moment, kind = phase_moment(pack, task_id, registered_entry.get("report"), WS.reports_dir)
            counters[kind] = counters.get(kind, 0) + 1
            phases.append(
                {
                    "id": task_id,
                    "suffix": suffix,
                    "title": task.get("title"),
                    "status": registered_entry.get("status", "pending"),
                    "attempt": registered_entry.get("attempt", 0),
                    "report": registered_entry.get("report"),
                    "day": None,  # indice di giorno: si riempie quando l'asse e' noto
                    "at": moment.strftime("%Y-%m-%d %H:%M") if moment else None,
                    "date": day.isoformat() if day else None,
                    "dated": kind,
                }
            )
        days = [p["date"] for p in phases if p["date"]]
        units[unit_id] = {
            "id": unit_id,
            "title": unit.get("title"),
            "domain": unit.get("domain") or "senza-dominio",
            "deliverable": unit.get("deliverable"),
            "depends_on": unit.get("depends_on_units") or [],
            "accepted": bool(phases) and all(p["status"] in DONE for p in phases),
            "phases": phases,
            "first": min(days) if days else None,
            "last": max(days) if days else None,
        }

    all_days = sorted({u["first"] for u in units.values() if u["first"]} | {u["last"] for u in units.values() if u["last"]})
    git_facts = repository_facts(pack)
    # Un progetto al primo giorno non ha NESSUNA data: nessuna consegna e' ancora stata fatta. Se
    # in quel caso l'asse sparisse, la sezione in testa resterebbe vuota proprio quando serve di
    # piu' — perche' non c'e' niente da datare, non perche' non ci sia niente da vedere. Si
    # disegna un giorno solo, oggi, e le righe restano: senza barre, con scritto «nessuna data».
    oggi = datetime.now().date().isoformat()
    if not all_days:
        all_days = [oggi]
    day_zero = date.fromisoformat(all_days[0])
    day_last = date.fromisoformat(all_days[-1])
    days = []
    cursor = day_zero
    today = datetime.now().date()
    while cursor <= day_last:
        days.append(
            {
                "date": cursor.isoformat(),
                "label": cursor.strftime("%d"),
                "month": cursor.strftime("%m"),
                "today": cursor == today,
                "weekend": cursor.weekday() >= 5,
            }
        )
        cursor = date.fromordinal(cursor.toordinal() + 1)

    def index(value):
        return (date.fromisoformat(value) - day_zero).days

    accepted_units = {unit_id for unit_id, unit in units.items() if unit["accepted"]}
    blocks = {}
    for unit in units.values():
        for phase in unit["phases"]:
            phase["day"] = index(phase["date"]) if phase["date"] else None
        unit["start"] = index(unit["first"]) if unit["first"] else None
        unit["end"] = index(unit["last"]) if unit["last"] else None
        unit["waiting_on"] = [dep for dep in unit["depends_on"] if dep not in accepted_units]
        phase_ids = {p["id"] for p in unit["phases"]}
        stalled = [p for p in unit["phases"] if p["status"] in STALLED]
        running = [p for p in unit["phases"] if p["id"] in live]
        if unit["accepted"]:
            unit["state"] = "accettata"
        elif stalled:
            unit["state"] = "respinta"
        elif running:
            unit["state"] = "in_corso"
        else:
            unit["state"] = "da_fare"
        dues = [item for item in obligations if item["id"].startswith(unit["id"]) or item["required_before"] in phase_ids]
        yours = _matching_prompts(prompt_entries, unit["id"], phase_ids)
        yours += [
            {
                "kind": "domanda",
                "label": q["id"],
                "detail": next_prompts.shorten(q.get("question"), 160),
                "target": f"#q-card-{q['id']}",
            }
            for q in questions
            if phase_ids & set(q["blocks"])
        ]
        unit["yours"] = yours
        unit["due"] = [
            {"kind": "obbligo", "label": item["id"], "detail": item["what"]} for item in dues
        ]
        unit["next"] = _next_action(unit, stalled, running, live)
        blocks.setdefault(unit["domain"], []).append(unit)

    out_blocks = []
    for domain, group in sorted(blocks.items()):
        group.sort(key=lambda item: item["id"])
        starts = [u["start"] for u in group if u["start"] is not None]
        ends = [u["end"] for u in group if u["end"] is not None]
        accepted = sum(1 for u in group if u["accepted"])
        yours = [dict(item, unit=u["id"]) for u in group for item in u["yours"]]
        due = [dict(item, unit=u["id"]) for u in group for item in u["due"]]
        if any(u["state"] == "respinta" for u in group):
            block_state = "respinta"
        elif any(u["state"] == "in_corso" for u in group):
            block_state = "in_corso"
        elif accepted == len(group):
            block_state = "accettata"
        else:
            block_state = "da_fare"
        by_suffix = {}
        for unit in group:
            suffix = (unit["next"] or {}).get("suffix")
            if suffix:
                by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
        out_blocks.append(
            {
                "domain": domain,
                "state": block_state,
                "accepted": accepted,
                "total": len(group),
                "start": min(starts) if starts else None,
                "end": max(ends) if ends else None,
                "next": {
                    "label": " · ".join(f"{key} ×{value}" for key, value in sorted(by_suffix.items()))
                    or ("niente: blocco chiuso" if accepted == len(group) else "nessuna fase aperta"),
                    "count": len(group) - accepted,
                },
                "yours": yours,
                "due": due,
                "units": group,
            }
        )
    # I commit che toccano i path dichiarati delle unita': l'attribuzione e' esatta, path per path,
    # e con questo repository il risultato e' zero per ogni blocco. Si dice, non si omette.
    fase_unita = {}
    for unit_id, unit in units.items():
        for phase in unit["phases"]:
            fase_unita[phase["id"]] = unit_id
    commits_by_block(out_blocks, git_facts, declared_paths_by_unit(state), fase_unita)
    return {
        "from": all_days[0],
        "to": all_days[-1],
        "days": days,
        "measured": counters,
        "blocks": out_blocks,
        "decisions": decisions,
        "questions": questions,
        "commits": _commit_window(git_facts, days),
    }


def _commit_window(git_facts, days):
    """I commit dentro la finestra disegnata, giorno per giorno, e il vuoto dichiarato."""
    if not git_facts.get("available"):
        return git_facts
    by_day = {}
    for commit in git_facts.get("list") or []:
        by_day.setdefault(commit["day"], []).append(commit)
    window = {day["date"]: by_day.get(day["date"], []) for day in days}
    facts = dict(git_facts)
    facts["by_day"] = window
    facts["in_window"] = sum(len(items) for items in window.values())
    facts["package_tracked"] = bool(git_facts.get("tracked_pack_files"))
    facts["by_day_outside"] = sorted(
        ((day, len(items)) for day, items in by_day.items() if day not in window), reverse=True
    )
    return facts


def _next_action(unit, stalled, running, live):
    """Cosa manca a questa unita', in una riga: la prima fase non accettata e perche'."""
    if unit["accepted"]:
        return None
    for phase in unit["phases"]:
        if phase["status"] in DONE:
            continue
        claim = live.get(phase["id"])
        if phase["status"] in STALLED:
            return {
                "suffix": phase["suffix"],
                "phase": phase["id"],
                "label": f"{phase['suffix']} da rifare",
                "detail": f"respinta in verifica (tentativo {phase['attempt'] or '?'})",
            }
        if claim:
            return {
                "suffix": phase["suffix"],
                "phase": phase["id"],
                "label": f"{phase['suffix']} in corso",
                "detail": next_prompts.shorten(
                    claim.get("taken_by") or claim.get("owner_agent") or claim.get("owner"), 90
                ),
            }
        if unit["waiting_on"]:
            return {
                "suffix": phase["suffix"],
                "phase": phase["id"],
                "label": f"{phase['suffix']} in attesa",
                "detail": "prima " + ", ".join(unit["waiting_on"]),
            }
        return {
            "suffix": phase["suffix"],
            "phase": phase["id"],
            "label": f"{phase['suffix']} da fare",
            "detail": f"stato nel registro: {phase['status']}",
        }
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="il carico che serve alla pagina")
    parser.add_argument(
        "--workspace",
        "--pack",  # nome storico
        dest="workspace",
        default=None,
        help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)",
    )
    parser.add_argument("--units", action="store_true", help="elenca anche le unita' di ogni blocco")
    args = parser.parse_args(argv)
    configure(Workspace.load(args.workspace))
    data = build(WS.root)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, default=str))
        return 0
    print(f"finestra {data['from']} -> {data['to']} ({len(data['days'])} giorni)")
    print(
        "date delle fasi: {dichiarata} dichiarate, {mtime} da mtime, {senza_data} senza data, "
        "{dichiarata_illeggibile} dichiarate ma illeggibili".format(**data["measured"])
    )
    commits = data["commits"]
    if commits.get("available"):
        last = commits.get("last") or {}
        print(
            f"commit: {commits['total']} in totale, {commits['in_window']} nella finestra · "
            f"ultimo {last.get('sha')} del {str(last.get('date'))[:10]} «{last.get('subject')}»"
        )
        print(
            f"non versionato: {commits['untracked']} file non tracciati, {commits['modified']} "
            f"modificati · file del pack tracciati: {commits['tracked_pack_files']}"
        )
    else:
        print(f"commit: non leggibili ({commits.get('reason')})")
    print(f"decisioni di governo aperte: {len(data['decisions'])} · domande aperte: {len(data['questions'])}")
    for block in data["blocks"]:
        span = f"{block['start']}–{block['end']}" if block["start"] is not None else "senza date"
        print(
            f"  {block['domain']:<14} {STATE_LABEL.get(block['state'], block['state']):<20} "
            f"{block['accepted']}/{block['total']} accettate · giorni {span} · "
            f"da farsi: {block['next']['label']} · per te: {len(block['yours'])} · "
            f"obblighi: {len(block['due'])}"
        )
        if args.units:
            for unit in block["units"]:
                nxt = unit["next"]["label"] if unit["next"] else "chiusa"
                print(
                    f"      {unit['id']:<10} {STATE_LABEL.get(unit['state'], unit['state']):<20} "
                    f"giorni {unit['start']}–{unit['end']} · {nxt}"
                    + (f" · per te: {len(unit['yours'])}" if unit["yours"] else "")
                    + (f" · attende {','.join(unit['waiting_on'])}" if unit["waiting_on"] else "")
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
