#!/usr/bin/env python3
"""Il piano dei task e la sua impronta approvata.

La Costituzione stabilisce il patto; `tasks.yaml` è la prima traduzione operativa di quel patto.
Per un progetto nuovo, quella traduzione deve essere vista dall'utente e poi sorvegliata: se il
file cambia, il tool blocca le nuove attivazioni finché l'utente non riconferma il piano.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

sys.path[:0] = [
    str(Path(__file__).resolve().parent.parent),
    str(Path(__file__).resolve().parent),
]

from console import constitution  # noqa: E402
from workspace import Workspace, lock_file  # noqa: E402

SCHEMA = "project-console-plan-approval/1.0"


class PlanError(Exception):
    code = "plan_error"


class PlanNotApproved(PlanError):
    code = "plan_not_approved"


class PlanChanged(PlanError):
    code = "plan_changed"


class PlanConflict(PlanError):
    code = "plan_conflict"


class PlanEmpty(PlanError):
    code = "plan_empty"


def _load(path):
    try:
        return yaml.load(
            path.read_text(encoding="utf-8", errors="replace"),
            Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
        ) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _tasks(workspace):
    percorso = workspace.path(workspace.tasks)
    if not percorso.is_file():
        return None, "", {}, ("tasks.yaml non esiste")
    try:
        testo = percorso.read_text(encoding="utf-8")
        documento = yaml.safe_load(testo) or {}
    except (OSError, yaml.YAMLError) as error:
        return None, "", {}, f"tasks.yaml non è leggibile: {error}"
    if not isinstance(documento, dict):
        return None, hashlib.sha256(testo.encode("utf-8")).hexdigest(), {}, (
            "tasks.yaml deve contenere una mappa YAML"
        )
    return (
        documento,
        hashlib.sha256(testo.encode("utf-8")).hexdigest(),
        {
            "units": len(documento.get("units") or []),
            "tasks": len(documento.get("tasks") or []),
        },
        "",
    )


def gate(workspace):
    if not workspace.require_plan_approval:
        return {
            "schema": SCHEMA,
            "required": False,
            "approved": True,
            "status": "not_required",
            "tasks_sha256": "",
            "approved_sha256": "",
            "units": 0,
            "tasks": 0,
            "message": "",
        }
    _, sha256, conteggi, errore = _tasks(workspace)
    base = {
        "schema": SCHEMA,
        "required": True,
        "approved": False,
        "status": "missing",
        "tasks_sha256": sha256,
        "approved_sha256": "",
        "units": conteggi.get("units", 0),
        "tasks": conteggi.get("tasks", 0),
        "approved_at": "",
        "approved_by": "",
        "message": errore,
    }
    if errore:
        base["status"] = "invalid"
        return base
    if not conteggi["units"] or not conteggi["tasks"]:
        base["status"] = "empty"
        base["message"] = "il piano non contiene ancora unità e task"
        return base
    path = workspace.plan_approval_path
    if not path.is_file():
        base["message"] = "il piano dei task non è ancora stato confermato"
        return base
    approvazione = _load(path)
    if str(approvazione.get("schema") or "") != SCHEMA:
        base["status"] = "invalid"
        base["message"] = f"{path}: schema non riconosciuto"
        return base
    approved_sha = str(approvazione.get("tasks_sha256") or "")
    base.update(
        {
            "approved_sha256": approved_sha,
            "approved_at": str(approvazione.get("approved_at") or ""),
            "approved_by": str(approvazione.get("approved_by") or ""),
        }
    )
    if str(approvazione.get("status") or "") != "approved":
        base["status"] = "pending"
        base["message"] = "il piano dei task aspetta la conferma dell'utente"
        return base
    if approved_sha != sha256:
        base["status"] = "changed"
        base["message"] = (
            "tasks.yaml è cambiato dopo l'approvazione: nuove attivazioni bloccate"
        )
        return base
    base["approved"] = True
    base["status"] = "approved"
    base["message"] = ""
    return base


def require_approved(workspace):
    stato = gate(workspace)
    if stato["approved"]:
        return stato
    if stato["status"] == "empty":
        raise PlanEmpty(stato["message"])
    if stato["status"] == "changed":
        raise PlanChanged(stato["message"])
    raise PlanNotApproved(stato["message"] or "approvazione del piano richiesta")


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(
        dir=str(path.parent), prefix=".plan-approval-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporaneo, path)
    finally:
        if os.path.exists(temporaneo):
            os.unlink(temporaneo)


def approve(workspace, expected_sha256=None):
    """Conferma il piano corrente. La Costituzione deve essere già approvata."""
    constitution.require_approved(workspace)
    _, corrente, conteggi, errore = _tasks(workspace)
    if errore:
        raise PlanEmpty(errore)
    if not conteggi["units"] or not conteggi["tasks"]:
        raise PlanEmpty("il piano non contiene ancora unità e task")
    with open(lock_file(workspace.root), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            # Rilettura sotto lock: il file potrebbe essere cambiato durante il controllo.
            _, corrente, conteggi, errore = _tasks(workspace)
            if errore or not conteggi["units"] or not conteggi["tasks"]:
                raise PlanEmpty(errore or "il piano non contiene ancora unità e task")
            if expected_sha256 and expected_sha256 != corrente:
                raise PlanConflict(
                    "tasks.yaml è cambiato durante la revisione: ricarica il piano"
                )
            adesso = datetime.now().astimezone().isoformat(timespec="seconds")
            _write(
                workspace.plan_approval_path,
                {
                    "schema": SCHEMA,
                    "status": "approved",
                    "tasks_sha256": corrente,
                    "approved_at": adesso,
                    "approved_by": "utente",
                    "units": conteggi["units"],
                    "tasks": conteggi["tasks"],
                },
            )
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    return gate(workspace)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    workspace = Workspace.load(args.workspace)
    try:
        esito = (
            approve(workspace, expected_sha256=args.expected_sha256)
            if args.approve
            else gate(workspace)
        )
    except PlanError as error:
        print(f"BLOCCATO: {error}")
        return 1
    print(json.dumps(esito, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
