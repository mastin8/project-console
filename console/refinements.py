"""La piccola anagrafica delle rifiniture: fasi A/E/T/R, claim e report.

Le 70 unità vivono in ``tasks.yaml``. Le rifiniture non sono unità: sono lavoro sopra il lavoro,
ma devono avere la stessa forma osservabile. Questo file è la loro sorgente esplicita; il console
la legge e la fonde con gli obblighi di ``state.yaml``. Se non esiste, il console usa la lettura
derivata dagli atti e lo dichiara.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workspace import Workspace, lock_file

SCHEMA = "project-console-refinements/1.0"
PHASES = ("A", "E", "T", "R")
LIVE_CLAIMS = ("taken", "active", "running", "in_progress")
DONE = ("accepted", "done", "closed")
PARTIAL = ("partial", "delivered", "rejected", "needs_changes", "failed")
IN_PROGRESS = ("taken", "active", "running", "in_progress")


def _carica(percorso):
    return yaml.load(percorso.read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def load(workspace):
    """Le rifiniture dichiarate, indicizzate per id dell'obbligo."""
    percorso = workspace.refinements_path
    if not percorso.is_file():
        return {}
    documento = _carica(percorso) or {}
    if documento.get("schema") != SCHEMA:
        raise ValueError(f"{percorso}: schema atteso {SCHEMA}")
    fuori = {}
    for voce in documento.get("items") or []:
        if not isinstance(voce, dict) or not voce.get("id"):
            continue
        if voce.get("active") is False:
            continue
        fuori[str(voce["id"])] = voce
    return fuori


def _fase_breve(stato):
    stato = str(stato or "").strip().lower()
    if stato in DONE:
        return "done"
    if stato in IN_PROGRESS:
        return "in_progress"
    if stato in PARTIAL:
        return "partial"
    return "missing"


def stage_map(item):
    fasi = item.get("phases") or {}
    return {
        fase: _fase_breve((fasi.get(fase) or {}).get("status"))
        for fase in PHASES
    }


def next_phase(item):
    fasi = item.get("phases") or {}
    for fase in PHASES:
        if _fase_breve((fasi.get(fase) or {}).get("status")) != "done":
            return fase
    return "R"


def latest_report(item):
    candidati = []
    for fase in PHASES:
        voce = (item.get("phases") or {}).get(fase) or {}
        if not voce.get("report"):
            continue
        candidati.append(
            (
                int(voce.get("attempt") or 0),
                fase,
                {
                    "path": str(voce["report"]),
                    "attempt": voce.get("attempt"),
                    "phase": fase,
                    "verdict": str(voce.get("verdict") or ""),
                    "author": str(voce.get("author") or ""),
                },
            )
        )
    if not candidati:
        return None
    return max(candidati, key=lambda voce: (voce[0], voce[1]))[2]


def _report_state(workspace, path):
    if workspace is None or not path:
        return {}
    percorso = workspace.path(str(path))
    if not percorso.is_file():
        return {}
    try:
        return _carica(percorso) or {}
    except Exception:  # noqa: BLE001 - un report illeggibile non si inventa
        return {}


def merge(obligation, item, workspace=None):
    """Sovrappone la rifinitura esplicita ai campi derivati dell'obbligo."""
    fasi = stage_map(item)
    r_report = _report_state(workspace, (item.get("phases") or {}).get("R", {}).get("report"))
    chiusa_da_report = bool(
        r_report.get("closure_condition_met") is True
        or str(r_report.get("obligation_status_after") or "") == "closed"
        or "accept" in str(r_report.get("verdict") or "").lower()
    )
    # Un atto pubblicato non equivale a uno stadio chiuso: se il report dice `open`, lo stadio
    # resta parziale e non può far avanzare il ciclo. Questo impedisce che una R parta su E/T
    # ancora aperti (misurato il 2026-10-19 su ACCEPTED-EVIDENCE, R attempt 8).
    if not chiusa_da_report:
        # A è un atto di design/decisione: resta done anche se l'obbligo è ancora aperto.
        # E/T/R, invece, non sono done se il loro report dichiara ancora `open`.
        for fase in ("E", "T", "R"):
            voce = (item.get("phases") or {}).get(fase) or {}
            if _fase_breve(voce.get("status")) != "done":
                continue
            report = _report_state(workspace, voce.get("report"))
            if not report:
                continue
            if (
                report.get("closure_condition_met") is False
                or str(report.get("obligation_status_after") or "") == "open"
                or "needs_changes" in str(report.get("verdict") or "").lower()
                or "fail" in str(report.get("verdict") or "").lower()
            ):
                fasi[fase] = "partial"
    prossima = next_phase(item)
    if fasi.get(prossima) == "partial" or any(
        fasi.get(fase) == "partial" for fase in ("E", "T")
    ):
        prossima = next(
            (fase for fase in ("A", "E", "T", "R") if fasi.get(fase) != "done"),
            prossima,
        )
    claim = item.get("claim") or {}
    presa = str(claim.get("status") or "").lower() in LIVE_CLAIMS
    report = latest_report(item) or {}
    fase_corrente = str(report.get("phase") or prossima)
    voce_fase = (item.get("phases") or {}).get(fase_corrente) or {}
    obligation.update(
        {
            "stages": fasi,
            "next_stage": prossima,
            "stage_known": True,
            "stage_source": "refinements.yaml",
            "title": str(item.get("title") or ""),
            "owners": [str(voce) for voce in item.get("owners") or []],
            "paths": [str(percorso) for percorso in item.get("paths") or []],
            "branch": str(item.get("branch") or f"task/{obligation['id']}"),
            "worktree": str(item.get("worktree") or f".worktrees/{obligation['id']}"),
            "test": voce_fase.get("test") or {},
            "errors": voce_fase.get("errors") or [],
            "taken": presa,
            "taken_by": str(claim.get("taken_by") or claim.get("owner") or ""),
            "taken_at": str(claim.get("taken_at") or ""),
            "claim_task": str(claim.get("task") or ""),
            "claim_status": str(claim.get("status") or ""),
            "last_claim_by": str(claim.get("taken_by") or claim.get("owner") or ""),
            "last_claim_task": str(claim.get("task") or ""),
            "last_claim_at": str(claim.get("taken_at") or ""),
            "report_verdict": str(report.get("verdict") or ""),
            "report_phase": str(report.get("phase") or ""),
            "report_attempt": report.get("attempt"),
            "report_author": str(report.get("author") or ""),
            "report_path": str(report.get("path") or ""),
            "next_report": str(item.get("next_report") or ""),
            "report_next": str(item.get("next") or ""),
            "report_closed": chiusa_da_report,
        }
    )
    return obligation


def update(
    workspace,
    obligation,
    *,
    add=False,
    title=None,
    phase=None,
    status=None,
    attempt=None,
    report=None,
    verdict=None,
    author=None,
    test_command=None,
    test_exit=None,
    test_duration=None,
    errors=None,
    branch=None,
    worktree=None,
    claim_by=None,
    claim_task=None,
    release=False,
    next_text=None,
    next_report=None,
):
    """Aggiorna una rifinitura sotto lock. Usata dalla CLI e dal front-end."""
    percorso = workspace.refinements_path
    documento = _carica(percorso) or {"schema": SCHEMA, "items": []}
    item = next(
        (voce for voce in documento.get("items") or [] if str(voce.get("id")) == obligation),
        None,
    )
    if item is None:
        if not add:
            raise SystemExit(
                f"rifinitura sconosciuta: {obligation} (usa --add per crearla)"
            )
        item = {
            "id": obligation,
            "title": title or "",
            "phases": {fase: {"status": "pending"} for fase in PHASES},
            "claim": {},
            "next": "",
            "next_report": "",
        }
        documento.setdefault("items", []).append(item)
    cambi = []
    if add:
        cambi.append("item")
    if title is not None:
        item["title"] = title
        cambi.append("title")
    if branch is not None:
        item["branch"] = branch
        cambi.append("branch")
    if worktree is not None:
        item["worktree"] = worktree
        cambi.append("worktree")
    if phase:
        fase = item.setdefault("phases", {}).setdefault(phase, {})
        for campo in ("status", "attempt", "report", "verdict", "author"):
            valore = {
                "status": status,
                "attempt": attempt,
                "report": report,
                "verdict": verdict,
                "author": author,
            }[campo]
            if valore is not None:
                fase[campo] = valore
                cambi.append(f"phases.{phase}.{campo}")
        if any(valore is not None for valore in (test_command, test_exit, test_duration)):
            test = fase.setdefault("test", {})
            for campo, valore in (
                ("command", test_command),
                ("exit", test_exit),
                ("duration", test_duration),
            ):
                if valore is not None:
                    test[campo] = valore
                    cambi.append(f"phases.{phase}.test.{campo}")
        if errors is not None:
            if isinstance(errors, str):
                errors = [voce.strip() for voce in errors.split(";") if voce.strip()]
            fase["errors"] = list(errors)
            cambi.append(f"phases.{phase}.errors")
    if claim_by:
        item["claim"] = {
            "status": "taken",
            "taken_by": claim_by,
            "task": claim_task or "",
            "taken_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        cambi.append("claim")
    if release:
        claim = item.setdefault("claim", {})
        claim["status"] = "released"
        claim["released_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        cambi.append("claim.released")
    if next_text:
        item["next"] = next_text
        cambi.append("next")
    if next_report:
        item["next_report"] = next_report
        cambi.append("next_report")
    if not cambi:
        raise SystemExit("nessun campo da aggiornare")
    with open(lock_file(workspace.root), "a+") as maniglia:
        fcntl.flock(maniglia, fcntl.LOCK_EX)
        percorso.write_text(
            yaml.safe_dump(documento, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        fcntl.flock(maniglia, fcntl.LOCK_UN)
    return {"obligation": obligation, "updated": cambi, "file": str(percorso)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fasi, claim e report delle rifiniture")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--obligation", required=True)
    parser.add_argument("--add", action="store_true")
    parser.add_argument("--title")
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--status")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--report")
    parser.add_argument("--verdict")
    parser.add_argument("--author")
    parser.add_argument("--test-command")
    parser.add_argument("--test-exit")
    parser.add_argument("--test-duration")
    parser.add_argument("--errors")
    parser.add_argument("--branch")
    parser.add_argument("--worktree")
    parser.add_argument("--claim-by")
    parser.add_argument("--claim-task")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--next")
    parser.add_argument("--next-report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    esito = update(
        Workspace.load(args.workspace),
        args.obligation,
        add=args.add,
        title=args.title,
        phase=args.phase,
        status=args.status,
        attempt=args.attempt,
        report=args.report,
        verdict=args.verdict,
        author=args.author,
        test_command=args.test_command,
        test_exit=args.test_exit,
        test_duration=args.test_duration,
        errors=args.errors,
        branch=args.branch,
        worktree=args.worktree,
        claim_by=args.claim_by,
        claim_task=args.claim_task,
        release=args.release,
        next_text=args.next,
        next_report=args.next_report,
    )
    if args.json:
        print(json.dumps(esito, ensure_ascii=False))
    else:
        print(f"{args.obligation}: aggiornati {', '.join(esito['updated'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
