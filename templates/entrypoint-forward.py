#!/usr/bin/env python3
"""Modello di PUNTO D'INGRESSO che inoltra al coordinatore.

Copia questo file dove il progetto ha il suo comando storico (per esempio
`<progetto>/review/server.py`), sostituisci `CONSOLE_PATH` e il resto viene da se': il comando che
si e' imparato continua a funzionare, e la pagina e' quella del coordinatore.

Perche' un inoltro e non una copia: il 2026-10-15 una copia vecchia del coordinatore e' rimasta in
esecuzione dentro un progetto mentre il codice andava avanti altrove. Chi apriva quella pagina si
e' trovato un'interfaccia senza gli strumenti — pulsanti che fallivano, nessun modo di far partire
una fase — e il tempo perso non si e' capito fino a quando non si e' guardato *quale* processo
ascoltava sulla porta. Due copie divergono; un inoltro no.

Il workspace e' la cartella che contiene i registri: si deduce da dove sta questo file, oppure si
dichiara a mano.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Dove sta il coordinatore (il repository di `project-console`).
CONSOLE_PATH = Path("/percorso/project-console")

#: Il workspace servito: di solito la cartella che contiene i registri. Si puo' dichiarare a mano.
WORKSPACE = Path(__file__).resolve().parent.parent


def main(argv=None):
    argomenti = list(argv if argv is not None else sys.argv[1:])
    entry = CONSOLE_PATH / "console" / "server.py"
    if not entry.exists():
        print(
            f"il coordinatore non e' in {CONSOLE_PATH}.\n"
            f"Avvialo con: python3 {entry} --workspace {WORKSPACE}"
        )
        return 1
    print(f"coordinatore: {CONSOLE_PATH}")
    print(f"workspace:    {WORKSPACE}")
    return subprocess.call(
        [sys.executable, str(entry), "--workspace", str(WORKSPACE), *argomenti]
    )


if __name__ == "__main__":
    raise SystemExit(main())
