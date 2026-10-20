"""Le misure del metodo: primo colpo, rifacimenti, tempo, token e interventi umani.

Non stima e non inventa. Ogni numero viene da un report, da un atto di accettazione o da un
timestamp del registro; quando la fonte non esiste, la copertura lo dice.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "registers"), str(Path(__file__).resolve().parent)]

from registers import next_action  # noqa: E402
from workspace import Workspace  # noqa: E402

SCHEMA = "project-console-method-metrics/1.0"
TOKEN_ROOTS = ("usage", "token_usage", "execution_usage", "metrics")
TOKEN_FIELDS = {
    "input": ("input_tokens", "tokens_input", "prompt_tokens"),
    "output": ("output_tokens", "tokens_output", "completion_tokens"),
    "total": ("total_tokens", "tokens_total"),
}


def _load(path):
    try:
        return yaml.load(
            path.read_text(encoding="utf-8", errors="replace"),
            Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
        ) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    testo = str(value or "").strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+", testo):
        testo = testo.replace(",", "")
    elif not re.fullmatch(r"\d+(?:[.,]\d+)?", testo):
        return None
    try:
        return float(testo.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _when(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip().strip("'\"")
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            momento = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            continue
        return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
    return None


def _attempt_number(path):
    trovato = re.search(r"attempt-(\d+)\.ya?ml$", path.name)
    return int(trovato.group(1)) if trovato else 0


def _usage(document):
    for root_name in TOKEN_ROOTS:
        root = document.get(root_name)
        if not isinstance(root, dict):
            continue
        valori = {}
        for chiave, nomi in TOKEN_FIELDS.items():
            for nome in nomi:
                numero = _num(root.get(nome))
                if numero is not None:
                    valori[chiave] = int(numero)
                    break
        if "total" not in valori and ("input" in valori or "output" in valori):
            valori["total"] = valori.get("input", 0) + valori.get("output", 0)
        if valori:
            return valori
    return {}


def _negative(document):
    return next_action.verdict_kind(document.get("verdict")) == "negative"


def _user_acceptance(document):
    autore = str(document.get("authored_by") or document.get("agent_id") or "").lower()
    ruolo = str(document.get("role") or "").lower()
    verdetto = str(document.get("verdict") or "").lower()
    return (
        verdetto.startswith("accept")
        and (
            autore in ("utente", "user")
            or "accettazione dell'utente" in ruolo
        )
    )


def _phase_rows(workspace, state, tasks_doc):
    registrate = state.get("tasks") or {}
    claims = state.get("active_claims") or []
    righe = []
    for task in tasks_doc.get("tasks") or []:
        fase = str(task.get("id") or "")
        if not fase:
            continue
        cartella = workspace.reports_dir / fase
        tentativi = sorted(
            cartella.glob("attempt-*.yaml") if cartella.is_dir() else [],
            key=_attempt_number,
        )
        documenti = [_load(percorso) for percorso in tentativi]
        date = [
            momento
            for documento in documenti
            if (momento := _when(documento.get("published_at")))
        ]
        date += [
            momento
            for claim in claims
            if str(claim.get("task_id") or "") == fase
            for momento in (
                _when(claim.get("taken_at")),
                _when(claim.get("registered_at")),
            )
            if momento
        ]
        inizio = min(date) if date else None
        registrata = registrate.get(fase) or {}
        accettata = str(registrata.get("status") or "") == "accepted"
        accettazione = next(
            (documento for documento in documenti if _user_acceptance(documento)),
            None,
        )
        fine = (
            _when((accettazione or {}).get("published_at"))
            or _when(registrata.get("accepted_at") or registrata.get("accepted_on"))
            or (max(date) if accettata and date else None)
        )
        durata = (
            max(0.0, (fine - inizio).total_seconds())
            if inizio is not None and fine is not None and fine >= inizio
            else None
        )
        negativi = sum(1 for documento in documenti if _negative(documento))
        classificati = sum(
            1
            for documento in documenti
            if next_action.verdict_kind(documento.get("verdict"))
            in ("positive", "negative", "partial")
        )
        prima_dell_accettazione = [
            documento for documento in documenti if not _user_acceptance(documento)
        ]
        primo_colpo = bool(
            accettata
            and prima_dell_accettazione
            and all(
                next_action.verdict_kind(documento.get("verdict")) == "positive"
                for documento in prima_dell_accettazione
            )
        )
        usi = [_usage(documento) for documento in documenti]
        usi = [uso for uso in usi if uso]
        righe.append(
            {
                "phase": fase,
                "unit": str(task.get("unit_id") or ""),
                "status": str(registrata.get("status") or "pending"),
                "accepted": accettata,
                "attempts": len(tentativi),
                "negative_attempts": negativi,
                "classified_attempts": classificati,
                "unclassified_attempts": len(documenti) - classificati,
                "reworked": negativi > 0,
                "first_pass_accepted": primo_colpo,
                "duration_seconds": durata,
                "token_usage": usi,
                "user_acceptance": accettazione is not None,
                "acceptance_recorded": any(
                    str(chiave).startswith("accepted_from_act_")
                    for chiave in registrata
                ),
            }
        )
    return righe


def _human_interventions(workspace, tasks_doc, righe):
    accettazioni = sum(
        1
        for riga in righe
        if riga["user_acceptance"] or riga["acceptance_recorded"]
    )
    domande = _load(workspace.path(workspace.questions)).get("questions") or []
    risposte = sum(1 for voce in domande if voce.get("status") == "answered")
    decisioni_doc = _load(workspace.path(workspace.user_decisions))
    decisioni = sum(
        1
        for voce in decisioni_doc.get("decisions") or []
        if voce.get("status") == "closed"
    )
    messaggi = 0
    consegne = 0
    if workspace.inbox_dir.is_dir():
        for percorso in workspace.inbox_dir.glob("*.md"):
            testo = percorso.read_text(encoding="utf-8", errors="replace")
            testa = testo.split("---", 2)[1] if testo.startswith("---") else ""
            if "sender: utente" in testa:
                if "kind: prompt-consegnato" in testa:
                    consegne += 1
                else:
                    messaggi += 1
    return {
        "total": accettazioni + risposte + decisioni + messaggi + consegne,
        "acceptances": accettazioni,
        "answers": risposte,
        "decisions": decisioni,
        "notes": messaggi,
        "dispatches": consegne,
    }


def build(workspace, state=None, tasks_doc=None):
    state = state if state is not None else _load(workspace.state_path)
    tasks_doc = (
        tasks_doc
        if tasks_doc is not None
        else _load(workspace.path(workspace.tasks))
    )
    righe = _phase_rows(workspace, state, tasks_doc)
    con_report = [riga for riga in righe if riga["attempts"]]
    accettate_con_report = [riga for riga in con_report if riga["accepted"]]
    accettate_comparabili = [
        riga for riga in accettate_con_report if riga["classified_attempts"]
    ]
    con_verdetti = [riga for riga in con_report if riga["classified_attempts"]]
    prima_accettazione = sum(
        1 for riga in accettate_comparabili if riga["first_pass_accepted"]
    )
    rifatte = [riga for riga in con_verdetti if riga["reworked"]]
    durate = sorted(
        riga["duration_seconds"]
        for riga in accettate_con_report
        if riga["duration_seconds"] is not None
    )
    token_input = 0
    token_output = 0
    token_total = 0
    report_con_token = 0
    for riga in righe:
        if riga["token_usage"]:
            report_con_token += len(riga["token_usage"])
            for uso in riga["token_usage"]:
                token_input += int(uso.get("input") or 0)
                token_output += int(uso.get("output") or 0)
                token_total += int(uso.get("total") or 0)
    umani = _human_interventions(workspace, tasks_doc, righe)
    hotspot = sorted(
        (
            {
                "phase": riga["phase"],
                "negative_attempts": riga["negative_attempts"],
                "attempts": riga["attempts"],
            }
            for riga in rifatte
        ),
        key=lambda voce: (-voce["negative_attempts"], voce["phase"]),
    )[:5]
    rapporto_primo_colpo = (
        round(prima_accettazione / len(accettate_comparabili), 4)
        if accettate_comparabili
        else None
    )
    rapporto_rifacimenti = (
        round(len(rifatte) / len(con_verdetti), 4) if con_verdetti else None
    )
    avvisi = []
    if not report_con_token:
        avvisi.append(
            "Token non misurati: nessun report dichiara ancora `usage.input_tokens/output_tokens`."
        )
    if rapporto_primo_colpo is not None and rapporto_primo_colpo < 0.7:
        avvisi.append(
            "Meno del 70% delle fasi accettate è passato al primo colpo."
        )
    if rapporto_rifacimenti is not None and rapporto_rifacimenti > 0.3:
        avvisi.append(
            "Oltre il 30% delle fasi con esiti leggibili ha richiesto almeno un rifacimento."
        )
    non_classificati = sum(riga["unclassified_attempts"] for riga in righe)
    if non_classificati:
        avvisi.append(
            f"{non_classificati} tentativi non hanno un esito classificabile e restano fuori "
            "dai rapporti su primo colpo e rifacimenti."
        )
    return {
        "schema": SCHEMA,
        "project": workspace.project,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "phases": len(righe),
            "phases_with_reports": len(con_report),
            "accepted_with_reports": len(accettate_con_report),
            "first_pass_comparable": len(accettate_comparabili),
            "first_pass_accepted": prima_accettazione,
            "first_pass_rate": rapporto_primo_colpo,
            "rework_comparable": len(con_verdetti),
            "reworked_phases": len(rifatte),
            "rework_rate": rapporto_rifacimenti,
            "attempts": sum(riga["attempts"] for riga in righe),
            "negative_attempts": sum(riga["negative_attempts"] for riga in righe),
            "unclassified_attempts": non_classificati,
            "cycle_time": {
                "measured_phases": len(durate),
                "median_seconds": round(statistics.median(durate), 1) if durate else None,
                "p90_seconds": (
                    round(durate[min(len(durate) - 1, int(len(durate) * 0.9))], 1)
                    if durate
                    else None
                ),
            },
            "tokens": {
                "reports_measured": report_con_token,
                "reports_total": sum(riga["attempts"] for riga in righe),
                "input": token_input if report_con_token else None,
                "output": token_output if report_con_token else None,
                "total": token_total if report_con_token else None,
            },
            "human_interventions": umani,
        },
        "rework_hotspots": hotspot,
        "warnings": avvisi,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    esito = build(Workspace.load(args.workspace))
    if args.json:
        print(json.dumps(esito, ensure_ascii=False, indent=2))
    else:
        s = esito["summary"]
        print(
            f"primo colpo: {s['first_pass_accepted']}/{s['accepted_with_reports']} · "
            f"rifacimenti: {s['reworked_phases']}/{s['phases_with_reports']} · "
            f"interventi umani: {s['human_interventions']['total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
