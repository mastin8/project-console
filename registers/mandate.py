#!/usr/bin/env python3
"""Il prompt di una fase: quello del quaderno se c'e', altrimenti composto dal registro.

Perche' esiste: attivare una fase riservava la fase e depositava l'ordine, ma se il quaderno non
aveva una sezione per QUELLA fase l'ordine usciva con `prompt: null` — e chi attivava non trovava
niente da incollare in una chat. Misurato il 2026-10-15: su `OVR01E` e `HIST01A` il quaderno tace,
quindi attivarle non dava nessun prompt da consegnare a un esecutore.

Il prompt composto non inventa lavoro: mette in fila quello che il registro GIA' sa — la fase, il
tipo, il file di consegna atteso, i criteri di accettazione, il perimetro dichiarato con le sue
impronte, e le tre regole che valgono sempre (prendi la fase prima di scrivere, prova solo cio' che
tocchi, lascia scritto cosa c'e' da fare dopo). Quello che il registro NON sa — il contenuto
tecnico del lavoro — resta scritto come tale: `DA COMPLETARE`, invece di essere riempito di prosa
inventata.

Sola lettura. Uso::

    python3 registers/mandate.py --workspace <progetto> --phase OVR01E
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


def _carica(flusso):
    """Legge un registro col parser veloce quando c'e' (libyaml): 17 volte piu' rapido su un
    registro da 2 MB (misurato: 0,09 s contro 1,55 s). Stesso sottoinsieme sicuro di YAML, nessun
    costruttore custom: e' `safe_load` scritto in C, non un'altra sintassi."""
    return yaml.load(flusso, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import activate  # noqa: E402 - le impronte del perimetro sono sue
import next_prompts  # noqa: E402 - il quaderno, per il prompt che esiste gia'
from workspace import Workspace  # noqa: E402

#: Che ruolo tocca, dal tipo di fase. E' un'etichetta, non un permesso: la mappa vera e' in
#: `agents/agents.yaml` del workspace, e chi dispatcha la usa.
RUOLI = {
    "analysis": "analisi",
    "implementation": "esecuzione",
    "independent_verification": "verifica indipendente",
    "functional_acceptance": "accettazione",
}


def _leggi(path):
    try:
        return _carica(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _occorrenza_per(ws, fase):
    """Quale occorrenza dell'ancora e' QUESTA voce: la n-esima fra quelle con lo stesso task_id.

    Il prompt dice `occurrence` perche' l'applicatore, davanti a un'ancora ripetuta, rifiuta invece
    di scegliere: senza il numero, la presa non si applica e la fase resta «in attesa».
    """
    state = _carica(ws.state_path.read_text(encoding="utf-8")) or {}
    quante = 0
    for voce in state.get("active_claims") or []:
        if str(voce.get("task_id")) != fase:
            continue
        quante += 1
        if voce.get("status") in ("pre_registered", "ready") or not voce.get("released_at"):
            return quante
    return max(quante, 1)


def componi(ws, fase, state=None, tasks_doc=None):
    """Un prompt per quella fase, costruito da cio' che il registro sa."""
    state = state if state is not None else _leggi(ws.state_path)
    tasks_doc = tasks_doc if tasks_doc is not None else _leggi(ws.path(ws.tasks))
    task = next((t for t in tasks_doc.get("tasks") or [] if str(t.get("id")) == fase), None)
    if task is None:
        raise SystemExit(f"fase non dichiarata in {ws.tasks}: {fase}")
    unita = next(
        (u for u in tasks_doc.get("units") or [] if str(u.get("id")) == str(task.get("unit_id"))),
        {},
    )
    registro = (state.get("tasks") or {}).get(fase) or {}
    tipo = str(task.get("kind") or "")
    ruolo = RUOLI.get(tipo, "esecuzione")
    # L'ultima fase del ciclo e' l'accettazione: e' l'unica che GIUDICA invece di produrre, e per
    # questo riceve istruzioni diverse — corte, con il cancello davanti.
    atto_corto = str(task.get("id") or fase).endswith(str((ws.phases or ("R",))[-1]))
    percorso_preflight = Path(__file__).resolve().parent / "preflight.py"
    # Il prossimo tentativo e' il primo numero LIBERO su disco: i file sono la storia pubblicata.
    # Il registro puo' essere indietro e una presa puo' non portare `attempt`: misurato il
    # 2026-10-17 su ZIP02E, dove il prompt diceva `attempt-1` mentre su disco c'erano 1 e 2.
    cartella_consegne = ws.reports_dir / str(fase)
    numeri = []
    for percorso in cartella_consegne.glob("attempt-*.yaml") if cartella_consegne.is_dir() else []:
        trovato = re.match(r"attempt-(\d+)\.yaml$", percorso.name)
        if trovato:
            numeri.append(int(trovato.group(1)))
    attempt = max(numeri, default=0) + 1
    consegna = f"{ws.deliverable_prefix}{fase}/attempt-{attempt}.yaml"
    revisione, fonte_revisione = activate.impronte(ws, state, fase)
    criteria = task.get("acceptance_criteria") or []
    if isinstance(criteria, dict):
        criteria = [f"{k}: {v}" for k, v in criteria.items()]

    # Dove si lavora: il repository che contiene il workspace, se c'e' — il codice sta li'.
    radici = activate.radici(ws)
    radice_lavoro = next((r for nome, r in radici if nome == "repository"), ws.root)
    # La busta (la «prima istruzione») la mette `per()`: qui c'e' solo il CORPO del prompt, cosi' la
    # stessa busta vale per il composto, per il quaderno e per un ordine gia' congelato.
    righe = [
        f"Lavora in {radice_lavoro}. Sei un agente di {ruolo}: non coordinare, non dispatchare",
        "figli, non chiedere conferme.",
        "",
        f"FASE: {fase} — {task.get('title') or 'senza titolo'}",
        f"UNITA': {unita.get('id') or task.get('unit_id')} "
        f"({unita.get('domain') or 'senza blocco'}) — {unita.get('title') or ''}".rstrip(),
        f"TIPO: {tipo or 'non dichiarato'}"
        + (
            f" · stato nel registro: {registro.get('status')}"
            + (f" (tentativo {registro.get('attempt')})" if registro.get("attempt") else "")
            if registro
            else ""
        ),
    ]
    if unita.get("deliverable"):
        righe += ["", f"RISULTATO ATTESO DELL'UNITA': {unita['deliverable']}"]
    if registro.get("status") in ("needs_changes", "failed"):
        righe += [
            "",
            "QUESTA FASE E' STATA RESPINTA IN VERIFICA: leggi il report precedente e il suo verdetto",
            f"({registro.get('report') or 'il report della fase'}) prima di ricominciare. Il nuovo",
            "tentativo si misura sugli stessi casi che l'hanno respinta.",
        ]
    if criteria:
        righe += ["", "CRITERI DI ACCETTAZIONE (dal registro):"]
        righe += [f"- {str(c).strip()}" for c in criteria]
    # DUE FASI DELLA STESSA UNITA' INSIEME. La catena A -> E -> T -> R e' una catena perche' ogni
    # fase MISURA l'output della precedente. Il registro non lo impone (le dipendenze dichiarate sono
    # fra unita'), e la pagina offriva le fasi in parallelo: misurato il 2026-10-16, ZIP02E e ZIP02T
    # prese nello stesso minuto. Non si vieta — la pratica del pack e' che il tester DERIVI i casi dal
    # design prima di vedere l'esecuzione — ma si dice cosa non si puo' fare: misurare su byte che si
    # stanno muovendo. E' la classe di difetto che ha bruciato `UPL04ZR` per undici atti.
    unita_di = str(task.get("unit_id") or "")
    altre = [
        str(voce.get("task_id"))
        for voce in state.get("active_claims") or []
        if str(voce.get("task_id") or "").startswith(unita_di)
        and str(voce.get("task_id")) != str(fase)
        and voce.get("status") in ("active", "taken", "active_extension")
        and not str(voce.get("released_at") or "").strip()
    ]
    if altre:
        # Chi misura: la verifica indipendente. La R giudica, la E scrive, la A progetta: la frase si
        # adatta al gesto che questa fase fa davvero.
        suffisso = str(fase)[len(str(task.get("unit_id") or "")) :] or str(fase)
        elenco = ", ".join(sorted(set(altre)))
        gesto = {
            "T": (
                "Derivare i casi dal design adesso va bene; FARLI GIRARE no. Aspetta che quella fase "
                "consegni: se i byte si muovono sotto la corsa, il verdetto nasce vecchio e va rifatto."
            ),
            "R": (
                "Giudicare adesso significa giudicare byte che si stanno muovendo: aspetta la consegna, "
                "oppure accetta dichiarando il limite — ma dichiaralo."
            ),
            "E": (
                "Stai per scrivere nella stessa unità in cui quella fase lavora: leggi i path che ha "
                "dichiarato prima del primo byte, e se sono gli stessi, fermati e dillo."
            ),
        }.get(
            suffisso.upper(),
            "Puoi procedere, ma dichiara il perimetro sapendo che quei byte si muovono.",
        )
        righe += [
            "",
            f"ATTENZIONE — QUESTA UNITA' HA UN'ALTRA FASE IN CORSO: {elenco}.",
            gesto,
        ]
    righe += [
        "",
        "COSA FARE (il registro non lo dice: va scritto qui prima di cominciare)",
        "DA COMPLETARE — in una riga: cosa deve esistere quando questa fase e' finita.",
        "",
        f"CONSEGNA: {consegna} (verifica che NON esista) e il puntatore "
        f"{ws.deliverable_prefix}{fase}.yaml.",
    ]
    if revisione:
        righe += [
            "",
            f"PERIMETRO E REVISIONE ({fonte_revisione}, impronte di adesso):",
        ]
        righe += [f"- {voce['path']}  {voce['sha256'][:16]}…" for voce in revisione]
    else:
        righe += [
            "",
            "PERIMETRO: dichiara qui i file che tocchi — il registro per questa fase non ne ha.",
        ]
    righe += [
        "",
        f"REGISTRO: in {ws.state} esiste la voce di claim {fase}: e' tua. NON scrivere il registro",
        f"a mano: deposita in {ws.transitions}/ la presa con taken_by = il tuo nome canonico PRIMA",
        f"del primo byte, e la richiesta di rilascio alla fine (formato in {ws.transitions}/README.md).",
        "Se un'altra corsia l'ha gia' presa, fermati e dillo.",
    ]
    if atto_corto:
        # L'ACCETTAZIONE E' UN ATTO CORTO. Perche' la regola stia in piedi serve il cancello: senza,
        # chi giudica spende il turno a scoprire che il puntatore e' indietro o che la revisione si e'
        # mossa — misurato: dieci atti di ratifica respinti per apparato e zero informazioni di
        # prodotto su una sola unita'.
        righe += [
            "",
            "PRIMA DI GIUDICARE — IL CANCELLO (un comando, dieci secondi):",
            f"    python3 {percorso_preflight} --workspace {ws.root} --phase {fase}",
            "Se risponde PRONTA, giudica. Se risponde NON ANCORA, NON scrivere un atto: deposita il",
            "motivo nel report e fermati — un giudizio su una base vecchia nasce respinto.",
            "",
            "L'ATTO, CORTO: (1) leggi i criteri di accettazione qui sopra; (2) leggi i byte che il",
            "tester ha misurato; (3) giudica: accettato, accettato con limiti, oppure respinto;",
            "(4) dichiara i limiti e i residui che lascia, e cosa NON hai ripercorso col motivo.",
            "NON rieseguire le batterie del tester: la misura del comportamento e' la sua, e rifarla",
            "e' la stessa misura due volte. Rimisura solo cio' che dichiari di rimisurare.",
            "",
        ]
    else:
        righe += [
            "",
            "VERIFICA: prova SOLO cio' che tocchi, UNA volta, subito prima di consegnare. Dichiara",
            "comando, esito, durata e cio' che NON hai rieseguito, col motivo.",
            "",
        ]
        if tipo == "independent_verification":
            righe += [
                "VERIFICA CONTENUTA: se per questa fase esiste gia' un atto, non rieseguire l'intera",
                "batteria. Parti dal tentativo precedente, riesegui i casi che hanno respinto e quelli",
                "che esercitano le funzioni toccate dall'ultimo E; nel report elenca i casi eseguiti,",
                "quelli NON rieseguiti e il motivo. Suite completa, MySQL e browser restano fuori",
                "salvo che il contratto della fase li richieda.",
                "",
            ]
    righe += [
        "TESTIMONE: nel report scrivi `next` con cosa c'e' da fare dopo. Chi prende il lavoro da te",
        "lo deve leggere dalla pagina del coordinatore, non da una chat.",
    ]
    return {
        "source": "composto dal registro (il quaderno non ha una sezione per questa fase)",
        "role": ruolo,
        "text": "\n".join(righe).strip() + "\n",
        "missing": [] if criteria else ["criteri di accettazione"],
        "revision_source": fonte_revisione,
    }


def per(ws, fase, state=None):
    """Il prompt della fase: la BUSTA che dichiara il lavoro davanti al corpo.

    Il corpo viene dal quaderno (scritto a mano: vale di piu') o, se il quaderno tace, composto dal
    registro. La busta e' SEMPRE la stessa e sta davanti a entrambi — e davanti anche a un ordine
    vecchio, dove il testo era stato congelato senza: «nei prompt nuovi non vedo la prima
    istruzione» (segnalato dall'utente) era esattamente questo, una busta che stava solo dentro il
    composto.

    `state` si passa gia' caricato quando c'e': evita di rileggere un registro da 1,9 MB per ogni
    riga della pagina.
    """
    # Cache per fase: la pagina chiede il prompt di ogni riga attivata insieme, e senza questa
    # ogni riga ricostruiva il quaderno (o componeva da capo) — misurato 4-5 s per prompt.
    # La cache vale finche' i registri non cambiano: il prompt porta dentro l'occorrenza della presa
    # e ora anche il perche' del rifacimento, e una copia di ieri non e' il prompt di oggi.
    chiave = (str(ws.root), fase, _versione_registri(ws))
    if chiave in _CACHE:
        return _CACHE[chiave]
    dal_quaderno = activate.prompt_per(ws, fase)
    # Un corpo CONGELATO serve a chi ha gia' ricevuto QUEL prompt. Se l'attempt che nomina esiste
    # gia' su disco, non e' il prompt di un nuovo atto: riproporlo manderebbe a scrivere sopra una
    # consegna (misurato il 2026-10-17 su HIST02A: ordine dell'attempt 1, e attempt-1 gia' c'era).
    if dal_quaderno and dal_quaderno.get("text") and consegna_gia_scritta(
        ws, fase, dal_quaderno["text"]
    ):
        dal_quaderno = None
    if dal_quaderno and dal_quaderno.get("text"):
        esito = {
            "source": f"{dal_quaderno['source']} (corpo)",
            "role": None,
            "text": dal_quaderno["text"],
            "missing": [],
        }
    else:
        esito = componi(ws, fase, state=state)
    perche = _perche(ws, fase, state)
    if perche:
        # In testa al corpo, subito dopo la busta: in un rifacimento la prima cosa da leggere è
        # perché la fase è tornata in mano, non il contratto generale che l'agente conosce già.
        esito = {**esito, "text": perche.strip() + "\n\n" + esito["text"]}
    esito = {**esito, "text": con_busta(ws, fase, esito["text"]), "envelope": True}
    _CACHE[chiave] = esito
    return esito


def _versione_registri(ws):
    """Il tempo di scrittura di registro e task: due `stat`, per non servire un prompt vecchio."""
    try:
        return (ws.state_path.stat().st_mtime_ns, ws.path(ws.tasks).stat().st_mtime_ns)
    except OSError:
        return (0, 0)


def consegna_gia_scritta(ws, fase, testo):
    """Il testo nomina un `attempt-N` di questa fase che esiste gia' su disco?"""
    schema = re.compile(
        rf"{re.escape(str(ws.deliverable_prefix))}{re.escape(str(fase))}/attempt-(\d+)\.ya?ml"
    )
    for trovato in schema.finditer(str(testo or "")):
        if (ws.root / trovato.group(0)).is_file():
            return True
    return False


def _blocco_testimone(ws, fase, voce, titolo="COSA HA LASCIATO CHI È VENUTO PRIMA", nomina=True):
    """Il testo del testimone, coi finding bloccanti che riguardano questa fase."""
    testo = str(voce.get("text") or "").strip()
    if not testo:
        return ""
    quando = str(voce.get("when") or "")[:16].replace("T", " ")
    # I finding BLOCCANTI che riguardano questa fase, per identificativo: «leggi il report» da
    # solo non dice quanti sono né quali. Si citano, non si riscrivono: il testo resta nel report.
    bloccanti = []
    try:
        sorgente = ws.root / str(voce.get("source") or "")
        documento = _carica(sorgente.read_text(encoding="utf-8", errors="replace")) or {}
        for finding in documento.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            gravita = str(finding.get("severity") or "").lower()
            proprietario = str(finding.get("owner") or "")
            if "block" in gravita and (not proprietario or str(fase) in proprietario):
                bloccanti.append(f"{finding.get('id') or '—'} ({finding.get('severity')})")
    except (OSError, yaml.YAMLError):
        bloccanti = []
    coda = (
        "\nBloccanti per te in quell'atto: " + ", ".join(bloccanti) + "."
        if bloccanti
        else ""
    )
    introduzione = f"nomina {fase} e dice" if nomina else "ha respinto l'unità e dice"
    return (
        f"\n\n═══ {titolo} ═══\n"
        f"Il report {voce.get('source') or '—'} ({quando}) {introduzione}:\n"
        f"{testo}{coda}\n"
        "Leggi quell'atto prima di toccare i byte: quello che chiede è il lavoro da fare; "
        "i finding bloccanti e i limiti sono nel suo report."
    )


def _verifica_respinta(ws, fase, state):
    """L'ultima verifica dell'unità, se è rossa e più recente dell'ultimo atto di questa fase.

    Serve ai report che descrivono i difetti senza ripetere il codice della fase da riprendere:
    A11Y01T dice «prima di una nuova ratifica correggi F1/F2/F3» e nomina solo R. La coda sa che il
    rifacimento è E; il prompt di E deve sapere lo stesso, non solo il percorso.
    """
    try:
        import handoff

        tasks_doc = _carica(ws.path(ws.tasks).read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        return None
    task = next((t for t in tasks_doc.get("tasks") or [] if str(t.get("id")) == str(fase)), None)
    unita = str((task or {}).get("unit_id") or "")
    if not unita:
        return None
    ultimo, _, _, _ = handoff.ultimo_report(ws, state, fase)
    for altra in tasks_doc.get("tasks") or []:
        if str(altra.get("unit_id")) != unita:
            continue
        if str(altra.get("kind")) != "independent_verification":
            continue
        percorso, _, _, documento = handoff.ultimo_report(ws, state, str(altra.get("id")))
        if not documento:
            continue
        if not str(documento.get("verdict") or "").startswith(("fail", "needs_changes")):
            continue
        if ultimo and percorso and percorso.stat().st_mtime <= ultimo.stat().st_mtime:
            continue
        if not str(documento.get("next") or "").strip():
            continue
        return {
            "source": str(percorso.relative_to(ws.root)) if percorso else "",
            "when": str(documento.get("published_at") or documento.get("prepared_at") or ""),
            "text": str(documento.get("next") or ""),
        }
    return None


def _perche(ws, fase, state=None):
    """Il testimone di chi nomina questa fase nel suo `next`: cosa ha lasciato e cosa chiede.

    Vale per un rifacimento E per un handoff normale: `HIST02A` consegna un design con tre finding
    bloccanti per `HIST02E`, e senza questo blocco il prompt di E sarebbe identico a quello di una
    fase mai cominciata. Se nessun report nomina la fase ma la verifica dell'unità è rossa e più
    recente, si cita quella: è il caso di A11Y01T che descrive i difetti senza scrivere «E».
    """
    if not isinstance(state, dict):
        return ""
    try:
        import handoff  # import locale: `handoff` legge i report, `mandate` compone il prompt

        voci = handoff.dovuto(ws, state=state, limite=200)
    except Exception:  # noqa: BLE001 - un prompt senza il perche' resta un prompt valido
        voci = []
    for voce in voci:
        if str(fase) not in {str(codice.get("code")) for codice in voce.get("codes") or []}:
            continue
        blocco = _blocco_testimone(ws, fase, voce)
        if blocco:
            return blocco
    voce = _verifica_respinta(ws, fase, state)
    if voce:
        return _blocco_testimone(ws, fase, voce, "COSA HA LASCIATO LA VERIFICA", nomina=False)
    return ""


def testimone(ws, fase, state=None):
    """Il blocco del testimone, per chi compone un prompt fuori da `per` (per esempio un ordine
    congelato): il corpo dell'ordine resta quello consegnato, ma non deve perdere cosa ha lasciato
    chi è venuto prima."""
    return _perche(ws, fase, state)


def busta(ws, fase):
    """La PRIMA ISTRUZIONE: dichiara che il lavoro sta andando, col deposito pronto da fare.

    Finche' la presa non e' applicata, per la piattaforma non e' partito niente e la pagina continua
    a dire «in attesa di un esecutore» mentre il lavoro e' gia' cominciato — e una seconda copia
    dello stesso prompt non trova nessun ostacolo. Per questo e' la PRIMA riga, e per questo la
    mette il coordinatore invece di sperare che chi scrive il prompt se ne ricordi.
    """
    occorrenza = _occorrenza_per(ws, fase)
    return "\n".join(
        [
            "════ PRIMA ISTRUZIONE — DICHIARA CHE STAI LAVORANDO, PRIMA DI QUALUNQUE ALTRA COSA ════",
            f"Questa fase e' {fase} e la stai prendendo TU: deposita la presa adesso, sul registro.",
            "",
            f"Scrivi il file {ws.transitions_dir}/<timestamp>-<tua-corsia>.yaml con DENTRO:",
            "",
            "    schema: project-console-transition/1.0",
            "    requested_by: <la tua corsia>",
            "    requested_at: '<adesso, ISO>'",
            f"    file: {ws.state}",
            f'    anchor: "- task_id: {fase}"',
            f"    occurrence: {occorrenza}      # l'occorrenza di QUESTA voce nel registro",
            "    field: status",
            "    text: taken",
            "",
            "SE LA VOCE HA GIA' UN released_at (una presa precedente chiusa), azzeralo con una seconda",
            "richiesta sulla stessa occorrenza (field: released_at, text: ''): senza, la fase risulta",
            "rilasciata e la pagina continua a dire «in attesa».",
            "",
            # Lo schema lo dichiara il progetto, e questa riga viaggia con OGNI prompt (la busta sta
            # davanti anche al testo del quaderno): una piattaforma che scrive nei registri di un
            # progetto non gli impone il proprio formato di report.
            f"SCHEMA DEI REPORT DI QUESTO PROGETTO: {ws.report_schema} (puntatore: {ws.pointer_schema}).",
            "I campi che la piattaforma legge restano quelli del contratto — `verdict`, `published_at`,",
            "`next` — e tutto il resto e' del progetto.",
            "",
            "e subito dopo, nella stessa voce, due richieste: taken_by: <la tua corsia> e",
            "taken_at: '<adesso>'. Poi fallo applicare al coordinamento:",
            # Il percorso del coordinatore, ASSOLUTO: dentro il progetto di solito non esiste una
            # cartella `registers/` — un agente l'ha segnalato («il comando non esiste in questo
            # repository») dopo aver perso tempo a cercarla.
            f"    python3 {Path(__file__).resolve().parent / 'apply_transitions.py'} --workspace {ws.root} --dir {ws.transitions_dir}",
            "",
            "Se il registro dice che la fase e' GIA' presa da un altro, FERMATI e dillo: due esecutori",
            "sugli stessi byte sono il difetto piu' caro. Alla fine del lavoro deposita il rilascio",
            "(status: released e released_at INSIEME): cosi' la pagina sa che hai finito.",
            "",
            "L'effetto che vedrai: appena la presa e' applicata, la pagina passa da «in attesa di un",
            "esecutore» a «in corso», col tuo nome e l'ora.",
            "══════════════════════════════════════════════════════════════════════════════════════",
        ]
    )


def con_busta(ws, fase, testo):
    """Il testo con la busta davanti, una volta sola: se c'e' gia', non si raddoppia."""
    corpo = str(testo or "").strip()
    if corpo.startswith("════ PRIMA ISTRUZIONE"):
        return corpo + "\n"
    return busta(ws, fase) + "\n\n" + corpo + "\n"


def senza_busta(testo):
    """Il CORPO, tolta la busta. Serve a confrontare due prompt senza che la differenza sia
    soltanto l'involucro (che cambia quando cambia la busta, non il mandato)."""
    corpo = str(testo or "")
    if corpo.startswith("════ PRIMA ISTRUZIONE"):
        riga = corpo.find("══════════════════════════════════════")
        if riga != -1:
            return corpo[corpo.find("\n", riga) :].strip()
    return corpo.strip()


def impronta(testo):
    """L'impronta del prompt: serve a dire se quello congelato e' ancora quello giusto."""
    import hashlib

    return hashlib.sha256(str(testo or "").encode("utf-8")).hexdigest()


def da_ordine(ws, fase):
    """Il prompt congelato nell'ordine depositato per quella fase, se c'e'.

    E' il testo che un esecutore ha ricevuto: si legge da li' invece di ricomporlo, perche' un
    prompt che cambia dopo essere stato consegnato e' un prompt perso.
    """
    for nome in sorted(activate.ordini_aperti(ws).get(fase) or []):
        percorso = ws.root / nome
        if not percorso.is_file():
            continue
        documento = _leggi(percorso)
        testo = documento.get("prompt")
        if testo:
            return {
                "file": nome,
                "text": testo,
                "sha256": documento.get("prompt_sha256") or impronta(testo),
                "frozen_at": documento.get("prompt_frozen_at"),
                "source": documento.get("prompt_source"),
            }
    return None


#: Cache dei prompt composti, per (workspace, fase).
_CACHE = {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="radice del workspace (default: cwd o $CONSOLE_WORKSPACE)")
    parser.add_argument("--phase", required=True, help="la fase di cui comporre il prompt")
    args = parser.parse_args(argv)
    ws = Workspace.load(args.workspace)
    next_prompts.configure(queue=ws.queue, deliverable_prefix=ws.deliverable_prefix)
    esito = per(ws, args.phase)
    print(f"# fonte: {esito['source']}")
    print(esito["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
