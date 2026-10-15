#!/usr/bin/env python3
"""Applica una TRANSIZIONE a un registro del pack facendo un edit testuale calcolato.

Perche' non riscrive il file con ``yaml.dump``: ``state.yaml`` porta commenti e un ordinamento
significativo, e riscriverlo con un serializer li distruggerebbe. L'edit e' quindi testuale, ma
l'indentazione NON e' scritta a mano: si calcola dall'ancora, che e' il difetto che il 2026-10-14 ha
spezzato quattro voci in due (le chiavi successive finivano dentro la voce nuova, il registro
restava formalmente valido con chiavi duplicate).

La transizione si descrive in un file YAML::

    schema: binche.ux-transition/1.0
    requested_by: /root
    requested_at: '2026-10-14T15:20:00+02:00'
    file: state.yaml
    anchor: "  UPL04ZE:"
    field: perimeter_decision_2026_10_14
    text: >-
      Testo del campo, ri-indentato dall'applicatore.

Un campo il cui valore e' una MAPPA si descrive con ``mapping`` invece di ``text``::

    field: ratification
    mapping:
      outcome: ratified
      by: /root/qa06rat1
      report: reports/QA06T-ratify/attempt-1.yaml
      dated: '2026-10-14T18:40:00+02:00'

Uso::

    apply_transitions.py <richiesta.yaml> [...]     # applica in ordine
    apply_transitions.py --dir pending-transitions  # applica tutte le richieste in coda

Se il file non e' piu' valido dopo l'edit, l'applicatore RIPRISTINA il backup ed esce in errore: la
validazione e' parte della scrittura, non un controllo che qualcuno deve ricordarsi di fare.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

#: Dove stanno i registri, se nessuno lo dice: il workspace da `$CONSOLE_WORKSPACE`, o la cartella
#: corrente. Il modulo non conosce nessun progetto.
PACK = Path(os.environ.get("CONSOLE_WORKSPACE") or Path.cwd()).expanduser().resolve()
#: Il nome neutro e quello storico: il primo progetto dava il suo nome allo schema, e rinominarlo
#: avrebbe invalidato tutte le richieste gia' depositate (e quelle che le corsie scrivono adesso).
#: Si accettano entrambi, e la coda li documenta tutti e due.
SCHEMA = "project-console-transition/1.0"
SCHEMI_ACCETTATI = (SCHEMA, "binche.ux-transition/1.0")


class TransitionError(Exception):
    """Una transizione non applicabile: si rifiuta, non si indovina."""


def read_transition(path):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TransitionError(f"{path}: la richiesta non e' una mappa YAML")
    if raw.get("schema") not in SCHEMI_ACCETTATI:
        raise TransitionError(
            f"{path}: schema atteso {' o '.join(SCHEMI_ACCETTATI)}, trovato {raw.get('schema')!r}"
        )
    for required in ("file", "anchor"):
        if not raw.get(required):
            raise TransitionError(f"{path}: campo obbligatorio mancante: {required}")
    if raw.get("item") is not None:
        if not isinstance(raw["item"], dict) or not raw["item"]:
            raise TransitionError(f"{path}: 'item' deve essere una mappa non vuota")
    elif raw.get("mapping") is not None:
        if not isinstance(raw["mapping"], dict) or not raw["mapping"]:
            raise TransitionError(f"{path}: 'mapping' deve essere una mappa non vuota")
        if not raw.get("field"):
            raise TransitionError(f"{path}: campo obbligatorio mancante: field")
    else:
        if not raw.get("field"):
            raise TransitionError(f"{path}: campo obbligatorio mancante: field")
        if "text" not in raw:
            raise TransitionError(f"{path}: manca il testo del campo")
    return raw


def locate_block(lines, anchor, occurrence=None):
    """Indice della riga dell'ancora.

    Senza ``occurrence`` l'ancora deve essere UNICA (zero o piu' corrispondenze si rifiutano).
    Con ``occurrence`` (1-based) si indirizza la n-esima: serve alle voci che il registro ripete
    per costruzione, come le claim della stessa fase prese, rilasciate e riprese piu' volte — la
    misura del 2026-10-14 e' che `- task_id: AUTO03T` compare due volte e la coda rifiutava la
    voce, lasciando il rilascio di una claim senza canale. Fuori intervallo si rifiuta.
    """
    hits = [index for index, line in enumerate(lines) if line.rstrip("\n") == anchor]
    if not hits:
        raise TransitionError(f"ancora non trovata: {anchor!r}")
    if occurrence is None and len(hits) > 1:
        raise TransitionError(f"ancora ambigua ({len(hits)} corrispondenze): {anchor!r}")
    if occurrence is None:
        return hits[0]
    if not 1 <= occurrence <= len(hits):
        raise TransitionError(
            f"occorrenza {occurrence} fuori intervallo: {len(hits)} corrispondenze per {anchor!r}"
        )
    return hits[occurrence - 1]


def indentation(line):
    return len(line) - len(line.lstrip(" "))


def block_bounds(lines, start):
    """Fine del blocco: la prima riga successiva con indentazione <= a quella dell'ancora."""
    base = indentation(lines[start])
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and indentation(line) <= base:
            break
        end += 1
    return end


def field_bounds(lines, start, block_end):
    """Fine dell'ESTENSIONE di un campo: la prima riga con indentazione <= alla sua.

    Serve a sostituire il solo campo, non cio' che lo segue nella voce. Misurato il
    2026-10-14 sulla prima versione: sostituendo `owner_agent` di una claim, `object` ed
    `exact_paths` sparivano in silenzio dal registro.
    """
    base = indentation(lines[start])
    end = start + 1
    while end < block_end:
        line = lines[end]
        if line.strip() and indentation(line) <= base:
            break
        end += 1
    return end


INT_OR_TOKEN = re.compile(r"-?[0-9]+|true|false|null|~")
PLAIN_FORBIDDEN_START = "-?:,[]{}#&*!|>'\"%@`"


def render_field(indent, field, text):
    """Un valore a UNA riga resta uno scalare a una riga.

    Il 2026-10-14 il reso a blocco (`>-`) era l'unico: su un campo token produce una stringa con
    newline finale (`status: >-` / `needs_changes`) e su un campo numerico la stringa `"2"` invece
    dell'intero, rompendo i lettori testuali (`tools/coord_status.py`) e `tools/check_pointers.py`.
    I valori a piu' righe restano come prima, in blocco.
    """
    pad = " " * indent
    body = " " * (indent + 2)
    lines = text.strip("\n").split("\n")
    if len(lines) > 1:
        rendered = [f"{pad}{field}: >-"]
        rendered.extend(f"{body}{line}".rstrip() for line in lines)
        return [item + "\n" for item in rendered]
    value = lines[0].strip()
    if not value:
        return [f"{pad}{field}: ''\n"]
    if INT_OR_TOKEN.fullmatch(value):
        return [f"{pad}{field}: {value}\n"]
    unsafe = (
        ": " in value
        or value.endswith(":")
        or value[0] in PLAIN_FORBIDDEN_START
        or " #" in value
    )
    if unsafe:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return [f'{pad}{field}: "{escaped}"\n']
    return [f"{pad}{field}: {value}\n"]


def render_value(text):
    """Le righe del VALORE di uno scalare: blocco se multi-riga, altrimenti una riga sola."""
    lines = str(text).strip("\n").split("\n")
    if len(lines) > 1:
        return [">-"] + [f"  {line.rstrip()}" for line in lines]
    value = lines[0].strip()
    if not value:
        return ["''"]
    if INT_OR_TOKEN.fullmatch(value):
        return [value]
    unsafe = (
        ": " in value
        or value.endswith(":")
        or value[0] in PLAIN_FORBIDDEN_START
        or " #" in value
    )
    if unsafe:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return [f'"{escaped}"']
    return [value]


def render_mapping_field(indent, field, mapping):
    """Un campo il cui valore e' una MAPPA (es. ``ratification: {outcome, by, report, dated}``).

    Perche' serve, misurato il 2026-10-14: la coda sapeva rendere solo scalari, quindi i campi
    ``ratification`` del registro esistevano soltanto perche' erano stati scritti a mano, e due atti
    di ratifica pubblicati (``reports/TODO01A-ratify/`` e ``reports/TODO01E-ratify/``) non avevano
    alcun canale per essere registrati. L'indentazione non e' scritta a mano piu' di quella degli
    altri campi: si calcola dall'ancora come per ``render_field``.
    """
    pad = " " * indent
    body = " " * (indent + 2)
    rendered = [f"{pad}{field}:\n"]
    for key, value in mapping.items():
        value_lines = render_value(value)
        rendered.append(f"{body}{key}: {value_lines[0]}\n")
        rendered.extend(f"{body}{line}\n" for line in value_lines[1:])
    return rendered


def render_item(indent, item):
    """Una voce NUOVA di una sequenza (una claim, un task) resa alla sua indentazione.

    La coda serve anche a DISPATCHARE, e ogni dispatch registra una claim prima di scrivere: fino
    al 2026-10-14 l'applicatore sapeva solo sostituire campi di voci esistenti, quindi l'unica
    operazione che il contratto pretende a ogni dispatch non aveva canale. Misurato: il titolare di
    AUTO03T ha chiesto al coordinamento il rilascio di una claim che la coda NON poteva
    indirizzare (ancora ripetuta) e la registrazione di una claim nuova non era possibile affatto.
    """
    pad = " " * indent
    body = " " * (indent + 2)
    rendered = []
    for index, (key, value) in enumerate(item.items()):
        prefix = f"{pad}- " if index == 0 else body
        if isinstance(value, (list, tuple)):
            rendered.append(f"{prefix}{key}:\n")
            for entry in value:
                entry_lines = render_value(entry)
                rendered.append(f"{body}- {entry_lines[0]}\n")
                rendered.extend(f"{body}  {line}\n" for line in entry_lines[1:])
            continue
        value_lines = render_value(value)
        rendered.append(f"{prefix}{key}: {value_lines[0]}\n")
        rendered.extend(f"{body}{line}\n" for line in value_lines[1:])
    return rendered


def item_already_present(lines, item):
    """Idempotenza delle voci: la stessa IDENTITA' non si duplica.

    L'identita' di una CLAIM e' la coppia (task_id, attempt). L'identita' di un FINDING e' il suo
    ``finding_id``: le voci di ``rework_findings`` non portano ``attempt``, quindi la guardia sulle
    claim le rifiutava TUTTE con «voce gia' presente» appena il task_id coincideva con una claim del
    registro. Misurato il 2026-10-15 alle 12:43 registrando i due finding di LOT03-READ-CAP, il cui
    task_id e' lo stesso della claim viva della tranche: il primo rifiuto e' arrivato sul campo
    ``finding_id`` correttamente compilato, cioe' il canale strutturato per registrare un finding era
    chiuso dal proprio guardiano. La correzione non tocca le claim: agisce solo sulle voci che
    DICHIARANO un ``finding_id``.
    """
    finding_id = str(item.get("finding_id", "")).strip()
    if finding_id:
        needle = f"finding_id: {finding_id}"
        return any(line.strip() == needle for line in lines)
    task_id = str(item.get("task_id", "")).strip()
    attempt = str(item.get("attempt", "")).strip()
    if not task_id:
        return False
    for index, line in enumerate(lines):
        if line.rstrip("\n") != f"- task_id: {task_id}":
            continue
        for follower in lines[index + 1 : index + 25]:
            if follower.strip().startswith("attempt:"):
                existing = follower.split(":", 1)[1].strip().strip("'\"")
                if not attempt or existing == attempt:
                    return True
                break
            if follower.startswith("- "):
                break
    return False


def apply_to_lines(lines, request):
    anchor = request["anchor"]
    start = locate_block(lines, anchor, request.get("occurrence"))
    end = block_bounds(lines, start)

    if request.get("item") is not None:
        item = request["item"]
        if item_already_present(lines, item):
            raise TransitionError(
                "voce gia' presente (task_id "
                f"{item.get('task_id')!r}, attempt {item.get('attempt')!r})"
            )
        rendered_item = render_item(indentation(lines[start]), item)
        where = request.get("position", "before")
        if where == "before":
            return lines[:start] + rendered_item + lines[start:]
        if where == "after":
            return lines[:end] + rendered_item + lines[end:]
        raise TransitionError("position deve essere 'before' o 'after'")

    field = request["field"]
    indent = indentation(lines[start]) + 2

    # Idempotenza: se il campo esiste gia' nel blocco lo si sostituisce, non lo si duplica.
    field_start = None
    for index in range(start + 1, end):
        stripped = lines[index].lstrip(" ")
        if stripped.startswith(f"{field}:"):
            field_start = index
            break

    if request.get("mapping") is not None:
        rendered = render_mapping_field(indent, field, request["mapping"])
    else:
        rendered = render_field(indent, field, str(request["text"]))
    if field_start is None:
        return lines[: start + 1] + rendered + lines[start + 1 :]
    field_end = field_bounds(lines, field_start, end)
    return lines[:field_start] + rendered + lines[field_end:]


def validate(pack):
    report = subprocess.run(
        # Il validatore e' questo repository, non una cartella del workspace: il workspace porta i
        # dati, il coordinatore porta il codice.
        [sys.executable, str(Path(__file__).resolve().parent / "validate_registries.py"),
         "--workspace", str(pack)],
        capture_output=True,
        text=True,
    )
    return report.returncode == 0, (report.stdout + report.stderr).strip()


def apply_request(request, dry_run=False, pack=None, validate_after=True):
    """Applica una richiesta. ``validate_after=False`` serve per una SEQUENZA di richieste: si
    valida una volta sola alla fine invece di pagare l'intero controllo dei registri per ogni
    campo (misurato: i sei campi di una risposta costano 27 s con la validazione per campo)."""
    pack = pack or PACK
    target = pack / request["file"]
    if not target.exists():
        raise TransitionError(f"{target} non esiste")
    original = target.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    updated = "".join(apply_to_lines(lines, request))
    if dry_run:
        return updated

    backup = Path(tempfile.mkstemp(prefix="transition-", suffix=".bak")[1])
    shutil.copy2(target, backup)
    try:
        target.write_text(updated, encoding="utf-8")
        try:
            yaml.safe_load(target.read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001
            raise TransitionError(f"YAML non valido dopo l'edit: {error}") from error
        if validate_after:
            ok, report = validate(pack)
            if not ok:
                raise TransitionError(f"registri non validi dopo l'edit:\n{report}")
    except Exception:
        shutil.copy2(backup, target)
        raise
    finally:
        backup.unlink(missing_ok=True)
    return updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", nargs="*", help="file di richiesta YAML")
    parser.add_argument("--dir", help="applica tutte le richieste in questa directory")
    parser.add_argument("--dry-run", action="store_true", help="mostra il risultato senza scrivere")
    parser.add_argument(
        "--workspace",
        "--pack-root",  # nome storico: lo usano le corsie dei progetti gia' avviati
        dest="workspace",
        help="radice del workspace da modificare (default: cwd o $CONSOLE_WORKSPACE)",
    )
    args = parser.parse_args(argv)
    pack = Path(args.workspace).resolve() if args.workspace else PACK

    paths = [Path(item) for item in args.requests]
    if args.dir:
        paths += sorted(Path(args.dir).glob("*.yaml"))
    if not paths:
        parser.error("nessuna richiesta: passare dei file oppure --dir")

    failures = 0
    for path in paths:
        try:
            request = read_transition(path)
            updated = apply_request(request, dry_run=args.dry_run, pack=pack)
        except TransitionError as error:
            print(f"RIFIUTATA {path}: {error}", file=sys.stderr)
            failures += 1
            continue
        if args.dry_run:
            print(f"--- {path} (dry-run) ---")
            print(updated)
        else:
            # La stampa non deve crashare dopo una scrittura RIUSCITA: un rc=1 su un edit
            # avvenuto farebbe riapplicare la richiesta da chi legge l'esito.
            if request.get("item") is not None:
                label = f"item({request['item'].get('task_id', '?')})"
            else:
                label = request["field"]
            print(f"APPLICATA {path}: {request['file']}#{label}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
