"""Le dichiarazioni obbligatorie di un report nei progetti nuovi: usage e provenienza Git."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _numero(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        numero = float(value)
    else:
        try:
            numero = float(str(value).strip().replace(",", "."))
        except ValueError:
            return None
    return numero if numero >= 0 else None


def usage_errors(document):
    usage = document.get("usage")
    if not isinstance(usage, dict):
        return ["manca `usage` (availability measured|unavailable)"]
    availability = str(usage.get("availability") or "").strip().lower()
    if availability == "unavailable":
        if not str(usage.get("reason") or "").strip():
            return ["usage unavailable senza `reason`: il motivo è obbligatorio"]
        return []
    if availability != "measured":
        return ["usage.availability deve essere `measured` oppure `unavailable`"]
    input_tokens = _numero(usage.get("input_tokens"))
    output_tokens = _numero(usage.get("output_tokens"))
    total_tokens = _numero(usage.get("total_tokens"))
    if total_tokens is None and (input_tokens is None or output_tokens is None):
        return [
            "usage measured richiede `total_tokens`, oppure `input_tokens` e `output_tokens`"
        ]
    return []


def git_errors(document):
    git = document.get("git")
    if not isinstance(git, dict):
        return ["manca `git` con branch, worktree, base/head commit e path modificati"]
    errori = []
    for campo in ("branch", "worktree", "base_commit", "head_commit"):
        if not str(git.get(campo) or "").strip():
            errori.append(f"git.{campo} è obbligatorio")
    for campo in ("base_commit", "head_commit"):
        valore = str(git.get(campo) or "").strip()
        if valore and not re.fullmatch(r"[0-9a-fA-F]{7,40}", valore):
            errori.append(f"git.{campo} non è un commit SHA valido")
    for campo in ("changed_paths", "dirty_before"):
        if not isinstance(git.get(campo), list):
            errori.append(f"git.{campo} deve essere una lista")
    if not isinstance(git.get("clean_after"), bool):
        errori.append("git.clean_after deve essere true oppure false")
    return errori


def validate(workspace, document):
    errori = []
    if workspace.require_usage:
        errori.extend(usage_errors(document))
    if workspace.require_git_provenance:
        errori.extend(git_errors(document))
    return errori


def unavailable_usage(reason):
    return {
        "availability": "unavailable",
        "reason": str(reason),
    }


def git_snapshot(workspace, base_commit=None):
    """La provenienza Git osservabile adesso, per gli atti scritti dal tool."""
    root = str(workspace.root)

    def git(*args):
        esito = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return esito.stdout.strip() if esito.returncode == 0 else ""

    worktree = git("rev-parse", "--show-toplevel")
    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    state = [
        riga[3:].strip()
        for riga in git("status", "--porcelain").splitlines()
        if len(riga) > 3
    ]
    return {
        "branch": branch,
        "worktree": worktree,
        "base_commit": str(base_commit or head),
        "head_commit": head,
        "changed_paths": state,
        "dirty_before": [],
        "clean_after": not state,
    }
