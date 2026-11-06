"""Le dichiarazioni obbligatorie di un report nei progetti nuovi: usage e provenienza Git."""
from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime
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


def _review_file(workspace, raw, label):
    errori = []
    if not str(raw or "").strip():
        return None, [f"review.{label}.path è obbligatorio"]
    target = (Path(workspace.root) / str(raw)).resolve()
    try:
        target.relative_to(Path(workspace.root).resolve())
    except ValueError:
        return None, [f"review.{label}.path esce dal workspace"]
    if not target.is_file():
        return None, [f"review.{label}.path non esiste: {raw}"]
    return target, errori


def _review_hash(workspace, block, label):
    target, errori = _review_file(workspace, (block or {}).get("path"), label)
    attesa = str((block or {}).get("sha256") or "").strip().lower()
    if target is None:
        return errori
    if not re.fullmatch(r"[0-9a-f]{64}", attesa):
        errori.append(f"review.{label}.sha256 deve essere uno SHA-256 completo")
    elif hashlib.sha256(target.read_bytes()).hexdigest() != attesa:
        errori.append(f"review.{label}.sha256 non corrisponde al file {block.get('path')}")
    return errori


def review_errors(workspace, document, phase_kind=None):
    """La prova T: percorso reale, screenshot o output, diff e impronte verificabili."""
    if str(phase_kind or "") != "independent_verification":
        return []
    review = document.get("review")
    if not isinstance(review, dict):
        return ["manca `review`: una consegna T deve mostrare la modifica reale"]
    errori = []
    kind = str(review.get("kind") or "").strip().lower()
    if kind not in ("ui", "backend", "mixed"):
        errori.append("review.kind deve essere ui, backend oppure mixed")
    for campo in ("title", "summary", "captured_at", "route"):
        if not str(review.get(campo) or "").strip():
            errori.append(f"review.{campo} è obbligatorio")
    route = str(review.get("route") or "").strip()
    if route and not route.startswith("/"):
        errori.append("review.route deve essere relativa all'app e iniziare con /")
    passi = review.get("steps")
    if not isinstance(passi, list) or not passi:
        errori.append("review.steps deve essere una lista non vuota")

    captured_at = None
    try:
        captured_at = datetime.fromisoformat(
            str(review.get("captured_at") or "").strip().replace("Z", "+00:00")
        )
        if captured_at.tzinfo is None:
            captured_at = captured_at.astimezone()
    except ValueError:
        errori.append("review.captured_at deve essere una data ISO valida")

    if kind in ("ui", "mixed"):
        screenshot = review.get("screenshot")
        if not isinstance(screenshot, dict):
            errori.append("review.screenshot è obbligatorio per kind ui/mixed")
        else:
            errori.extend(_review_hash(workspace, screenshot, "screenshot"))
            if not str(screenshot.get("viewport") or "").strip():
                errori.append("review.screenshot.viewport è obbligatorio")

    if kind in ("backend", "mixed"):
        proof = review.get("proof")
        if not isinstance(proof, dict):
            errori.append("review.proof è obbligatorio per kind backend/mixed")
        else:
            for campo in ("command", "result", "duration"):
                if proof.get(campo) in (None, ""):
                    errori.append(f"review.proof.{campo} è obbligatorio")
            if proof.get("output_path"):
                errori.extend(
                    _review_hash(
                        workspace,
                        {
                            "path": proof.get("output_path"),
                            "sha256": proof.get("output_sha256"),
                        },
                        "proof.output",
                    )
                )
            elif not str(proof.get("recorded_in") or "").strip():
                errori.append(
                    "review.proof richiede output_path+output_sha256 oppure recorded_in"
                )

    diff = review.get("diff")
    if not isinstance(diff, dict):
        errori.append("review.diff è obbligatorio")
    else:
        riassunto = diff.get("summary")
        percorsi = diff.get("paths")
        if not isinstance(riassunto, list) or not riassunto:
            errori.append("review.diff.summary deve essere una lista non vuota")
        if not isinstance(percorsi, list):
            errori.append("review.diff.paths deve essere una lista")
            percorsi = []
        patch = str(diff.get("patch_path") or "").strip()
        patch_sha = str(diff.get("sha256") or "").strip()
        if bool(patch) != bool(patch_sha):
            errori.append("review.diff richiede patch_path e sha256 insieme")
        elif patch:
            errori.extend(
                _review_hash(
                    workspace,
                    {"path": patch, "sha256": patch_sha},
                    "diff",
                )
            )
        if captured_at is not None:
            for relativo in percorsi:
                try:
                    target = (Path(workspace.root) / str(relativo)).resolve()
                    target.relative_to(Path(workspace.root).resolve())
                except (OSError, ValueError):
                    errori.append(f"review.diff.paths contiene un percorso non valido: {relativo}")
                    continue
                if target.is_file():
                    modificato = datetime.fromtimestamp(target.stat().st_mtime, tz=captured_at.tzinfo)
                    if modificato > captured_at:
                        errori.append(
                            f"review è precedente all'ultima modifica di {relativo}"
                        )
    return errori


def validate(workspace, document, phase_kind=None):
    errori = []
    if workspace.require_usage:
        errori.extend(usage_errors(document))
    if workspace.require_git_provenance:
        errori.extend(git_errors(document))
    errori.extend(review_errors(workspace, document, phase_kind=phase_kind))
    return errori


def prompt_contract(workspace):
    """Le clausole macchina che ogni prompt deve mostrare quando il workspace le richiede."""
    righe = []
    if workspace.require_usage:
        righe.extend(
            [
                "USAGE OBBLIGATORIO nel report: `usage.availability` vale `measured` oppure `unavailable`.",
                "Se vale `unavailable`, `usage.reason` e' obbligatorio; se vale `measured`, dichiara",
                "`total_tokens` oppure entrambi `input_tokens` e `output_tokens`.",
            ]
        )
    if workspace.require_git_provenance:
        righe.extend(
            [
                "GIT OBBLIGATORIO nel report: branch, worktree, base_commit, head_commit,",
                "changed_paths, dirty_before e clean_after.",
                "`changed_paths` e `dirty_before` sono LISTE YAML (`- percorso` oppure `[]`),",
                "non booleani o stringhe. `clean_after` e' un booleano true/false.",
            ]
        )
    return righe


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
