"""Il contratto di un workspace: come si chiama ogni cosa che il coordinatore legge e scrive.

Il codice non conosce nessun progetto. Conosce QUESTI nomi, e ogni nome si puo' sovrascrivere
dichiarandolo in `console.yaml` nella radice del workspace. I valori predefiniti sono la
convenzione nata sul primo progetto che ha usato questo strumento, cosi' un workspace scritto a
mano funziona senza configurazione e un progetto nuovo la cambia in un file solo.

Un workspace e' quindi solo una cartella di dati. Lo stesso coordinatore puo' servire quanti
workspace vuoi, anche contemporaneamente, senza sapere niente di nessuno di essi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

CONFIG_NAME = "console.yaml"


@dataclass(frozen=True)
class Workspace:
    """La radice di un progetto e i nomi dei suoi registri."""

    root: Path
    project: str = "Progetto"
    surface: str = "verifica del percorso"
    state: str = "state.yaml"
    tasks: str = "tasks.yaml"
    questions: str = "questions.yaml"
    decisions: str = "decisions.yaml"
    user_decisions: str = "user_decisions.yaml"
    reports: str = "reports"
    queue: str = "PARALLEL-PROMPTS.md"
    transitions: str = "pending-transitions"
    brand: str = "brand"
    view: str = "STATUS.html"
    deliverable_prefix: str = "reports/"
    phases: tuple = ("A", "E", "T", "R")
    #: I comandi che una persona esegue a mano per verificare il progetto da sola (label, comando).
    #: Non si indovinano: un workspace che non li dichiara non ne mostra.
    verify: tuple = ()

    # ------------------------------------------------------------- percorsi
    def path(self, name: str) -> Path:
        return self.root / name

    @property
    def state_path(self) -> Path:
        return self.path(self.state)

    @property
    def reports_dir(self) -> Path:
        return self.path(self.reports)

    @property
    def brand_dir(self) -> Path:
        return self.path(self.brand)

    @property
    def transitions_dir(self) -> Path:
        return self.path(self.transitions)

    def describe(self) -> str:
        return f"{self.project} — {self.surface} ({self.root})"

    # --------------------------------------------------------------- carica
    @classmethod
    def load(cls, root=None, config_name: str = CONFIG_NAME) -> "Workspace":
        """Il workspace da `console.yaml`, o quello che si deduce dalla cartella."""
        base = Path(root or os.environ.get("CONSOLE_WORKSPACE") or Path.cwd()).expanduser()
        if not base.is_dir():
            raise SystemExit(f"workspace non trovato: {base}")
        base = base.resolve()
        data = {}
        config = base / config_name
        if config.exists():
            loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise SystemExit(f"{config}: deve contenere una mappa di chiavi")
            data = loaded
        known = {field.name for field in fields(cls)} - {"root"}
        unknown = sorted(set(data) - known)
        if unknown:
            # Una chiave scritta male e ignorata in silenzio e' un progetto che sembra configurato
            # e non lo e': qui si rifiuta, e si dice quali chiavi esistono.
            raise SystemExit(
                f"{config}: chiavi sconosciute {unknown}; ammesse: {sorted(known)}"
            )
        if "phases" in data:
            data["phases"] = tuple(str(item) for item in data["phases"])
        if "verify" in data:
            data["verify"] = tuple(
                (str(item.get("label", "verifica")), str(item.get("command", "")))
                if isinstance(item, dict)
                else (str(item), "")
                for item in data["verify"] or []
            )
        return cls(root=base, **data)

    def writable_check(self) -> list:
        """Cosa manca perche' il workspace sia completo: si dichiara, non si crea di nascosto."""
        missing = [
            name
            for name in (self.state, self.tasks, self.queue)
            if not self.path(name).exists()
        ]
        if not self.reports_dir.is_dir():
            missing.append(self.reports)
        return missing
