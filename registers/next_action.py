#!/usr/bin/env python3
"""Il motore unico della prossima azione.

La pagina non interpreta piu' il verdetto. Questo modulo trasforma un atto pubblicato in UNA
decisione strutturata: accettare, tornare in E, passare a T/R, chiudere l'obbligo, aspettare o
chiedere una revisione umana. La stessa decisione alimenta la UI, l'attivazione e la chiusura.

Uso diagnostico::

    python3 registers/next_action.py --phase E --verdict needs_changes
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import apply_transitions
from workspace import Workspace, lock_file

SCHEMA = "project-console-next-action/1.0"
STANDARD_PHASES = ("A", "E", "T", "R")
FAST_PHASES = ("E", "T")
LANES = ("standard", "fast")
RISK_PATH_MARKERS = (
    "migration",
    "models.py",
    "settings",
    "security",
    "release",
    "deploy",
)
NEGATIVE_MARKERS = (
    "needs_changes",
    "needs-changes",
    "rejected",
    "failed",
    "failure",
)


def _text(value):
    return " ".join(str(value or "").strip().split())


def infer_lane(explicit=None, *, strict=False, risk=None, paths=None, changed_files=None):
    """La corsia rapida vale solo per una correzione piccola e non rischiosa."""
    dichiarata = str(explicit or "").strip().lower()
    rischi = [str(voce).strip().lower() for voce in (risk or []) if str(voce).strip()]
    percorsi = [str(voce) for voce in (paths or []) if str(voce).strip()]
    if strict or rischi:
        return "standard"
    if any(
        marcatore in percorso.lower()
        for percorso in percorsi
        for marcatore in RISK_PATH_MARKERS
    ):
        return "standard"
    if dichiarata in LANES:
        return dichiarata
    quanti = int(changed_files or len(percorsi) or 0)
    if dichiarata == "auto":
        # La corsia automatica resta prudente: senza perimetro misurabile non sceglie la via corta.
        return "fast" if 0 < quanti <= 2 else "standard"
    return "standard"


def phases_for(lane):
    return FAST_PHASES if lane == "fast" else STANDARD_PHASES


def next_after(phase, lane="standard"):
    ordine = phases_for(lane)
    fase = str(phase or "").upper()
    if fase not in ordine:
        return None
    indice = ordine.index(fase)
    return ordine[indice + 1] if indice + 1 < len(ordine) else None


def stages_from_report(item, lane=None):
    """Le fasi osservative della pagina, derivate dallo stesso atto che decide l'azione."""
    lane = lane or infer_lane(
        item.get("lane"),
        strict=item.get("strict") is True,
        risk=item.get("risk") or [],
        paths=item.get("paths") or [],
    )
    fasi = {fase: "missing" for fase in STANDARD_PHASES}
    if lane == "fast":
        fasi["A"] = "not_required"
        fasi["R"] = "not_required"
    phase = str(item.get("report_phase") or "").upper()
    kind = verdict_kind(item.get("report_verdict"))
    presa = bool(item.get("taken"))
    if item.get("report_closed"):
        for fase in phases_for(lane):
            fasi[fase] = "done"
        return fasi
    if phase:
        if lane != "fast":
            fasi["A"] = "done"
        ordine = phases_for(lane)
        if phase in ordine:
            for fase in ordine[: ordine.index(phase)]:
                fasi[fase] = "done"
            if kind == "negative":
                if phase == "E":
                    fasi["E"] = "in_progress" if presa else "partial"
                else:
                    # T/R hanno misurato e prodotto un verdetto: il loro atto esiste. Il ritorno
                    # in E rende E il punto aperto, non cancella la verifica già eseguita.
                    fasi[phase] = "done"
                    fasi["E"] = "in_progress" if presa else "partial"
            elif kind == "partial":
                fasi[phase] = "partial"
            elif kind == "positive":
                fasi[phase] = "done"
    elif presa:
        prima = phases_for(lane)[0]
        if lane != "fast":
            fasi["A"] = "done"
        fasi[prima] = "in_progress"
    return fasi


def verdict_kind(verdict):
    testo = _text(verdict).lower().replace(" ", "_")
    if not testo:
        return "none"
    if any(marcatore.replace("-", "_") in testo for marcatore in NEGATIVE_MARKERS):
        return "negative"
    if (
        testo.startswith(("pass", "accept", "ready_for", "delivered", "closed"))
        or "accept_unit" in testo
        or "closure_condition_met" in testo
    ):
        return "positive"
    if any(
        marcatore in testo
        for marcatore in (
            "remeasure_required",
            "measurement_delivered",
            "still_open",
            "partial",
        )
    ):
        return "partial"
    return "unknown"


def _action(
    code,
    label,
    *,
    phase=None,
    reason,
    accept_phase=None,
    after_phase=None,
    target_phase=None,
    primary="none",
):
    return {
        "schema": SCHEMA,
        "code": code,
        "label": label,
        "reason": reason,
        "phase": phase,
        "accept_phase": accept_phase,
        "after_phase": after_phase,
        "target_phase": target_phase or accept_phase or phase,
        "primary": primary,
    }


def decide_report(
    phase,
    verdict,
    *,
    lane="standard",
    closure_condition_met=None,
    obligation_status_after="",
):
    """La decisione per un atto pubblicato. Nessuna prosa: solo il prossimo gesto."""
    fase = str(phase or "").upper()
    lane = infer_lane(lane)
    kind = verdict_kind(verdict)
    closed = bool(
        closure_condition_met is True
        or str(obligation_status_after or "").strip().lower() == "closed"
    )
    if closed:
        return _action(
            "close_obligation",
            "Chiudi l'obbligo",
            phase=fase or "R",
            reason="Il report dichiara la condizione di chiusura soddisfatta.",
            primary="close",
        )
    if kind == "negative":
        return _action(
            "rework_e",
            "Correggi in E",
            phase="E",
            target_phase="E",
            reason=f"Il verdetto «{_text(verdict)}» respinge l'atto.",
            primary="prompt",
        )
    if fase == "E" and kind == "partial":
        return _action(
            "rework_e",
            "Completa E",
            phase="E",
            target_phase="E",
            reason="L'esecuzione è dichiarata parziale.",
            primary="prompt",
        )
    if "still_open" in _text(verdict).lower() and "remeasur" in _text(verdict).lower():
        return _action(
            "run_phase",
            "Passa alla verifica T",
            phase="T",
            target_phase="T",
            reason="La rimisura E è consegnata; ora serve la verifica indipendente.",
            primary="prompt",
        )
    if fase in ("A", "E", "T", "R") and kind == "positive":
        dopo = next_after(fase, lane)
        if dopo:
            return _action(
                "accept",
                f"Accetta {fase} e passa a {dopo}",
                phase=fase,
                accept_phase=fase,
                after_phase=dopo,
                reason=f"Il verdetto «{_text(verdict)}» è positivo.",
                primary="accept",
            )
        return _action(
            "accept",
            f"Accetta {fase} e chiudi",
            phase=fase,
            accept_phase=fase,
            reason=f"Il verdetto «{_text(verdict)}» è positivo e non restano fasi.",
            primary="accept",
        )
    if kind == "partial":
        return _action(
            "rework_e",
            "Completa E",
            phase="E",
            target_phase="E",
            reason="L'atto è consegnato ma incompleto.",
            primary="prompt",
        )
    if kind == "unknown":
        return _action(
            "review",
            "Serve una revisione",
            phase=fase or None,
            reason=f"Il verdetto «{_text(verdict)}» non è classificabile dal tool.",
            primary="review",
        )
    ordine = phases_for(lane)
    prima = ordine[0]
    return _action(
        "run_phase",
        f"Esegui {prima}",
        phase=prima,
        target_phase=prima,
        reason="Non esiste ancora un atto pubblicato.",
        primary="prompt",
    )


def for_obligation(item):
    """Decide per un obbligo/rifinitura già fuso con il suo ultimo report."""
    lane = infer_lane(
        item.get("lane"),
        strict=item.get("strict") is True,
        risk=item.get("risk") or [],
        paths=item.get("paths") or [],
    )
    if item.get("report_closed"):
        return _action(
            "close_obligation",
            "Chiudi l'obbligo",
            phase=str(item.get("report_phase") or "R").upper(),
            reason="L'ultimo report dichiara l'obbligo chiuso.",
            primary="close",
        )
    pending = item.get("pending_refinement") or {}
    if str(pending.get("status") or "").lower() == "delivered":
        fase = str(pending.get("phase") or "").upper()
        dopo = next_after(fase, lane)
        return _action(
            "accept",
            f"Accetta {pending.get('label') or fase}"
            + (f" e passa a {dopo}" if dopo else " e chiudi"),
            phase=fase,
            accept_phase=fase,
            after_phase=dopo,
            reason="L'atto è consegnato e aspetta l'accettazione umana.",
            primary="accept",
        )
    stages = item.get("stages") or {}
    if stages and all(stages.get(fase) == "done" for fase in phases_for(lane)):
        return _action(
            "review",
            "Le fasi sono concluse, manca la chiusura",
            phase="R" if lane == "standard" else "T",
            reason=(
                "Tutte le fasi richieste sono accettate, ma il report non dichiara "
                "soddisfatta la condizione di chiusura dell'obbligo."
            ),
            primary="review",
        )
    verdict = _text(item.get("report_verdict"))
    phase = str(item.get("report_phase") or "").upper()
    prossimo_report = str(item.get("next_report") or "")
    base_prossimo = Path(prossimo_report).parent.name.upper()
    prossima_fase = next(
        (
            fase
            for fase in ("A2", "E", "T", "R")
            if base_prossimo.endswith(fase)
        ),
        "",
    )
    if prossima_fase:
        item["next_stage"] = prossima_fase
    if (
        "obligation_open" in verdict.lower()
        and any(
            parola in _text(item.get("report_next")).lower()
            for parola in ("ripar", "ripinn", "proprietar", "owner")
        )
    ):
        return _action(
            "review",
            "Servono i proprietari",
            phase="OWNERS",
            reason="Il report assegna le riparazioni a unità proprietarie esterne.",
            primary="review",
        )
    if verdict or phase:
        decisa = decide_report(
            phase,
            verdict,
            lane=lane,
            closure_condition_met=item.get("report_closed"),
        )
        if decisa["code"] != "run_phase" or not item.get("next_stage"):
            return decisa
    stage = str(item.get("next_stage") or "").upper()
    if stage == "OWNERS":
        return _action(
            "review",
            "Servono i proprietari",
            phase="OWNERS",
            reason="Il report assegna le riparazioni a unità proprietarie esterne.",
            primary="review",
        )
    if stage in ("A2",):
        return _action(
            "run_phase",
            f"Esegui {stage}",
            phase=stage,
            target_phase=stage,
            reason="Il registro chiede il design della fase successiva.",
            primary="prompt",
        )
    if stage in phases_for(lane):
        return _action(
            "run_phase",
            f"Esegui {stage}",
            phase=stage,
            target_phase=stage,
            reason="Questa è la prima fase ancora aperta.",
            primary="prompt",
        )
    if item.get("taken"):
        fase = phases_for(lane)[0]
        return _action(
            "wait",
            f"{fase} è in corso",
            phase=fase,
            reason=f"Presa viva: {item.get('taken_by') or 'titolare non dichiarato'}.",
            primary="none",
        )
    return decide_report("", "", lane=lane)


def for_task(item):
    """Decide per una riga del percorso A/E/T/R, usando solo misure già presenti."""
    lane = infer_lane(item.get("lane"))
    verdict = _text(item.get("verdetto"))
    phase = str(item.get("phase") or "").upper()
    kind = verdict_kind(verdict)
    if item.get("live"):
        return _action(
            "wait",
            f"{phase} è in corso",
            phase=phase,
            reason=f"Presa viva: {item.get('owner') or 'titolare non dichiarato'}.",
            primary="none",
        )
    if item.get("attesa"):
        return _action(
            "wait",
            f"{phase} è in attesa",
            phase=phase,
            reason="Manca un prerequisito dichiarato.",
            primary="none",
        )
    if kind == "negative":
        fase = str(item.get("rifai") or "E").upper()
        return _action(
            "rework_e",
            f"Correggi in {fase}",
            phase=fase,
            target_phase=fase,
            reason=f"Il verdetto «{verdict}» respinge l'atto.",
            primary="prompt",
        )
    if verdict and kind == "unknown":
        return _action(
            "review",
            "Serve una revisione",
            phase=phase,
            reason=f"Il verdetto «{verdict}» non è classificabile dal tool.",
            primary="review",
        )
    if item.get("consegnata"):
        dopo = next_after(phase, lane)
        return _action(
            "accept",
            f"Accetta {phase}" + (f" e passa a {dopo}" if dopo else " e chiudi"),
            phase=phase,
            accept_phase=phase,
            after_phase=dopo,
            reason=f"Il verdetto «{verdict}» è positivo.",
            primary="accept",
        )
    if item.get("riservata"):
        return _action(
            "dispatch",
            "Consegna il prompt",
            phase=phase,
            target_phase=phase,
            reason="L'ordine esiste e nessuno ha ancora preso la fase.",
            primary="prompt",
        )
    if phase:
        return _action(
            "run_phase",
            f"Esegui {phase}",
            phase=phase,
            target_phase=phase,
            reason="La fase è la prima ancora aperta nel percorso.",
            primary="prompt",
        )
    return _action(
        "wait",
        "Nessuna azione",
        reason="Il registro non espone una fase aperta.",
    )


def for_owed(item):
    """Una direzione lasciata dal report, ridotta al primo atto realmente eseguibile."""
    codici = [voce for voce in item.get("codes") or [] if isinstance(voce, dict)]
    azionabili = [
        voce
        for voce in codici
        if not voce.get("live")
        and not voce.get("done")
        and not voce.get("attesa")
        and not voce.get("busy")
    ]
    if azionabili:
        codice = str(azionabili[0].get("code") or "")
        return _action(
            "run_phase",
            f"Esegui {codice}",
            phase=codice,
            target_phase=codice,
            reason="Questa è la prima fase nominata dal report che può partire adesso.",
            primary="prompt",
        )
    if codici and all(voce.get("live") or voce.get("done") for voce in codici):
        return _action(
            "wait",
            "Direzione già in lavorazione",
            reason="Le fasi nominate sono già in corso oppure hanno una consegna successiva.",
        )
    return _action(
        "review",
        "Direzione non ancora eseguibile",
        reason="Le fasi nominate aspettano un prerequisito o non sono determinate.",
        primary="review",
    )


def decorate_obligation(item):
    """Scrive la decisione nella voce e allinea i campi storici della pagina."""
    lane = infer_lane(
        item.get("lane"),
        strict=item.get("strict") is True,
        risk=item.get("risk") or [],
        paths=item.get("paths") or [],
    )
    if not item.get("stages"):
        item["stages"] = stages_from_report(item, lane)
    azione = for_obligation(item)
    item["next_action"] = azione
    item["lane_effective"] = lane
    if azione.get("phase"):
        item["next_stage"] = azione["phase"]
    item["stage_source"] = "next_action"
    item["stage_known"] = bool(azione.get("phase"))
    return item


def decorate_task(item):
    item["next_action"] = for_task(item)
    item["lane_effective"] = infer_lane(item.get("lane"))
    return item


def _load_yaml(path):
    return yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
    ) or {}


def _latest_obligation_report(workspace, obligation, prefix=""):
    cartella = workspace.root / workspace.deliverable_prefix
    candidati = []
    for percorso in cartella.glob(f"{prefix or obligation}*"):
        if percorso.is_dir():
            candidati.extend(percorso.glob("attempt-*.yaml"))
        elif percorso.suffix in (".yaml", ".yml"):
            candidati.append(percorso)
    if not candidati:
        return None, {}
    percorso = max(
        candidati,
        key=lambda voce: (
            1 if voce.name.startswith("attempt-") else 0,
            voce.stat().st_mtime_ns,
        ),
    )
    return percorso, _load_yaml(percorso)


def close_obligation(workspace, obligation_id, report_path=None):
    """Chiude una voce `execution_attempts` solo se il report lo dichiara chiuso."""
    stato = _load_yaml(workspace.state_path)
    voci = [
        voce
        for voce in stato.get("execution_attempts") or []
        if isinstance(voce, dict)
        and str(voce.get("obligation_id") or "") == str(obligation_id)
    ]
    if not voci:
        raise ValueError(f"obbligo non presente in {workspace.state}: {obligation_id}")
    if str(voci[-1].get("status") or "").lower() == "closed" or voci[-1].get("closure_kind"):
        return {"already_closed": True, "obligation": obligation_id}
    percorso = workspace.path(report_path) if report_path else None
    documento = _load_yaml(percorso) if percorso and percorso.is_file() else {}
    if not documento:
        percorso, documento = _latest_obligation_report(
            workspace, str(obligation_id), str(obligation_id)
        )
    if not documento:
        raise ValueError(f"nessun report leggibile per {obligation_id}")
    chiuso = bool(
        documento.get("closure_condition_met") is True
        or str(documento.get("obligation_status_after") or "").lower() == "closed"
    )
    if not chiuso:
        raise ValueError(
            f"{percorso.relative_to(workspace.root)} non dichiara l'obbligo chiuso"
        )
    relativo = str(percorso.relative_to(workspace.root))
    quando = str(
        documento.get("published_at")
        or datetime.now().astimezone().isoformat(timespec="seconds")
    )
    evidenza = (
        f"Chiusura automatica dal report {relativo}: "
        f"{_text(documento.get('verdict')) or 'condizione di chiusura soddisfatta'}."
    )
    anchor = f"- obligation_id: {obligation_id}"
    # L'occorrenza è 1-based fra le righe identiche, come nell'applicatore.
    quante = 0
    for voce in stato.get("execution_attempts") or []:
        if str((voce or {}).get("obligation_id") or "") == str(obligation_id):
            quante += 1
    campi = (
        ("status", "closed"),
        ("closed_at", quando),
        ("closed_by", "utente, dalla pagina Adesso"),
        ("closure_declaration_ref", relativo),
        ("closure_evidence", evidenza),
        ("closure_kind", "automatic_from_published_report"),
    )
    richieste = [
        {
            "schema": apply_transitions.SCHEMA,
            "file": workspace.state,
            "anchor": anchor,
            "occurrence": max(quante, 1),
            "field": campo,
            "text": valore,
        }
        for campo, valore in campi
    ]
    with open(lock_file(workspace.root), "a+") as maniglia:
        fcntl.flock(maniglia, fcntl.LOCK_EX)
        descrittore, percorso_copia = tempfile.mkstemp(
            prefix="next-action-close-", suffix=".bak"
        )
        os.close(descrittore)
        copia = Path(percorso_copia)
        shutil.copy2(workspace.state_path, copia)
        try:
            for indice, richiesta in enumerate(richieste):
                apply_transitions.apply_request(
                    richiesta,
                    pack=workspace.root,
                    validate_after=indice == len(richieste) - 1,
                )
        except Exception:
            shutil.copy2(copia, workspace.state_path)
            raise
        finally:
            copia.unlink(missing_ok=True)
            fcntl.flock(maniglia, fcntl.LOCK_UN)
    return {
        "obligation": obligation_id,
        "closed": True,
        "report": relativo,
        "closed_at": quando,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", default="")
    parser.add_argument("--verdict", default="")
    parser.add_argument("--lane", choices=LANES, default="standard")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    esito = decide_report(args.phase, args.verdict, lane=args.lane)
    if args.json:
        print(json.dumps(esito, ensure_ascii=False))
    else:
        print(f"{esito['code']}: {esito['label']} — {esito['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
