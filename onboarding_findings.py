#!/usr/bin/env python3
"""Audit per la bozza di Costituzione: fatti misurati e intervista iniziale tracciabile."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml
from onboarding_questions import CLOSED, add_question, initial_questions
from onboarding_questions import merge as merge_questions
from onboarding_questions import open_required, render_markdown, summary

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA = "project-console-onboarding-findings/1.1"
START = "<!-- ONBOARDING_FINDINGS_START -->"
END = "<!-- ONBOARDING_FINDINGS_END -->"


def _git(root, *args):
    esito = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return esito.stdout.strip() if esito.returncode == 0 else ""


def _package(root):
    path = root / "frontend" / "package.json"
    if not path.is_file():
        path = root / "package.json"
    if not path.is_file():
        return {}, ""
    try:
        return json.loads(path.read_text(encoding="utf-8")), str(path.relative_to(root))
    except (OSError, json.JSONDecodeError):
        return {}, str(path.relative_to(root))


def _source_count(root):
    ignore = {".git", ".coord", ".venv", "node_modules", "media", "staticfiles", "__pycache__"}
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in ignore:
            continue
        if path.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}:
            count += 1
    return count


def _fact(identifier, label, value, evidence):
    return {"id": identifier, "label": label, "value": value, "evidence": evidence}


def _gap(identifier, question, *, blocking=True, reason="", status="open"):
    return {
        "id": identifier,
        "question": question,
        "blocking": bool(blocking),
        "status": status,
        "reason": reason,
        "resolution": "",
    }


def open_blocking(workspace):
    """Le voci che impediscono l'approvazione, lette dal file che il console controlla."""
    path = Path(workspace).resolve() / "onboarding-findings.yaml"
    if not path.is_file():
        return []
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"{path}: audit iniziale illeggibile: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{path}: l'audit iniziale deve contenere una mappa YAML")
    gaps = [
        gap
        for gap in document.get("gaps") or []
        if isinstance(gap, dict)
        and gap.get("status") == "open"
        and gap.get("blocking") is True
    ]
    questions = [
        {**question, "kind": "question", "reason": question.get("area") or ""}
        for question in open_required(document.get("questions") or [])
    ]
    return gaps + questions


def _previous_document(workspace):
    path = workspace / "onboarding-findings.yaml"
    if not path.is_file():
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return document if isinstance(document, dict) else {}


def scan(repository, workspace):
    root = Path(repository).resolve()
    workspace = Path(workspace).resolve()
    previous = _previous_document(workspace)
    facts, gaps = [], []

    package, package_path = _package(root)
    deps = {
        **dict(package.get("dependencies") or {}),
        **dict(package.get("devDependencies") or {}),
    }
    frontend = [
        label
        for key, label in (
            ("vue", "Vue"),
            ("react", "React"),
            ("vite", "Vite"),
            ("vitest", "Vitest"),
            ("playwright", "Playwright"),
            ("@playwright/test", "Playwright"),
        )
        if key in deps
    ]
    facts.append(
        _fact(
            "frontend",
            "Frontend rilevato",
            ", ".join(dict.fromkeys(frontend)) or "non rilevato",
            package_path or "nessun package.json",
        )
    )

    requirements = ""
    for name in ("requirements.txt", "pyproject.toml", "Pipfile"):
        path = root / name
        if path.is_file():
            requirements += path.read_text(encoding="utf-8", errors="replace").lower()
    backend = [
        label
        for key, label in (
            ("django", "Django"),
            ("fastapi", "FastAPI"),
            ("celery", "Celery"),
            ("redis", "Redis"),
        )
        if key in requirements
    ]
    settings_files = [root / "settings.py"]
    settings_files.extend(
        path
        for path in root.glob("*/settings.py")
        if path not in settings_files
    )
    settings_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in settings_files
        if path.is_file()
    )
    if settings_text:
        backend += [
            label
            for needle, label in (
                ("django.db.backends.postgresql", "PostgreSQL"),
                ("django.db.backends.mysql", "MySQL"),
                ("django.db.backends.sqlite3", "SQLite"),
            )
            if needle in settings_text
        ]
    facts.append(
        _fact(
            "backend",
            "Backend rilevato",
            ", ".join(dict.fromkeys(backend)) or "non rilevato",
            "requirements/settings",
        )
    )

    repo = _git(root, "rev-parse", "--show-toplevel")
    dirty = []
    if repo:
        for riga in _git(root, "status", "--porcelain").splitlines():
            if len(riga) <= 3:
                continue
            valore = riga[3:].strip()
            try:
                (root / valore).resolve().relative_to(workspace)
                continue
            except ValueError:
                dirty.append(valore)
    facts.append(_fact("git", "Repository Git", repo or "non rilevato", "git rev-parse"))
    facts.append(
        _fact(
            "dirty",
            "File modificati fuori dal workspace",
            len(dirty),
            "git status --porcelain",
        )
    )
    if not repo:
        gaps.append(
            _gap("BOOT-GIT", "Inizializzare Git e definire il commit di partenza prima del primo task?")
        )
    elif dirty:
        gaps.append(
            _gap(
                "BOOT-DIRTY",
                "Quali modifiche preesistenti vanno conservate, spostate in un branch o considerate fuori perimetro?",
                reason=f"{len(dirty)} file modificati/non tracciati fuori da .coord",
            )
        )

    tracked = set(_git(root, "ls-files").splitlines()) if repo else set()
    tracked_sensitive = sorted(
        path
        for path in tracked
        if Path(path).name == ".env" or path.endswith((".pem", ".key"))
    )
    tracked_heavy = sorted(
        path
        for path in tracked
        if path.startswith((".venv/", "node_modules/", "__pycache__/"))
        or Path(path).name == "db.sqlite3"
    )
    if tracked_sensitive:
        gaps.append(
            _gap(
                "BOOT-SECRETS",
                "Rimuovere dal tracking Git i file che possono contenere segreti, senza cancellarli dal disco.",
                reason=", ".join(tracked_sensitive),
            )
        )
    if tracked_heavy:
        gaps.append(
            _gap(
                "BOOT-ARTIFACTS",
                "Definire quali ambienti, database e cache locali non devono essere versionati.",
                reason=f"{len(tracked_heavy)} file tecnici tracciati",
            )
        )

    sources = _source_count(root)
    facts.append(_fact("sources", "File sorgente rilevati", sources, "conteggio statico"))
    if sources:
        gaps.append(
            _gap(
                "BOOT-CODE-BASE",
                "Il codice esistente è la base da evolvere o verrà sostituito? Indicare cosa resta e cosa viene riscritto.",
                reason=f"{sources} file sorgente già presenti",
            )
        )
    if "Vue" in frontend and "React" in frontend:
        gaps.append(
            _gap(
                "BOOT-FRONTEND-CONFLICT",
                "Il repository contiene sia Vue sia React: quale è la base ufficiale della v1?",
            )
        )
    elif frontend:
        gaps.append(
            _gap(
                "BOOT-FRONTEND",
                f"Confermare che {', '.join(frontend)} sia la base frontend della v1.",
                reason=package_path,
            )
        )
    if backend:
        gaps.append(
            _gap(
                "BOOT-BACKEND",
                f"Confermare che {', '.join(dict.fromkeys(backend))} sia la base backend della v1.",
                reason="requirements/settings",
            )
        )
    elif not frontend:
        gaps.append(
            _gap(
                "BOOT-STACK",
                "Definire lo stack della v1: linguaggi, framework, database, test e infrastruttura.",
                reason="nessuno stack applicativo riconosciuto nella repository",
            )
        )

    precedenti = {
        str(gap.get("id")): gap
        for gap in previous.get("gaps") or []
        if isinstance(gap, dict)
    }
    for gap in gaps:
        prima = precedenti.get(gap["id"], {})
        if prima.get("status") in {"open", "resolved", "not_applicable", "accepted_risk"}:
            gap["status"] = prima["status"]
        gap["resolution"] = str(prima.get("resolution") or "")

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repository": str(root),
        "workspace": str(workspace),
        "facts": facts,
        "gaps": gaps,
        "questions": merge_questions(previous.get("questions") or initial_questions()),
    }


def render_section(document):
    righe = [
        START,
        "## 0. Stato di partenza e decisioni mancanti",
        "",
        f"<!-- Generato da onboarding_findings.py il {document['generated_at']}. Non contiene valori segreti. -->",
        "",
        "### Rilevato dal repository",
        "",
    ]
    for fact in document.get("facts") or []:
        righe.append(
            f"- **{fact['label']}:** {fact['value']} — prova: `{fact['evidence']}`"
        )
    aperti = [gap for gap in document.get("gaps") or [] if gap.get("status") == "open"]
    righe += ["", "### Decisioni mancanti", ""]
    if not aperti:
        righe.append("Nessun gap tecnico aperto rilevato dall'audit statico.")
    for gap in aperti:
        peso = "BLOCCANTE" if gap.get("blocking") else "non bloccante"
        nota = f" — {gap['reason']}" if gap.get("reason") else ""
        righe.append(f"- [ ] `{gap['id']}` [{peso}] {gap['question']}{nota}")
    risolti = [gap for gap in document.get("gaps") or [] if gap.get("status") != "open"]
    if risolti:
        righe += ["", "### Decisioni chiuse", ""]
        for gap in risolti:
            righe.append(
                f"- [x] `{gap['id']}` — {gap.get('status')}: {gap.get('resolution') or 'chiusa'}"
            )
    domande = document.get("questions") or []
    dati = summary(domande)
    righe += [
        "",
        "### Intervista di progetto",
        "",
        f"{dati['closed']} decisioni chiuse su {dati['total']} · {dati['open']} ancora aperte.",
        "Le domande sono adattive: una voce non pertinente si chiude con `not_applicable` e il motivo.",
        "",
    ]
    aree = {}
    for domanda in domande:
        aree.setdefault(domanda.get("area") or "Altre decisioni", []).append(domanda)
    for area, voci in aree.items():
        righe += [f"#### {area}", ""]
        for domanda in voci:
            chiusa = domanda.get("status") in CLOSED
            segno = "x" if chiusa else " "
            stato = (
                ""
                if domanda.get("status") == "open"
                else f" — **{domanda.get('status')}:** {domanda.get('answer') or 'senza nota'}"
            )
            righe.append(
                f"- [{segno}] `{domanda.get('id')}` {domanda.get('question')}{stato}"
            )
        righe.append("")
    righe += ["", END]
    return "\n".join(righe)


def apply_to_constitution(path, section):
    testo = path.read_text(encoding="utf-8")
    if START in testo and END in testo:
        prima, resto = testo.split(START, 1)
        _, dopo = resto.split(END, 1)
        testo = prima + section + dopo
    else:
        marker = "## 1. Obiettivo"
        testo = testo.replace(marker, section + "\n\n" + marker, 1)
    path.write_text(testo, encoding="utf-8")


def save(workspace, document):
    workspace = Path(workspace).resolve()
    findings_path = workspace / "onboarding-findings.yaml"
    findings_path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (workspace / "onboarding-questions.md").write_text(
        render_markdown(document.get("questions") or []),
        encoding="utf-8",
    )
    constitution = workspace / "constitution.md"
    if constitution.is_file():
        apply_to_constitution(constitution, render_section(document))
    return findings_path


def resolve(workspace, identifier, status, note):
    workspace = Path(workspace).resolve()
    path = workspace / "onboarding-findings.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found = next(
        (gap for gap in document.get("gaps") or [] if str(gap.get("id")) == identifier),
        None,
    )
    question = found is None
    if question:
        found = next(
            (
                item
                for item in document.get("questions") or []
                if str(item.get("id")) == identifier
            ),
            None,
        )
    if found is None:
        raise SystemExit(f"decisione non trovata: {identifier}")
    ammessi = (
        {"open", "answered", "not_applicable", "accepted_risk", "deferred"}
        if question
        else {"open", "resolved", "not_applicable", "accepted_risk"}
    )
    if status not in ammessi:
        raise SystemExit(f"stato non valido: {status}")
    if status != "open" and not str(note or "").strip():
        raise SystemExit("una decisione chiusa richiede --note")
    found["status"] = status
    found["answer" if question else "resolution"] = str(note or "").strip()
    save(workspace, document)
    return document


def ask(workspace, question, area="Approfondimenti", identifier=None, blocking=True):
    workspace = Path(workspace).resolve()
    path = workspace / "onboarding-findings.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        document["questions"] = add_question(
            document.get("questions") or [],
            area,
            question,
            identifier=identifier,
            blocking=blocking,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    save(workspace, document)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--repository")
    azione = parser.add_mutually_exclusive_group()
    azione.add_argument("--resolve")
    azione.add_argument("--ask-question")
    parser.add_argument("--status", default="resolved")
    parser.add_argument("--note")
    parser.add_argument("--area", default="Approfondimenti")
    parser.add_argument("--question-id")
    parser.add_argument("--optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if args.resolve:
        document = resolve(workspace, args.resolve, args.status, args.note)
    elif args.ask_question:
        document = ask(
            workspace,
            args.ask_question,
            area=args.area,
            identifier=args.question_id,
            blocking=not args.optional,
        )
    else:
        repository = (
            Path(args.repository).expanduser().resolve()
            if args.repository
            else workspace.parent
        )
        document = scan(repository, workspace)
        save(workspace, document)
    if args.json:
        print(json.dumps(document, ensure_ascii=False, indent=2))
    else:
        aperti_gap = sum(
            1
            for gap in document.get("gaps") or []
            if gap.get("status") == "open" and gap.get("blocking")
        )
        aperti_domande = len(open_required(document.get("questions") or []))
        print(
            "onboarding-findings.yaml aggiornato · "
            f"gap bloccanti aperti: {aperti_gap} · domande aperte: {aperti_domande}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
