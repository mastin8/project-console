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


def lock_file(root) -> str:
    """Il file di lock dei registri di un workspace.

    Perche' sta qui e non in ogni modulo: due scrittori sugli stessi registri devono serializzarsi
    sullo STESSO file, altrimenti il lock non serve a niente. Il nome si puo' dichiarare
    (`CONSOLE_REGISTRY_LOCK`), e si accetta anche `BINCHE_REGISTRY_LOCK` perche' e' quello che usano
    i progetti gia' avviati: la pagina e le corsie devono prendere lo stesso lucchetto.
    """
    import hashlib
    import os

    dichiarato = os.environ.get("CONSOLE_REGISTRY_LOCK") or os.environ.get("BINCHE_REGISTRY_LOCK")
    if dichiarato:
        return dichiarato
    return f"/tmp/project-console-{hashlib.sha1(str(root).encode()).hexdigest()[:12]}.lock"


@dataclass(frozen=True)
class Workspace:
    """La radice di un progetto e i nomi dei suoi registri."""

    root: Path
    project: str = "Progetto"
    surface: str = "verifica del percorso"
    state: str = "state.yaml"
    tasks: str = "tasks.yaml"
    constitution: str = "constitution.md"
    first_prompt: str = "FIRST-PROMPT.md"
    onboarding_findings: str = "onboarding-findings.yaml"
    onboarding_questions: str = "onboarding-questions.md"
    questions: str = "questions.yaml"
    decisions: str = "decisions.yaml"
    user_decisions: str = "user_decisions.yaml"
    reports: str = "reports"
    refinements: str = "refinements.yaml"
    plan_approval: str = "plan-approval.yaml"
    queue: str = "PARALLEL-PROMPTS.md"
    transitions: str = "pending-transitions"
    #: La posta in arrivo: i messaggi depositati interi, uno per file. Vedi `registers/inbox.py`.
    inbox: str = "inbox"
    brand: str = "brand"
    view: str = "STATUS.html"
    deliverable_prefix: str = "reports/"
    #: Gli schemi che il coordinatore SCRIVE. Un progetto con un formato suo di report lo dichiara qui
    #: e l'atto di accettazione usa il suo, invece di imporgli quello di questa piattaforma.
    report_schema: str = "project-console-report/1.0"
    pointer_schema: str = "project-console-report-pointer/1.0"
    #: Cancelli dei progetti nuovi. I workspace storici restano compatibili finché non li accendono.
    require_usage: bool = False
    require_git_provenance: bool = False
    require_plan_approval: bool = False
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
    def refinements_path(self) -> Path:
        return self.path(self.refinements)

    @property
    def constitution_path(self) -> Path:
        return self.path(self.constitution)

    @property
    def plan_approval_path(self) -> Path:
        return self.path(self.plan_approval)

    @property
    def first_prompt_path(self) -> Path:
        return self.path(self.first_prompt)

    @property
    def onboarding_findings_path(self) -> Path:
        return self.path(self.onboarding_findings)

    @property
    def onboarding_questions_path(self) -> Path:
        return self.path(self.onboarding_questions)

    @property
    def brand_dir(self) -> Path:
        return self.path(self.brand)

    @property
    def transitions_dir(self) -> Path:
        return self.path(self.transitions)

    @property
    def inbox_dir(self) -> Path:
        return self.path(self.inbox)

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
