#!/usr/bin/env python3
"""Controllo di sanita' prima di committare: i moduli si importano e le loro porte ci sono.

Perche' esiste: il 2026-10-15 una sostituzione fatta con una regex su `registers/activate.py` ha
**cancellato le funzioni finali** del file (`attiva`, `aggiorna_ordini`, `rilascia`, `main`). Il
file restava sintatticamente valido — `ast.parse` passava — e il commit e' andato avanti; il difetto
e' comparso solo quando l'utente ha premuto «Attiva», con un errore che parlava di un modulo senza
quella funzione.

`ast.parse` non basta: questo controlla che le porte di ogni modulo esistano e che le righe di
comando rispondano. Un minuto, e si lancia prima di ogni commit.

Uso: python3 selfcheck.py
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: Per ogni modulo, le porte che DEBBONO esserci: sono quelle che la pagina e le corsie chiamano.
PORTE = {
    "workspace.py": ["Workspace", "lock_file"],
    "registers/apply_transitions.py": ["apply_request", "read_transition", "main"],
    "registers/validate_registries.py": ["main"],
    "registers/next_prompts.py": ["build", "configure", "render_html", "main"],
    "registers/activate.py": ["attivabili", "attiva", "rilascia", "aggiorna_ordini", "elenco", "main"],
    "registers/handoff.py": ["dichiarazioni", "lacune", "dovuto", "scrivi", "main"],
    "registers/inbox.py": ["voci", "archivia", "trova", "chiudi", "non_lavorate", "main"],
    "registers/rework.py": ["per_fase", "frase", "stabile", "main"],
    "registers/coda.py": ["leggi", "applica", "richieste", "main"],
    "registers/preflight.py": ["leggi", "main"],
    "registers/accetta.py": ["per", "main"],
    "registers/mandate.py": ["componi", "per", "impronta", "da_ordine", "main"],
    "registers/static_view.py": ["render", "main"],
    "registers/sync_phases.py": ["inserisci", "main"],
    "console/timeline.py": ["build", "configure", "repository_facts", "main"],
    "console/recap.py": ["costruisci", "main"],
    "console/refinements.py": ["load", "merge", "stage_map", "next_phase", "latest_report", "main"],
    "console/test_refinements.py": ["main"],
    "console/server.py": ["main", "ReviewState"],
}

#: Le righe di comando che devono rispondere (senza workspace: solo `--help`).
COMANDI = (
    [sys.executable, "scaffold.py", "--help"],
    [sys.executable, "registers/activate.py", "--help"],
    [sys.executable, "registers/handoff.py", "--help"],
    [sys.executable, "registers/inbox.py", "--help"],
    [sys.executable, "registers/rework.py", "--help"],
    [sys.executable, "registers/coda.py", "--help"],
    [sys.executable, "registers/preflight.py", "--help"],
    [sys.executable, "registers/accetta.py", "--help"],
    [sys.executable, "registers/mandate.py", "--help"],
    [sys.executable, "registers/sync_phases.py", "--help"],
    [sys.executable, "console/server.py", "--help"],
)


def main():
    problemi = []
    for nome, porte in PORTE.items():
        percorso = ROOT / nome
        if not percorso.is_file():
            problemi.append(f"{nome}: manca il file")
            continue
        try:
            albero = ast.parse(percorso.read_text(encoding="utf-8"), nome)
        except SyntaxError as errore:
            problemi.append(f"{nome}: non si legge: {errore}")
            continue
        # Un nome e' definito se compare come def/class OPPURE come assegnazione (i moduli hanno
        # anche costanti pubbliche): si guarda l'insieme dei nomi legati al livello del modulo.
        definiti = set()
        for nodo in albero.body:
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definiti.add(nodo.name)
            elif isinstance(nodo, ast.Assign):
                for bersaglio in nodo.targets:
                    if isinstance(bersaglio, ast.Name):
                        definiti.add(bersaglio.id)
            elif isinstance(nodo, ast.ImportFrom):
                definiti.update(alias.asname or alias.name for alias in nodo.names)
            elif isinstance(nodo, (ast.Import, ast.Try, ast.If, ast.For)):
                definiti.update(
                    sub.name
                    for sub in ast.walk(nodo)
                    if isinstance(sub, (ast.FunctionDef, ast.ClassDef))
                )
        mancanti = [porta for porta in porte if porta not in definiti]
        if mancanti:
            problemi.append(f"{nome}: porte mancanti {mancanti}")
        else:
            print(f"ok    {nome}  ({len(porte)} porte)")
    for comando in COMANDI:
        esito = subprocess.run(comando, cwd=str(ROOT), capture_output=True, text=True)
        if esito.returncode != 0:
            problemi.append(f"{' '.join(comando)}: rc={esito.returncode} {esito.stderr.strip()[:120]}")
        else:
            print(f"ok    {' '.join(comando[1:])}")
    if problemi:
        print("\nPROBLEMI:")
        for problema in problemi:
            print(f"  {problema}")
        return 1
    print("\ntutto a posto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
