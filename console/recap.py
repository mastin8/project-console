"""Il recap di ciò che resta in sospeso, letto dai registri e dagli esiti su disco.

Il coordinatore non esegue il lavoro e non chiama un modello: prepara il testo che una persona
incolla in una chat nuova. Questo modulo fa la parte che mancava: mette in un unico elenco le
unità aperte, le prese vive, ciò che aspetta l'utente, ciò che i report dichiarano dovuto, la
coda dei registri e i finding/limiti leggibili negli ultimi report delle fasi aperte.

Sola lettura. Nessuna interpretazione degli esiti: `esiti.estrai` legge solo le sezioni che hanno
una forma riconoscibile. Se un report non è leggibile, lo si dichiara; non si dice «tutto fatto».
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "registers")]

import esiti  # noqa: E402
import handoff  # noqa: E402
from console import constitution  # noqa: E402

CATEGORIE = (
    ("bloccanti", "Bloccano la chiusura"),
    ("altri_aperti", "Aperti, non bloccanti"),
    ("da_fare", "Da fare"),
    ("in_corso", "In corso"),
    ("attesa_te", "Aspetta te"),
    ("amministrazione", "Amministrazione"),
    ("esiti", "Cosa dicono gli esiti"),
)

MAX_REPORT_ESITI = 12
MAX_VOCI_CATEGORIA = 40
MAX_TITOLO = 140
MAX_DETTAGLIO = 320

GATE_UNITS = {"END01", "END02", "END03", "A11Y01", "A11Y02", "A11Y03"}


def _short(testo, limite):
    testo = " ".join(str(testo or "").split())
    return testo if len(testo) <= limite else testo[: limite - 1].rstrip() + "…"


def _prima_frase(testo):
    testo = " ".join(str(testo or "").split())
    if not testo:
        return ""
    for separatore in (". ", "; ", " — "):
        if separatore in testo:
            return testo.split(separatore, 1)[0].rstrip(" .;—") + "."
    return _short(testo, 160)


def _voce(categoria, titolo, dettaglio="", fonte="", badge="", riassunto="", stato="", ref=""):
    return {
        "categoria": categoria,
        "titolo": _short(titolo, MAX_TITOLO),
        "dettaglio": _short(dettaglio, MAX_DETTAGLIO),
        "fonte": str(fonte or ""),
        "badge": str(badge or ""),
        "riassunto": _short(riassunto, 180),
        "stato": _short(stato, 180),
        "ref": str(ref or ""),
    }


def _fase_rappresentativa(fasi):
    """La fase che tiene aperta l'unità: prima una respinta, poi la prima non accettata."""
    respinte = [fase for fase in fasi if fase.get("status") in ("needs_changes", "failed")]
    return respinte[0] if respinte else (fasi[0] if fasi else None)


def _categoria_fase(fase):
    if fase.get("status") in ("needs_changes", "failed"):
        return "bloccanti"
    if fase.get("status") in ("taken", "running", "active", "active_extension"):
        return "in_corso"
    return "da_fare"


def _dettaglio_fase(unit, fase):
    parti = [f"stato: {fase.get('status') or 'pending'}"]
    if fase.get("attempt"):
        parti.append(f"attempt {fase['attempt']}")
    if fase.get("delivered"):
        parti.append("consegna presente su disco")
    if unit.get("blocked"):
        parti.append(f"sblocca {unit['blocked']} unità")
    return "; ".join(parti)


def _esiti_aperti(state_obj, state_doc, fasi):
    """Finding e limiti degli ultimi report delle fasi aperte, senza inventare un verdetto."""
    letti = []
    for fase in fasi[:MAX_REPORT_ESITI]:
        if not fase.get("report") and not fase.get("delivery_path"):
            continue
        try:
            percorso, _, _, documento = handoff.ultimo_report(
                state_obj.workspace, state_doc, fase["id"]
            )
        except Exception as errore:  # noqa: BLE001 - un report illeggibile si dichiara
            letti.append(_voce(
                "esiti",
                f"{fase['id']} · esito non leggibile",
                str(errore)[:200],
                "report",
            ))
            continue
        if not documento:
            continue
        relativo = str(percorso.relative_to(state_obj.workspace.root)) if percorso else ""
        estratto = esiti.estrai(documento, relativo)
        for sezione in estratto.get("sezioni") or []:
            if sezione.get("titolo") not in ("Finding", "Limiti dichiarati"):
                continue
            for punto in sezione.get("punti") or []:
                testo = punto.get("testo") or punto.get("id")
                if not testo:
                    continue
                etichetta = punto.get("id") or sezione["titolo"]
                esito = punto.get("esito")
                letti.append(_voce(
                    "esiti",
                    f"{fase['id']} · {etichetta}",
                    f"{testo}" + (f" [{esito}]" if esito else ""),
                    relativo,
                ))
    if len(fasi) > MAX_REPORT_ESITI:
        letti.append(_voce(
            "esiti",
            "Esiti non letti tutti",
            f"letti i primi {MAX_REPORT_ESITI} report di {len(fasi)} fasi aperte; il resto resta nei report.",
            "limite dichiarato",
        ))
    return letti


def _stato_obbligo(obbligo):
    """L'ultima evidenza utile per un obbligo, non il testo iniziale se è stato superato."""
    for prefisso in (
        "fix_delivered",
        "verification_independent",
        "second_act",
        "state_",
        "closure_evidence",
        "disposition",
    ):
        candidate = [
            (chiave, valore)
            for chiave, valore in obbligo.items()
            if chiave.startswith(prefisso) and isinstance(valore, str) and valore.strip()
        ]
        if candidate:
            candidate.sort(key=lambda coppia: coppia[0], reverse=True)
            return candidate[0][1]
    return obbligo.get("what") or obbligo.get("note") or ""


def costruisci(state_obj):
    """Il recap di un workspace, dalla stessa istantanea che usa la pagina."""
    istantanea = state_obj.snapshot()
    state_doc = state_obj._load(state_obj.workspace.state) or {}
    voci = []
    per_fase = {}

    for blocco in istantanea.get("blocks") or []:
        for unit in blocco.get("units") or []:
            fasi = unit.get("phases") or []
            aperte = [fase for fase in fasi if fase.get("status") not in ("accepted",)]
            if not aperte and not unit.get("incoherent_with"):
                continue
            fase = _fase_rappresentativa(aperte)
            if fase is not None:
                voce = _voce(
                    _categoria_fase(fase),
                    f"{fase['id']} · {fase.get('kind') or 'fase'}",
                    _dettaglio_fase(unit, fase),
                    "registro",
                )
                voci.append(voce)
                per_fase[fase["id"]] = voce
            if unit.get("incoherent_with"):
                voci.append(_voce(
                    "bloccanti",
                    f"{unit['id']} · registro incoerente",
                    f"la fase {unit['incoherent_with']} chiude l'unità mentre un'altra fase è aperta",
                    "registro",
                ))

    for claim in istantanea.get("claims") or []:
        fase = claim.get("task_id")
        if fase in per_fase:
            owner = claim.get("owner") or "titolare non dichiarato"
            per_fase[fase]["dettaglio"] += f"; tenuta da {owner}"
            continue
        voci.append(_voce(
            "in_corso",
            f"{fase or 'fase'} · presa viva",
            f"tenuta da {claim.get('owner') or 'titolare non dichiarato'}"
            + (f" dal {claim['taken_at']}" if claim.get("taken_at") else ""),
            "registro",
        ))

    for domanda in istantanea.get("questions") or []:
        voci.append(_voce(
            "attesa_te",
            f"{domanda.get('id') or 'domanda'} · {domanda.get('topic') or 'domanda aperta'}",
            domanda.get("question") or domanda.get("why") or "",
            "domande",
        ))
    for decisione in istantanea.get("decisions") or []:
        voci.append(_voce(
            "attesa_te",
            f"{decisione.get('id') or 'decisione'} · {decisione.get('topic') or 'decisione di governo'}",
            decisione.get("question") or decisione.get("why") or "",
            "decisioni",
        ))

    for obbligo in state_doc.get("execution_attempts") or []:
        if not obbligo.get("obligation_id") or str(obbligo.get("status")) == "closed":
            continue
        identificativo = obbligo.get("obligation_id") or "obbligo"
        dettaglio = _stato_obbligo(obbligo)
        scadenza = str(obbligo.get("required_before") or "").strip()
        gate = scadenza in GATE_UNITS
        voci.append(_voce(
            "bloccanti" if gate else "altri_aperti",
            f"Obbligo {identificativo}",
            dettaglio,
            "registro",
            f"GATE · prima di {scadenza}" if gate else "APERTO",
            riassunto=_prima_frase(obbligo.get("what") or obbligo.get("note")),
            stato=_prima_frase(dettaglio),
        ))

    for dovuto in istantanea.get("owed") or []:
        if not dovuto.get("from_open"):
            continue
        voci.append(_voce(
            "da_fare",
            f"Dovuto da {dovuto.get('from_phase') or 'un report'}",
            dovuto.get("text") or ", ".join(dovuto.get("codes") or []),
            dovuto.get("source") or "report",
        ))

    for prompt in istantanea.get("next_prompts") or []:
        stato = prompt.get("state")
        if stato in ("fatto", "ignoto"):
            continue
        consegne = prompt.get("deliverables") or []
        categoria = {
            "da_lanciare": "da_fare",
            "parziale": "da_fare",
            "in_azione": "in_corso",
            "respinta": "bloccanti",
        }.get(stato, "amministrazione")
        voci.append(_voce(
            categoria,
            f"Prompt §{prompt.get('number')} · {prompt.get('title') or prompt.get('anchor') or 'senza titolo'}",
            f"stato misurato: {stato}"
            + (f"; consegna: {consegne[0].get('path')}" if consegne else ""),
            "quaderno",
        ))

    coda = istantanea.get("queue") or {}
    if int(coda.get("totale") or 0) > 0:
        voci.append(_voce(
            "amministrazione",
            "Coda dei registri non vuota",
            f"{coda.get('totale')} richieste non applicate"
            + (f", {coda.get('ferme')} ferme da oltre {coda.get('soglia_ore')} ore" if coda.get("ferme") else ""),
            "pending-transitions",
        ))
    if int(coda.get("sospette_totali") or 0) > 0:
        voci.append(_voce(
            "bloccanti",
            "Richieste in coda da non applicare",
            f"{coda.get('sospette_totali')} richieste segnalate: vanno lette prima di applicare la coda",
            "pending-transitions",
        ))

    posta = istantanea.get("inbox") or {}
    messaggi = [
        messaggio
        for messaggio in (posta.get("items") or [])
        if not messaggio.get("closed") and messaggio.get("open")
    ]
    for messaggio in messaggi:
        voci.append(_voce(
            "amministrazione",
            f"Posta: {messaggio.get('file') or 'messaggio'}",
            " · ".join(
                str(parte)
                for parte in (
                    messaggio.get("phase") or "senza fase",
                    messaggio.get("sender") or "mittente non dichiarato",
                    messaggio.get("when") or "",
                )
                if parte
            ),
            "inbox",
            ref=str(messaggio.get("ricevuta") or ""),
        ))
    if not messaggi and int(posta.get("non_lavorate") or 0) > 0:
        voci.append(_voce(
            "amministrazione",
            "Posta in arrivo non lavorata",
            f"{posta.get('non_lavorate')} messaggi senza un report successivo",
            posta.get("cartella") or "inbox",
        ))

    fasi_aperte = [
        fase
        for blocco in istantanea.get("blocks") or []
        for unit in blocco.get("units") or []
        for fase in unit.get("phases") or []
        if fase.get("status") not in ("accepted",)
    ]
    voci.extend(_esiti_aperti(state_obj, state_doc, fasi_aperte))

    ordine = {chiave: indice for indice, (chiave, _) in enumerate(CATEGORIE)}
    voci.sort(key=lambda voce: (ordine.get(voce["categoria"], 99), voce["titolo"]))
    gruppi = []
    for chiave, etichetta in CATEGORIE:
        membri = [voce for voce in voci if voce["categoria"] == chiave]
        if not membri:
            continue
        tagliati = membri[MAX_VOCI_CATEGORIA:]
        gruppi.append({
            "chiave": chiave,
            "etichetta": etichetta,
            "voci": membri[:MAX_VOCI_CATEGORIA],
            "tagliate": len(tagliati),
        })
    conteggi = {gruppo["chiave"]: len(gruppo["voci"]) + gruppo["tagliate"] for gruppo in gruppi}
    completo = not voci
    adesso = datetime.now().strftime("%Y-%m-%d %H:%M")
    progetto = getattr(state_obj.workspace, "project", "") or "questo progetto"
    vincoli = constitution.prompt_context(state_obj.workspace)

    righe = [
        f"Sei nel workspace «{progetto}». Devo sapere se il lavoro è davvero finito.",
        f"Questo recap è stato calcolato il {adesso} dai registri e dagli esiti su disco.",
        "",
    ]
    if completo:
        righe.append("Nessuna voce aperta: i registri non mostrano unità aperte, prese vive,")
        righe.append("domande, decisioni, code o esiti con finding/limiti.")
    else:
        for gruppo in gruppi:
            righe.append(f"{gruppo['etichetta']} ({len(gruppo['voci']) + gruppo['tagliate']})")
            for voce in gruppo["voci"]:
                riga = f"- {voce['titolo']}"
                if voce["dettaglio"]:
                    riga += f": {voce['dettaglio']}"
                if voce["fonte"]:
                    riga += f" [{voce['fonte']}]"
                righe.append(riga)
            if gruppo["tagliate"]:
                righe.append(f"- … altre {gruppo['tagliate']} voci non elencate")
            righe.append("")
    righe.extend([
        "Leggi i report citati e verifica ogni voce. Non inventare voci nuove.",
        "Per ogni voce dimmi: (1) è ancora aperta? (2) chi la chiude? (3) qual è il prossimo comando o prompt?",
        "Se un esito non è leggibile, dichiaralo. Non dire «tutto fatto» se una fonte non è stata letta.",
    ])
    return {
        "project": progetto,
        "generated": adesso,
        "complete": completo,
        "counts": conteggi,
        "groups": gruppi,
        "prompt": vincoli + "\n" + "\n".join(righe).strip() + "\n",
    }


def main(argv=None):
    import argparse
    import json

    from server import ReviewState
    from workspace import Workspace

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    esito = costruisci(ReviewState(Workspace.load(args.workspace)))
    if args.json:
        print(json.dumps(esito, ensure_ascii=False, indent=1))
    else:
        print(esito["prompt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
