#!/usr/bin/env python3
"""Crea un workspace: la cartella di dati che il coordinatore legge.

Un workspace non e' un progetto di codice, e' la sua contabilita' di lavoro: unita', fasi, claim,
domande, decisioni, consegne, il quaderno dei prompt. Questo comando ne scrive la struttura minima
a partire dai modelli in `templates/workspace/`, cosi' il primo giorno di un progetto nuovo non si
comincia da un formato da indovinare.

Non sovrascrive niente che esista gia': quello che c'e' lo lascia, e lo dice.

Uso::

    python3 scaffold.py /percorso/nuovo-progetto --project "Nome"
    python3 scaffold.py examples/demo --project Demo --esempio
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELLI = ROOT / "templates" / "workspace"

#: I modelli da copiare, e dove vanno. `?esempio` significa: solo con `--esempio`.
MAPPATURA = (
    ("constitution.md", "constitution.md", True),
    ("FIRST-PROMPT.md", "FIRST-PROMPT.md", True),
    ("console.yaml", "console.yaml", True),
    ("state.yaml", "state.yaml", True),
    ("tasks-esempio.yaml", "tasks.yaml", True),
    ("tasks.yaml", "tasks.yaml", True),
    ("questions.yaml", "questions.yaml", True),
    ("decisions.yaml", "decisions.yaml", True),
    ("user_decisions.yaml", "user_decisions.yaml", True),
    ("plan-approval.yaml", "plan-approval.yaml", True),
    ("PARALLEL-PROMPTS.md", "PARALLEL-PROMPTS.md", True),
    ("pending-transitions/README.md", "pending-transitions/README.md", True),
    ("inbox/README.md", "inbox/README.md", True),
    ("brand/README.md", "brand/README.md", True),
    ("agents/README.md", "agents/README.md", True),
    ("agents/CONTRATTO.md", "agents/CONTRATTO.md", True),
    ("agents/agents.yaml", "agents/agents.yaml", True),
    ("agents/orchestration.yaml", "agents/orchestration.yaml", True),
)
#: Il quaderno d'esempio ha un prompt dentro; senza `--esempio` ne basta l'intestazione.
QUADERNO_VUOTO = "# Il quaderno dei prompt\n\nAggiungi qui le sezioni numerate: vedi il modello in `templates/workspace/PARALLEL-PROMPTS.md`.\n"
CONSEGNA_ESEMPIO = (
    "schema: project-console-report/1.0\n"
    "task_id: ES01A\n"
    "attempt: 1\n"
    "status: published\n"
    "verdict: pass\n"
    "published_at: '{oggi}'\n"
    "summary: >-\n"
    "  Consegna d'esempio: e' la prova che il coordinatore legge per datare e colorare una fase.\n"
    "findings: []\n"
)


def _scrivi(destinazione: Path, testo: str, creati: list, saltati: list) -> None:
    if destinazione.exists():
        saltati.append(str(destinazione))
        return
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text(testo, encoding="utf-8")
    creati.append(str(destinazione))


def scafold(root: Path, project: str, esempio: bool = False) -> tuple:
    creati, saltati = [], []
    for modello, destinazione, _ in MAPPATURA:
        if destinazione == "tasks.yaml" and modello == "tasks-esempio.yaml" and not esempio:
            continue
        if destinazione == "tasks.yaml" and modello == "tasks.yaml" and esempio:
            continue
        sorgente = MODELLI / modello
        testo = sorgente.read_text(encoding="utf-8").replace("__PROJECT__", project)
        if destinazione == "PARALLEL-PROMPTS.md" and not esempio:
            testo = QUADERNO_VUOTO
        _scrivi(root / destinazione, testo, creati, saltati)

    ruoli = ROOT / "agents" / "roles"
    for ruolo in sorted(ruoli.glob("*.md")):
        _scrivi(root / "agents" / "roles" / ruolo.name, ruolo.read_text(encoding="utf-8"), creati, saltati)
    _scrivi(root / "reports" / ".gitkeep", "", creati, saltati)

    if esempio:
        oggi = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
        _scrivi(root / "reports" / "ES01A" / "attempt-1.yaml", CONSEGNA_ESEMPIO.format(oggi=oggi), creati, saltati)
        _scrivi(
            root / "reports" / "ES01A.yaml",
            "schema: project-console-report-pointer/1.0\n"
            "task_id: ES01A\n"
            "attempt: 1\n"
            "report_ref: reports/ES01A/attempt-1.yaml\n"
            "report: reports/ES01A/attempt-1.yaml\n"
            "status: published\n"
            "verdict: pass\n"
            f"published_at: '{oggi}'\n",
            creati,
            saltati,
        )
        stato = root / "state.yaml"
        if stato.exists():
            testo = stato.read_text(encoding="utf-8")
            if "tasks: {}" in testo:
                stato.write_text(
                    testo.replace(
                        "tasks: {}",
                        "tasks:\n"
                        "  ES01A:\n"
                        "    status: accepted\n"
                        "    attempt: 1\n"
                        "    report: reports/ES01A/attempt-1.yaml\n",
                    ),
                    encoding="utf-8",
                )
    return creati, saltati


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destinazione", help="cartella del workspace (creata se non esiste)")
    parser.add_argument("--project", required=True, help="nome del progetto, quello in testa alla pagina")
    parser.add_argument("--esempio", action="store_true", help="aggiunge un'unita', una consegna e un prompt d'esempio")
    args = parser.parse_args(argv)
    root = Path(args.destinazione).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    creati, saltati = scafold(root, args.project, args.esempio)
    for path in creati:
        print(f"scritto   {path}")
    for path in saltati:
        print(f"lasciato  {path}  (esisteva gia')")
    print(f"\nworkspace pronto: {root}")
    print(
        f"primo passo: apri {root / 'FIRST-PROMPT.md'}, fai compilare la bozza "
        f"{root / 'constitution.md'} dall'agente, poi approva la Costituzione dal console"
    )
    print(f"avvialo con: python3 console/server.py --workspace {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
