#!/usr/bin/env python3
"""Genera la vista statica leggibile di un workspace (default: `STATUS.html` nella sua radice).

Perche' esiste: i registri sono il posto giusto per la macchina e quello sbagliato per una
persona: YAML grandi con centinaia di voci storiche dentro. Questa pagina e' la traduzione dei
registri in cinque domande, nell'ordine in cui una persona le fa:

  1. Cosa aspetta ME?              (domande aperte, una per volta)
  2. Cosa posso far partire io?    (i prompt del quaderno, con lo stato ricavato)
  3. Cosa sta succedendo ADESSO?   (claim vive, chi scrive cosa)
  4. A che punto siamo?            (unita' e fasi, con i conteggi)
  5. Come verifico io?             (i comandi dei gate di prodotto, da eseguire a mano)

La sezione 2 non si scrive a mano: la regola sta in `registers/next_prompts.py`, la stessa usata
dalla pagina JavaScript del coordinatore, cosi' le due viste non possono raccontare cose diverse.

Il conteggio delle unita' accettate NON viene ricalcolato qui: si importa la regola del
coordinatore (`tools/coord_status.py`). Il 2026-10-14 questa pagina stampava 49 mentre il
coordinatore contava 52, perche' la pagina pretendeva TUTTE le fasi accettate mentre il counter
chiede la sola ratifica R: due implementazioni della stessa regola divergono, quindi la pagina
legge quella del coordinatore e DICHIARA la differenza invece di nasconderla.

Sola lettura: legge i registri e scrive un solo file HTML statico. Nessuna dipendenza esterna,
nessuna rete. Uso: python3 registers/static_view.py --workspace /percorso/progetto [--out STATUS.html]
"""
from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import next_prompts  # noqa: E402 - script fratello: una sola implementazione della regola
from workspace import Workspace  # noqa: E402 - il contratto dei nomi, uno per tutto il repo

#: Dove sta il workspace: `$CONSOLE_WORKSPACE`, o la cartella corrente. Nessun progetto cablato.
PACK = Path(os.environ.get("CONSOLE_WORKSPACE") or Path.cwd()).expanduser().resolve()
WS = Workspace(root=PACK)
LIVE_STATUSES = ("active", "taken", "pre_registered", "ready", "active_extension")
DONE_STATUSES = ("accepted",)
PHASE_ORDER = ("A", "E", "T", "R")

#: I comandi di verifica NON stanno qui: li dichiara il workspace (`verify:` in `console.yaml`).
#: Un elenco cablato sarebbe l'elenco di un progetto, e questo strumento ne serve molti.
VERIFY_COMMANDS = []


def load(name):
    path = PACK / name
    if not path.exists():
        return None
    # I registri si scrivono con `open(path, "w")`: per una frazione di secondo il file e' VUOTO, e
    # un lettore che non riprova legge `None` — misurato il 2026-10-15 alle 09:37 su QUESTO tool, che
    # ha reso una pagina con «accettate 0» e «Nessuna domanda aperta: niente aspetta te» mentre una
    # corsia scriveva il registro. Un registro vuoto non e' «un registro senza contenuto»: e' una
    # lettura strappata. Si riprova, e se resta vuoto si esce con errore invece di pubblicare una
    # pagina che dice il falso a chi la legge per decidere.
    for _ in range(10):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if data:
            return data
        time.sleep(0.2)
    raise SystemExit(f"registro illeggibile o vuoto dopo 10 tentativi: {path}")


def unit_progress(tasks_doc, state):
    """(unita' totali, accettate, tabella unita' -> fasi e stato) dai due registri."""
    statuses = state.get("tasks", {}) if state else {}
    units = {}
    for task in (tasks_doc or {}).get("tasks", []) or []:
        unit = task.get("unit_id")
        task_id = task.get("id")
        if not unit or not task_id:
            continue
        units.setdefault(unit, {})[task_id] = (statuses.get(task_id) or {}).get("status", "pending")
    accepted = [
        unit
        for unit, phases in units.items()
        if phases and all(value in DONE_STATUSES for value in phases.values())
    ]
    return units, accepted


def live_claims(state):
    claims = (state or {}).get("active_claims", []) or []
    return [c for c in claims if c.get("status") in LIVE_STATUSES and not c.get("released_at")]


def coordinator_ratified():
    """(unita' con la RATIFICA accettata, totale) — la regola e' del workspace, non di un progetto.

    L'ultima fase dell'elenco (`R` per convenzione) e' quella che accetta l'unita' INTERA: le
    altre accettano un handoff. Se un'unita' dichiara `children`, la sua ratifica pretende quella
    di ogni figlio. E' l'unica regola con cui il conto «accettate» viene calcolato due volte — una
    stretta, una per ratifica — e le due si dichiarano invece di confondersi.
    """
    registry = load(WS.tasks) or {}
    units = registry.get("units") or []
    states = (load(WS.state) or {}).get("tasks") or {}
    by_id = {unit.get("id"): unit for unit in units}
    ratifica = WS.phases[-1]

    def accepted(unit_id):
        if states.get(f"{unit_id}{ratifica}", {}).get("status") != "accepted":
            return False
        for child in (by_id.get(unit_id) or {}).get("children") or []:
            if not accepted(child):
                return False
        return True

    ratified = [unit.get("id") for unit in units if accepted(unit.get("id"))]
    return ratified, len(units)


def open_questions(questions):
    return [q for q in (questions or {}).get("questions", []) or [] if q.get("status") == "asked"]


def render(
    out_path,
    state,
    questions,
    tasks_doc,
    decisions,
    ratified=None,
    user_decisions=None,
    next_entries=None,
    verify=None,
):
    units, accepted = unit_progress(tasks_doc, state)
    ratified_ids, ratified_total = ratified if ratified else (None, None)
    statuses = Counter()
    for phases in units.values():
        statuses.update(phases.values())
    claims = live_claims(state)
    waiting = open_questions(questions)
    last_decisions = ((decisions or {}).get("decisions", []) or [])[-3:]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = subprocess.run(
        ["sha256sum", str(PACK / WS.state)], capture_output=True, text=True
    ).stdout.split(" ")[0][:12]
    commands = list(verify if verify is not None else VERIFY_COMMANDS)

    def esc(value):
        return html.escape(str(value if value is not None else ""))

    parts = [
        "<!doctype html>",
        '<html lang="it"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Stato del pack UX</title>",
        "<style>",
        ":root{--b:#111;--m:#666;--l:#e5e5e5;--g:#0a7d33;--y:#b06a00;--r:#b3261e}",
        "*{box-sizing:border-box}body{font:15px/1.5 system-ui,sans-serif;color:var(--b);"
        "margin:0;padding:32px;max-width:1100px}",
        "h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:34px 0 10px;"
        "border-bottom:1px solid var(--l);padding-bottom:6px}",
        ".meta{color:var(--m);font-size:13px;margin-bottom:8px}",
        "table{border-collapse:collapse;width:100%;font-size:14px}",
        "th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--l);vertical-align:top}",
        "th{color:var(--m);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}",
        "code{background:#f4f4f4;padding:2px 5px;border-radius:3px;font-size:13px}",
        "pre{background:#f8f8f8;border:1px solid var(--l);padding:10px;overflow-x:auto;",
        "font-size:13px;border-radius:4px}",
        ".pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;"
        "border:1px solid var(--l)}",
        ".ok{color:var(--g)}.warn{color:var(--y)}.bad{color:var(--r)}",
        ".card{border:1px solid var(--l);border-radius:6px;padding:14px;margin:10px 0}",
        ".q{font-size:16px;font-weight:600;margin-bottom:6px}",
        "</style></head><body>",
        "<h1>Stato del pack UX</h1>",
        f'<div class="meta">generato {esc(generated)} &middot; state.yaml '
        f"<code>{esc(stamp)}</code> &middot; {len(units)} unita' &middot; "
        f"{sum(statuses.values())} fasi tracciate</div>",
    ]

    # 1. Cosa aspetta l'utente.
    parts.append("<h2>1. Cosa aspetta te</h2>")
    if waiting:
        for question in waiting:
            parts.append('<div class="card">')
            parts.append(f'<div class="q">{esc(question.get("topic"))}</div>')
            parts.append(f"<p>{esc(question.get('question'))}</p>")
            answers = question.get("suggested_answers") or []
            if answers:
                parts.append("<ul>")
                for answer in answers:
                    parts.append(f"<li>{esc(answer)}</li>")
                parts.append("</ul>")
            parts.append(
                f'<div class="meta">aperta il {esc(question.get("asked_on"))} &middot; '
                f"blocca {esc(', '.join(question.get('affected_tasks') or []))}</div>"
            )
            parts.append("</div>")
    else:
        parts.append('<p class="ok">Nessuna domanda aperta: niente aspetta te.</p>')

    # Le decisioni di GOVERNO che appartengono all'utente e non a un agente. Non stanno in
    # `questions.yaml` perche' quella ammette una sola domanda attiva per volta, e queste non sono
    # domande di un task: senza questa sezione la pagina diceva «niente aspetta te» mentre tre
    # scelte di governo erano ferme.
    gov = ((user_decisions or {}).get("decisions", []) or [])
    gov = [item for item in gov if item.get("status") != "closed"]
    if gov:
        parts.append("<h3>Decisioni di governo (non sono domande di un task)</h3>")
        for item in gov:
            parts.append('<div class="card">')
            parts.append(f'<div class="q">{esc(item.get("topic"))}</div>')
            parts.append(f"<p>{esc(item.get('question'))}</p>")
            evidence = item.get("evidence")
            if evidence:
                parts.append(f'<p class="meta">{esc(evidence)}</p>')
            why = item.get("why_yours")
            if why:
                parts.append(f'<p class="meta">{esc(why)}</p>')
            note = item.get("queue_note")
            if note:
                parts.append(f'<p class="meta">{esc(note)}</p>')
            parts.append("</div>")

    # 2. I prompt del quaderno, con lo stato ricavato: e' l'unica sezione che risponde a «cosa
    # posso far partire adesso», ed e' la prima cosa che si guarda dopo aver visto che l'utente
    # non deve nulla. La regola sta in `tools/next_prompts.py`.
    parts.append("<h2>2. I prossimi prompt da eseguire</h2>")
    parts.append(
        next_prompts.render_html(next_entries or [])
        if next_entries
        else '<p class="meta">Quaderno non leggibile in questa generazione: nessun prompt '
        "mostrato. Nessun altro numero di questa pagina cambia: il resto viene dai registri.</p>"
    )

    # 3. Cosa sta succedendo adesso.
    parts.append("<h2>3. Cosa sta succedendo adesso</h2>")
    if claims:
        parts.append("<table><tr><th>Fase</th><th>Fase del ciclo</th><th>Titolare</th><th>Presa</th></tr>")
        for claim in claims:
            parts.append(
                f"<tr><td><code>{esc(claim.get('task_id'))}</code></td>"
                f"<td>{esc(claim.get('phase'))}</td>"
                f"<td>{esc((claim.get('owner_agent') or claim.get('owner') or '')[:70])}</td>"
                f"<td>{esc(claim.get('taken_at'))}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>Nessuna presa viva.</p>")

    # 4. A che punto siamo.
    parts.append("<h2>4. A che punto siamo</h2>")
    parts.append(
        '<p class="meta">Avanzamento per fase: '
        + " ".join(
            f'<span class="pill">{esc(status)}: {count}</span>'
            for status, count in sorted(statuses.items(), key=lambda item: -item[1])
        )
        + "</p>"
    )
    if ratified_ids is None:
        headline, headline_total = len(accepted), len(units)
        parts.append(
            f'<p><strong>{headline}</strong> unita\' accettate su <strong>{headline_total}</strong> '
            f"({round(100 * headline / max(headline_total, 1))}%), con TUTTE le fasi accettate. "
            "Il counter del coordinatore non era raggiungibile da questa generazione: il numero "
            "qui sopra e' quello stretto della pagina, non necessariamente quello del pack.</p>"
        )
        pending_units = sorted(unit for unit in units if unit not in accepted)
    else:
        headline, headline_total = len(ratified_ids), ratified_total or len(units)
        parts.append(
            f'<p><strong>{headline}</strong> unita\' accettate su <strong>{headline_total}</strong> '
            f"({round(100 * headline / max(headline_total, 1))}%). E' il conteggio della sola "
            "ratifica R, con la stessa regola di <code>tools/coord_status.py</code>.</p>"
        )
        pending_units = sorted(unit for unit in units if unit not in ratified_ids)
        divergent = sorted(unit for unit in ratified_ids if unit in units and unit not in accepted)
        if divergent:
            names = ", ".join(f"<code>{esc(unit)}</code>" for unit in divergent)
            phases = "; ".join(
                f"<code>{esc(unit)}</code> -> "
                + ", ".join(
                    f"{key}={esc(units[unit].get(unit + key, '-'))}"
                    for key in PHASE_ORDER
                    if units[unit].get(unit + key) not in DONE_STATUSES
                )
                for unit in divergent
                if unit in units
            )
            parts.append(
                f'<p class="meta"><strong>{len(accepted)}</strong> unita\' hanno tutte e quattro '
                f"le fasi accettate; {len(divergent)} ({names}) sono accettate con una fase che "
                "RESTA <code>needs_changes</code> nello storico: il verdetto pubblicato non si "
                "riscrive e il finding risulta chiuso da un tentativo E successivo, come dichiara "
                f"il report dell'unita'. Fasi non verdi di quelle voci: {phases}. La tabella qui "
                "sotto elenca invece le unita' che la ratifica R non ce l'hanno ancora.</p>"
            )
    if pending_units:
        parts.append("<table><tr><th>Unita'</th><th>Fasi e stato</th></tr>")
        for unit in pending_units[:40]:
            phases = units[unit]
            cells = " ".join(
                f'<span class="pill {"ok" if phases.get(unit + key) in DONE_STATUSES else ""}">'
                f"{esc(key)}: {esc(phases.get(unit + key, '-'))}</span>"
                for key in PHASE_ORDER
            )
            parts.append(f"<tr><td><code>{esc(unit)}</code></td><td>{cells}</td></tr>")
        parts.append("</table>")
        if len(pending_units) > 40:
            parts.append(
                f'<p class="meta">e altre {len(pending_units) - 40} unita\' non accettate.</p>'
            )

    # 4. Come verificare da soli.
    parts.append("<h2>5. Come verifichi tu</h2>")
    parts.append(
        "<p>Ogni riga e' un comando che puoi eseguire a mano, dalla root del repository. "
        "Non serve leggere un registro: l'esito lo stampa il comando.</p>"
    )
    if commands:
        for label, command in commands:
            parts.append(
                f'<div class="card"><div>{esc(label)}</div><pre>{esc(command)}</pre></div>'
            )
    else:
        parts.append(
            '<p class="meta">Questo workspace non dichiara comandi di verifica: si aggiungono in '
            "<code>console.yaml</code>, alla voce <code>verify</code>.</p>"
        )
    parts.append(
        '<p class="meta">Se un comando non parte o stampa un rosso inatteso, quello e\' il posto '
        "giusto per fermarci: e' una verifica tua, non una dichiarazione nostra.</p>"
    )

    if last_decisions:
        parts.append("<h2>Ultime decisioni registrate</h2><table>")
        parts.append("<tr><th>ID</th><th>Data</th><th>Decisione</th></tr>")
        for decision in last_decisions:
            statement = str(decision.get("statement", ""))[:220]
            parts.append(
                f"<tr><td><code>{esc(decision.get('id'))}</code></td>"
                f"<td>{esc(decision.get('date'))}</td><td>{esc(statement)}</td></tr>"
            )
        parts.append("</table>")

    parts.append("</body></html>")
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return {
        "units": headline_total,
        "accepted": headline,
        "all_phases": len(accepted),
        "waiting": len(waiting),
        "live_claims": len(claims),
        "prompts": len(next_entries or []),
        "free_prompts": len(
            [entry for entry in (next_entries or []) if entry["state"] == "da_lanciare"]
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    parser.add_argument("--out", help="file di output, dentro il workspace")
    args = parser.parse_args(argv)
    global PACK, WS
    WS = Workspace.load(args.workspace)
    PACK = WS.root
    next_prompts.configure(queue=WS.queue, deliverable_prefix=WS.deliverable_prefix)
    out_path = WS.path(args.out or WS.view)
    # Lo stato si carica UNA volta e si passa anche al quaderno: due letture dello stesso registro
    # da 1,9 MB possono cadere a cavallo di una scrittura e descrivere due stati diversi.
    state = load(WS.state)
    summary = render(
        out_path,
        state,
        load(WS.questions),
        load(WS.tasks),
        load(WS.decisions),
        ratified=coordinator_ratified(),
        user_decisions=load(WS.user_decisions),
        next_entries=next_prompts.build(PACK, state=state),
        verify=WS.verify,
    )
    print(f"scritto {out_path}")
    print(
        "unita' {units} | accettate {accepted} | tutte le fasi accettate {all_phases} | "
        "domande in attesa {waiting} | presse vive {live_claims} | prompt in quaderno "
        "{prompts} | lanciabili {free_prompts}".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
