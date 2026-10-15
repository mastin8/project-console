#!/usr/bin/env python3
"""I prossimi prompt da eseguire, con lo stato RICAVATO e non dichiarato.

Perche' esiste: `PARALLEL-PROMPTS.md` e' il quaderno dei prompt — una sezione per prompt, il testo
pronto da incollare in una chat nuova — ma lo stato di ogni prompt e' scritto A MANO nel titolo
(«PRESO, NON LANCIARLO»). Quella riga invecchia da sola, e il 2026-10-15 e' successo davvero: la
sezione 8 dichiarava LIBERA mentre la consegna `reports/ZIP01-CONTRACT-LIMITS-DECLARE/attempt-1.yaml`
esisteva su disco ed era citata dal registro. Chi legge per decidere cosa lanciare non ha modo di
sapere quale delle due righe credere.

Questo strumento NON aggiunge un registro: legge il quaderno e i registri che esistono gia' e
ricava lo stato da due segnali che nessuno scrive a mano.

  1. la CONSEGNA dichiarata dalla sezione (`CONSEGNA: reports/<id>/attempt-N.yaml`), che il prompt
     stesso ordina di non trovare gia' presente: se esiste, quel prompt e' stato eseguito;
  2. l'ANCORA della sezione — la voce di claim o l'obbligo che il testo nomina — dentro
     `state.yaml`: se e' viva con un titolare, quel prompt e' in azione adesso.

Stati possibili, tutti una misura:

  ``fatto``        tutte le consegne dichiarate esistono su disco
  ``parziale``     una parte soltanto esiste
  ``in azione``    la voce di claim e' viva nel registro, con titolare e ora di presa
  ``da lanciare``  l'ancora esiste nel registro e la consegna non c'e'
  ``ignoto``       nel testo non c'e' un'ancora riconoscibile: si dichiara, non si inventa

Le due viste del pack (la pagina JavaScript di `review/` e il generatore di `STATUS.html`) usano
QUESTA implementazione, cosi' non possono divergere: la regola sta in un posto solo.

Sola lettura: legge `PARALLEL-PROMPTS.md` e `state.yaml`, e guarda se i file di consegna esistono.
Non scrive niente, non tocca la rete.

Uso::

    python3 tools/next_prompts.py              # tabella leggibile
    python3 tools/next_prompts.py --json       # per le pagine
    python3 tools/next_prompts.py --section 11 # una sola sezione
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

#: Il workspace da `$CONSOLE_WORKSPACE` o dalla cartella corrente. Il modulo non conosce progetti.
PACK = Path(os.environ.get("CONSOLE_WORKSPACE") or Path.cwd()).expanduser().resolve()
#: Il file del quaderno e il prefisso dei percorsi di consegna: sono CONVENZIONI, e si cambiano
#: dalla configurazione del workspace (`console.yaml`).
PROMPTS_MD = "PARALLEL-PROMPTS.md"
DELIVERABLE_PREFIX = "reports/"

#: Gli stati in cui la pagina considera VIVA una voce di claim: gli stessi di `check_claims.py`,
#: `coord_status.py` e della pagina di review. Una voce con `released_at` non e' viva comunque.
LIVE_STATUSES = ("active", "taken", "pre_registered", "ready", "active_extension")

#: Le parole con cui i titoli dichiarano a mano lo stato. Servono solo a MISURARE il disaccordo.
DECLARED_DONE = ("GIA' ESEGUITO", "GIÀ ESEGUITO", "ESEGUITA", "PUBBLICATO")
DECLARED_TAKEN = ("PRESO", "IN VOLO")
DECLARED_KEEP = ("NON LANCIARLO", "NON LANCIARLA")

_SECTION = re.compile(r"^##\s+(\d+)\s+[—-]\s+(.*)$", re.M)
_FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)
_CLAIM = re.compile(r"voce di claim\s+([^\n]{0,60})")
_OBLIGATION = re.compile(r"obbligo\s+([^\n]{0,60})")
#: Un id del registro ha per forza una maiuscola o una cifra: e' il filtro che scarta la PROSA.
#: Serve davvero: «La voce di claim e' `taken` nel registro» e «la voce di claim che il registro
#: ha gia'» davano come id `e` e `che` — misurato al primo giro di questo strumento (§5 e §10).
_TOKEN = re.compile(r"`([^`]+)`|([A-Za-z][A-Za-z0-9._-]{2,})")
#: Un id finisce con una lettera o una cifra: la prosa lo mette in mezzo a un punto fermo
#: («la voce di claim VAT01A. NON scrivere») e senza questo vincolo l'id letto era `VAT01A.`,
#: che il registro non conosce (misurato il 2026-10-15 su un progetto nuovo).
_ID_LIKE = re.compile(r"^(?=.*[A-Z0-9])[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$|^[A-Za-z0-9]{2}$")
_DELIVERABLE = re.compile(r"\breports/[A-Za-z0-9._/-]+\.ya?ml")


def configure(queue=None, deliverable_prefix=None):
    """Le due convenzioni che cambiano da progetto a progetto. Chiamata dai consumatori (console,
    vista statica) prima di leggere: nessuna delle due e' cablata nel codice."""
    global PROMPTS_MD, DELIVERABLE_PREFIX, _DELIVERABLE
    if queue:
        PROMPTS_MD = str(queue)
    if deliverable_prefix:
        DELIVERABLE_PREFIX = str(deliverable_prefix).lstrip("./")
        _DELIVERABLE = re.compile(
            r"\b" + re.escape(DELIVERABLE_PREFIX) + r"[A-Za-z0-9._/-]+\.ya?ml"
        )
_MANDATE = re.compile(r"MANDATE-[A-Za-z0-9-]+\.md")


def _clean(text):
    return " ".join(str(text or "").split())


def _pack_relative(raw):
    """`docs/ux-context-pack/reports/x.yaml` e `reports/x.yaml` sono lo stesso file."""
    value = raw.strip().strip("`").rstrip(".,;")
    prefix = "docs/ux-context-pack/"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return value


def split_heading(heading):
    """Titolo e clausola di stato scritta a mano, dal titolo della sezione.

    `1 — A11Y03T — PRESO (terzo tentativo, in volo), NON LANCIARLO` -> `A11Y03T`, `PRESO ...`.
    `6 — verifica indipendente ... — AGGIUNTO 2026-10-14 19:00` -> la data non e' uno stato.
    """
    parts = [part.strip() for part in re.split(r"\s+[—-]\s+", heading)]
    if len(parts) > 1:
        tail = parts[-1]
        upper = tail.upper()
        if any(word in upper for word in DECLARED_DONE + DECLARED_TAKEN + DECLARED_KEEP) or (
            upper.startswith("AGGIUNTO") or upper.startswith("AGGIUNTA")
        ):
            return " — ".join(parts[:-1]), tail
    return heading, ""


def sections(md_text):
    """Le sezioni NUMERATE del quaderno, con il loro corpo e il primo blocco recintato."""
    found = list(_SECTION.finditer(md_text))
    out = []
    for index, match in enumerate(found):
        end = found[index + 1].start() if index + 1 < len(found) else len(md_text)
        body = md_text[match.end() : end]
        title, declared = split_heading(match.group(2).strip())
        fence = _FENCE.search(body)
        out.append(
            {
                "number": int(match.group(1)),
                "line": md_text[: match.start()].count("\n") + 1,
                "heading": match.group(2).strip(),
                "title": title,
                "declared": declared,
                "body": body,
                "prompt": fence.group(1).strip("\n") if fence else None,
            }
        )
    return out


def _ids_near(text, phrase):
    """Gli id plausibili subito dopo una frase, in ordine: prima quelli fra apici inversi."""
    out = []
    for match in re.finditer(phrase, text):
        # Dalla PRIMA COSA DOPO LA FRASE, non dalla fine del match: il match contiene gia' i 60
        # caratteri guardati, quindi `match.end()` cadeva DOPO l'id e il pattern leggeva la prosa
        # successiva («NON», «CONSEGNA», «Una» — misurato su §1, §2 e §5 al secondo giro).
        start = match.start(1)
        window = text[start : start + 60]
        for backticked, bare in _TOKEN.findall(window):
            candidate = (backticked or bare).strip()
            if not _ID_LIKE.match(candidate):
                continue
            if re.fullmatch(r"[a-z].*", candidate) and not re.search(r"[0-9]", candidate):
                continue
            if candidate not in out:
                out.append(candidate)
    return out


def anchor_candidates(section):
    """Le ancore CANDIDATE che legano il prompt al registro, in ordine di fiducia.

    Prima la prosa — «la voce di claim X», «l'obbligo Y» — perche' e' cio' che l'autore ha scritto
    di proposito; se tace, il nome del percorso della consegna (`reports/<id>/attempt-N.yaml`) o il
    nome del mandato (`MANDATE-<id>.md`), che sono comunque id del registro. Nessuna di queste
    stringhe viene creduta sulla parola: `resolve` la cerca in `state.yaml` e, se non c'e', lo
    DICHIARA invece di inventare uno stato.
    """
    text = section["heading"] + "\n" + section["body"]
    out = [("claim", value, "prosa") for value in _ids_near(text, _CLAIM)]
    out += [("obbligo", value, "prosa") for value in _ids_near(text, _OBLIGATION)]
    for deliverable in deliverables_of(section):
        parts = Path(deliverable).parts
        if len(parts) >= 3 and deliverable.startswith(DELIVERABLE_PREFIX):
            out.append(("claim", parts[1], "consegna"))
    for mandate in _MANDATE.findall(text):
        out.append(("claim", mandate[len("MANDATE-") : -len(".md")], "mandato"))
    seen, unique = set(), []
    for kind, value, source in out:
        if (kind, value) in seen:
            continue
        seen.add((kind, value))
        unique.append((kind, value, source))
    return unique


def deliverables_of(section):
    """I file di consegna dichiarati dopo `CONSEGNA:` — il prompt dice di non trovarli gia' li'."""
    body = section["body"]
    index = body.upper().find("CONSEGNA:")
    zone = body[index:] if index >= 0 else body
    # Solo il paragrafo della consegna: il resto della sezione puo' citare altri file.
    zone = re.split(r"\n\s*\n", zone)[0] if index >= 0 else zone
    seen, out = set(), []
    for raw in _DELIVERABLE.findall(zone):
        path = _pack_relative(raw)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _latest_claim(state, claim_id):
    """L'ULTIMA voce di claim con quell'id: il registro appende, e l'ultima e' quella viva."""
    claims = [c for c in (state.get("active_claims") or []) if c.get("task_id") == claim_id]
    if claims:
        claim = claims[-1]
        live = claim.get("status") in LIVE_STATUSES and not claim.get("released_at")
        owner = claim.get("taken_by") or claim.get("owner_agent") or claim.get("owner")
        return {
            "found": True,
            "where": "active_claims",
            "status": claim.get("status"),
            "live": live,
            "owner": owner,
            # Il campo `owner` porta spesso l'intero mandato: a schermo se ne mostra l'inizio.
            "owner_short": shorten(owner, 120),
            "taken_at": claim.get("taken_at"),
            "released_at": claim.get("released_at"),
            "attempt": claim.get("attempt"),
            "phase": claim.get("phase"),
        }
    task = (state.get("tasks") or {}).get(claim_id)
    if task:
        owner = task.get("owner_agent") or task.get("owner")
        return {
            "found": True,
            "where": "tasks",
            "status": task.get("status"),
            "live": task.get("status") in LIVE_STATUSES,
            "owner": owner,
            "owner_short": shorten(owner, 120),
            "taken_at": task.get("taken_at"),
            "released_at": None,
            "attempt": task.get("attempt"),
            "phase": task.get("phase"),
            "report": task.get("report"),
        }
    return {"found": False, "where": None}


def _latest_obligation(state, obligation_id):
    """Gli obblighi vivono in `execution_attempts`, mescolati alle voci di claim."""
    items = [
        item
        for item in (state.get("execution_attempts") or [])
        if item.get("obligation_id") == obligation_id
    ]
    if not items:
        return {"found": False, "where": None}
    item = items[-1]
    closed = item.get("status") == "closed" or bool(item.get("closure_kind"))
    owner = item.get("owner")
    return {
        "found": True,
        "where": "execution_attempts",
        "status": item.get("status"),
        "live": False,
        "closed": closed,
        "owner": owner,
        "owner_short": shorten(owner, 120),
        "taken_at": item.get("registered_at"),
        "required_before": item.get("required_before"),
    }


def resolve(section, state, pack=PACK):
    """Lo stato del prompt: una misura, con accanto la prova che l'ha prodotta."""
    candidates = anchor_candidates(section)
    deliveries = []
    for path in deliverables_of(section):
        target = pack / path
        item = {"path": path, "exists": target.exists()}
        if item["exists"]:
            stat = target.stat()
            item["mtime"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            item["bytes"] = stat.st_size
        deliveries.append(item)
    present = [d for d in deliveries if d["exists"]]

    kind, anchor, source, registry = "nessuna", None, "nessuna", {"found": False, "where": None}
    for candidate_kind, candidate, candidate_source in candidates:
        # La prima candidata che il REGISTRO conosce: cosi' un id citato di passaggio nella prosa
        # non ruba il posto a quello vero, e nessuna candidata viene creduta sulla parola. Si prova
        # anche l'altro tipo di voce: un id letto dal percorso della consegna o dal nome del mandato
        # non dice da solo se nel registro e' una fase o un obbligo, e sbagliare tipo non e' un
        # motivo per dichiarare ignoto un prompt che il registro conosce.
        for attempt_kind in ((candidate_kind,) + (("obbligo",) if candidate_kind == "claim" else ("claim",))):
            found = (
                _latest_claim(state, candidate)
                if attempt_kind == "claim"
                else _latest_obligation(state, candidate)
            )
            if found.get("found"):
                kind, anchor, source, registry = attempt_kind, candidate, candidate_source, found
                break
        if registry.get("found"):
            break
    if not registry.get("found") and candidates:
        kind, anchor, source = candidates[0]

    accepted_phase = registry.get("status") == "accepted"
    if deliveries and len(present) == len(deliveries):
        state_name = "fatto"
    elif accepted_phase:
        state_name = "fatto"
    elif registry.get("live"):
        state_name = "in_azione"
    elif present:
        state_name = "parziale"
    elif registry.get("found") and not registry.get("closed"):
        state_name = "da_lanciare"
    else:
        state_name = "ignoto"

    flags = []
    if kind == "nessuna":
        flags.append("senza_ancora")
    elif not registry.get("found"):
        flags.append("ancora_non_nel_registro")
    if not deliveries:
        flags.append("senza_consegna")
    if section["prompt"] is None:
        flags.append("testo_non_estratto")
    upper = section["declared"].upper()
    claims_done = any(word in upper for word in DECLARED_DONE)
    claims_held = any(word in upper for word in DECLARED_TAKEN)
    claims_keep = any(word in upper for word in DECLARED_KEEP)
    # Il titolo e' scritto a mano: qui si misura solo se CONTRADDICE la misura, e in che verso.
    if state_name in ("da_lanciare", "ignoto") and (claims_done or claims_held or claims_keep):
        flags.append("titolo_ottimista")
    # Solo su `fatto`: se la consegna esiste e il titolo lo da' ancora per preso, il titolo e'
    # fermo. Su `in_azione` il titolo ha ragione — registro e titolo dicono la stessa cosa — e
    # segnalarlo sarebbe un falso positivo (misurato sul quaderno sintetico del 2026-10-15).
    if state_name == "fatto" and (claims_held or claims_keep) and not claims_done:
        flags.append("titolo_ancora_in_volo")
    if state_name == "fatto" and not (claims_done or claims_held) and upper:
        flags.append("titolo_fermo")
    if state_name == "fatto" and registry.get("live"):
        flags.append("consegna_senza_rilascio")
    if state_name == "fatto" and registry.get("status") in ("needs_changes", "failed"):
        flags.append("esito_respinto")
    if state_name == "fatto" and registry.get("status") == "open":
        flags.append("obbligo_ancora_aperto")

    return {
        "number": section["number"],
        "title": section["title"],
        "declared": section["declared"],
        "state": state_name,
        "anchor_kind": kind,
        "anchor": anchor,
        "anchor_source": source,
        "candidates": [f"{k}:{v}({s})" for k, v, s in candidates],
        "registry": registry,
        "deliverables": deliveries,
        "mandates": sorted(set(_MANDATE.findall(section["heading"] + section["body"]))),
        "prompt": section["prompt"],
        "flags": flags,
        "notes": [FLAG_NOTE.get(flag, flag) for flag in flags if flag in FLAGS_SHOWN],
        "group": None,  # riempito in `build`: dipende dai segnali, che qui sono appena nati
        "line": section["line"],
    }


def build(pack=PACK, md_name=PROMPTS_MD, state=None):
    """Tutti i prompt del quaderno, risolti. `state` si passa gia' caricato: sono 1,9 MB."""
    path = pack / md_name
    if not path.exists():
        return []
    if state is None:
        state = yaml.safe_load((pack / "state.yaml").read_text(encoding="utf-8")) or {}
    text = path.read_text(encoding="utf-8")
    entries = [resolve(section, state, pack) for section in sections(text)]
    for entry in entries:
        entry["group"] = group_of(entry)
        entry["group_label"] = GROUP_LABEL.get(entry["group"], entry["group"])
    # Prima cio' che si puo' far partire: e' la domanda per cui si apre questa sezione.
    entries.sort(key=lambda entry: (STATE_PRIORITY.get(entry["group"], 9), entry["number"]))
    return entries


STATE_LABEL = {
    "fatto": "fatto",
    "in_azione": "in azione",
    "parziale": "parziale",
    "da_lanciare": "da lanciare",
    "ignoto": "ignoto",
}

#: I segnali, in italiano, per chi legge. Il codice va alle pagine UNA volta sola: se ogni vista
#: avesse la sua traduzione, la stessa riga finirebbe per dire due cose diverse.
FLAG_NOTE = {
    "titolo_ottimista": "il titolo lo dichiara preso o gia' eseguito, ma la consegna non esiste",
    "titolo_ancora_in_volo": "il titolo lo da' ancora per preso, mentre la consegna esiste",
    "titolo_fermo": "la consegna esiste e il titolo non lo dichiara",
    "ancora_non_nel_registro": "il codice letto nel testo non e' una voce di questo registro",
    "senza_ancora": "nel testo non c'e' un codice del registro: lo stato non e' ricavabile",
    "senza_consegna": "il prompt non dichiara una consegna da misurare",
    "testo_non_estratto": "il testo del prompt non e' leggibile dal quaderno",
    "consegna_senza_rilascio": "la voce di claim e' ancora viva: manca il rilascio",
    "esito_respinto": "consegnata, ma la verifica l'ha respinta",
    "obbligo_ancora_aperto": "l'obbligo nel registro e' ancora aperto",
}

#: Quali segnali meritano una riga a schermo. `titolo_fermo` resta nel codice (e nei file) ma non
#: si mostra: dice solo che un titolo scritto a mano non annuncia una consegna, e ripeterlo sotto
#: ogni riga riempie la pagina di una cosa che non cambia nessuna decisione.
FLAGS_SHOWN = (
    "titolo_ottimista",
    "titolo_ancora_in_volo",
    "esito_respinto",
    "consegna_senza_rilascio",
    "obbligo_ancora_aperto",
    "ancora_non_nel_registro",
    "senza_ancora",
    "senza_consegna",
    "testo_non_estratto",
)

#: L'ordine in cui si leggono le righe: prima quello che puoi far partire adesso, poi quello che
#: qualcuno sta facendo, e la storia in fondo. Dentro il gruppo resta l'ordine del quaderno.
STATE_PRIORITY = {"da_lanciare": 0, "in_azione": 1, "respinta": 2, "parziale": 3, "ignoto": 4, "fatto": 5}

#: I gruppi in cui si leggono i prompt, e come si chiamano. `respinta` non e' uno stato del
#: registro: e' un prompt CONSEGNATO la cui verifica ha detto di no, ed e' la cosa che si vuole
#: distinguere a colpo d'occhio da «gia' fatto».
GROUP_LABEL = {
    "da_lanciare": "da lanciare",
    "in_azione": "in azione",
    "respinta": "consegna respinta",
    "parziale": "consegna parziale",
    "ignoto": "da verificare",
    "fatto": "gia' consegnati",
}


def group_of(entry):
    """Il gruppo di un prompt: lo stato, con la consegna respinta che vince sull'essere «fatto»."""
    if "esito_respinto" in entry["flags"]:
        return "respinta"
    return entry["state"]


def shorten(text, limit=90):
    """Taglia su uno spazio: troncare a meta' parola e' la forma peggiore di un numero truncato."""
    value = _clean(text)
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def render_table(entries):
    lines = []
    for entry in entries:
        label = STATE_LABEL.get(entry["state"], entry["state"])
        anchor = entry["anchor"] or "—"
        lines.append(f"§{entry['number']:<3} {label:<11} {anchor:<28} {entry['title'][:40]}")
        if entry["deliverables"]:
            done = sum(1 for item in entry["deliverables"] if item["exists"])
            first = entry["deliverables"][0]
            when = f" ({first.get('mtime')})" if first.get("mtime") else ""
            lines.append(f"      consegna {done}/{len(entry['deliverables'])}: {first['path']}{when}")
        if entry["registry"].get("found"):
            registry = entry["registry"]
            owner = registry.get("owner_short") or ""
            lines.append(
                f"      registro: {registry['status']} in {registry['where']}"
                + (f" · titolare {owner}" if owner else "")
                + (f" · presa {registry['taken_at']}" if registry.get("taken_at") else "")
            )
        if entry["flags"]:
            lines.append(f"      segnali: {', '.join(entry['flags'])}")
    return "\n".join(lines)


def render_html(entries):
    """Il blocco HTML per `STATUS.html`: la stessa regola, resa come la pagina statica.

    Il titolo lo mette chi chiama: la numerazione delle sezioni e' della pagina, non di questo
    strumento.
    """
    css = {"fatto": "ok", "in_azione": "warn", "da_lanciare": "", "parziale": "warn", "ignoto": "bad"}
    parts = [
        '<p class="meta">Ogni riga e\' un prompt pronto da incollare in una chat nuova. Il codice '
        "e' quello che citi tu; lo stato lo ricava questa pagina dai registri e dai file di "
        "consegna, quindi non invecchia come la riga scritta a mano nel titolo.</p>"
    ]
    if not entries:
        parts.append('<p class="meta">Nessun prompt nel quaderno.</p>')
        return "\n".join(parts)
    parts.append(
        "<table><tr><th>Codice</th><th>Stato</th><th>Prompt</th><th>Ancora nel registro</th></tr>"
    )
    last_group = None
    for entry in entries:
        # Una riga di separazione per gruppo: «da lanciare», «consegna respinta», «gia' consegnati».
        if entry["group"] != last_group:
            last_group = entry["group"]
            quanti = sum(1 for item in entries if item["group"] == last_group)
            parts.append(
                f'<tr><td colspan="4"><strong>{html.escape(entry["group_label"])}</strong>'
                f' <span class="meta">({quanti})</span></td></tr>'
            )
        label = STATE_LABEL.get(entry["state"], entry["state"])
        code = html.escape(entry["anchor"] or f"§{entry['number']}")
        anchor = entry["registry"]
        detail = ""
        if anchor.get("found"):
            detail = f"{html.escape(str(anchor.get('status')))}"
            if anchor.get("taken_at"):
                detail += f" · presa {html.escape(str(anchor['taken_at']))}"
            if anchor.get("owner_short"):
                detail += f" · {html.escape(anchor['owner_short'])}"
        else:
            detail = "nessuna voce nel registro"
        delivery = entry["deliverables"][0] if entry["deliverables"] else None
        if delivery:
            mark = "consegnata" if delivery["exists"] else "non consegnata"
            detail += f"<br><code>{html.escape(delivery['path'])}</code> — {mark}"
        flags = ""
        if entry["notes"]:
            sentences = " ".join(f"{html.escape(note)}." for note in entry["notes"])
            codes = html.escape(", ".join(entry["flags"]))
            flags = f'<br><span class="bad" title="{codes}">{sentences}</span>'
        parts.append(
            f'<tr><td><code>§{entry["number"]}</code><br><code>{code}</code></td>'
            f'<td class="{css.get(entry["state"], "")}">{html.escape(label)}</td>'
            f'<td>{html.escape(entry["title"])}{flags}</td>'
            f"<td class=\"meta\">{detail}</td></tr>"
        )
    parts.append("</table>")
    return "\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="per le pagine")
    parser.add_argument("--section", type=int, help="una sola sezione del quaderno")
    parser.add_argument(
        "--workspace",
        "--pack",  # nome storico: lo usano le corsie dei progetti gia' avviati
        dest="workspace",
        default=str(PACK),
        help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)",
    )
    parser.add_argument("--queue", help="file del quaderno (default: quello della convenzione)")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="cosa ha letto in ogni sezione: ancore candidate e ancore risolte",
    )
    args = parser.parse_args(argv)
    if args.queue:
        configure(queue=args.queue)
    entries = build(Path(args.workspace))
    if args.section is not None:
        entries = [entry for entry in entries if entry["number"] == args.section]
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, default=str))
    elif args.explain:
        # Cosa ha LETTO, non solo cosa ha concluso: senza questo, un'ancora sbagliata si vede solo
        # dal numero sbagliato nella pagina (e' successo al primo giro, §5 «e» e §10 «che»).
        for entry in entries:
            chosen = f"{entry['anchor_kind']}:{entry['anchor']} da {entry['anchor_source']}"
            print(f"§{entry['number']} -> {chosen}")
            print(f"    candidate: {', '.join(entry['candidates']) or 'nessuna'}")
            if entry["registry"].get("found"):
                print(
                    f"    registro: {entry['registry']['status']} in {entry['registry']['where']}"
                    f" (viva: {'si' if entry['registry'].get('live') else 'no'})"
                )
            for item in entry["deliverables"]:
                print(f"    consegna: {item['path']} {'esiste' if item['exists'] else 'assente'}")
            print(f"    stato: {entry['state']} · segnali: {', '.join(entry['flags']) or '—'}")
    else:
        print(render_table(entries))
        counts = {}
        for entry in entries:
            counts[entry["state"]] = counts.get(entry["state"], 0) + 1
        print("\n" + " · ".join(f"{STATE_LABEL[k]}: {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
