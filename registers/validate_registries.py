#!/usr/bin/env python3
"""Controlla ogni registro YAML di un workspace con un parser vero.

Un registro rotto spegne gli strumenti di chi lavora: questo lo impedisce leggendo i file con
PyYAML (ancore e alias compresi), segnalando il primo errore con la sua riga, e cercando le chiavi
DUPLICATE nel testo — che il parse risolve in silenzio tenendo l'ultima. Sola lettura.

I registri controllati sono quelli PRESENTI: un workspace nuovo non deve possedere i dieci file di
un progetto maturo per essere valido.

Uso: python3 registers/validate_registries.py [--workspace /percorso/progetto]
"""
import argparse
import glob
import os
import sys

import yaml

LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)


def workspace_root(explicit=None):
    return os.path.abspath(
        explicit or os.environ.get("CONSOLE_WORKSPACE") or os.getcwd()
    )


class DuplicateKeyLoader(yaml.SafeLoader):
    """Unused placeholder kept for import compatibility."""


def duplicate_keys(path):
    """Report duplicate mapping keys by walking the composed node tree.

    The pack already lost a real decision to duplicate keys (a stale copy of an
    answered question overrode the answer on every read), so a plain parse is not
    enough: duplicates are legal YAML but never intentional here. Walking nodes
    keeps construction untouched.
    """
    problems = []

    def walk(node):
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode):
                    key = key_node.value
                    if key in seen:
                        problems.append((key, key_node.start_mark.line + 1))
                    seen.add(key)
                walk(value_node)
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                walk(child)

    with open(path, encoding="utf-8") as handle:
        for document in yaml.compose_all(handle, Loader=LOADER):
            if document is not None:
                walk(document)
    return problems

#: I registri che un workspace puo' avere. Si controllano SOLO quelli presenti: un progetto nuovo
#: non deve possedere i dieci file di un progetto maturo per essere valido.
REGISTRIES = (
    "console.yaml",
    "manifest.yaml",
    "state.yaml",
    "tasks.yaml",
    "agents.yaml",
    "questions.yaml",
    "decisions.yaml",
    "user_decisions.yaml",
    "requirements.yaml",
    "orchestration.yaml",
    "traceability.yaml",
    "scenarios.yaml",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="controlla i registri di un workspace")
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    args = parser.parse_args(argv)
    root = workspace_root(args.workspace)
    if not os.path.isdir(root):
        print(f"workspace non trovato: {root}")
        return 1
    failures = 0
    checked = 0
    for name in REGISTRIES:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            # Assente non e' rotto: si dichiara e si va avanti. Solo i registri che il workspace
            # dichiara di avere devono esserci.
            continue
        checked += 1
        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml.load(handle, Loader=LOADER)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f"line {mark.line + 1}" if mark is not None else "unknown line"
            print(f"INVALID {name}: {where}: {getattr(exc, 'problem', exc)}")
            failures += 1
            continue
        if data is None:
            print(f"EMPTY   {name}")
            failures += 1
            continue
        duplicates = duplicate_keys(path)
        if duplicates:
            for key, line in duplicates:
                print(f"DUPKEY  {name}:{line}: duplicate key {key!r}")
            failures += 1
            continue
        print(f"OK      {name} (top-level {type(data).__name__})")

    for relative in sorted(glob.glob(os.path.join(root, "templates", "*.yaml"))):
        checked += 1
        try:
            with open(relative, encoding="utf-8") as handle:
                yaml.load(handle, Loader=LOADER)
        except yaml.YAMLError as exc:
            print(f"INVALID {os.path.relpath(relative, root)}: {getattr(exc, 'problem', exc)}")
            failures += 1
            continue
        for key, line in duplicate_keys(relative):
            print(f"DUPKEY  {os.path.relpath(relative, root)}:{line}: duplicate key {key!r}")
            failures += 1

    print(f"checked={checked} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
