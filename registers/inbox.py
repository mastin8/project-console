#!/usr/bin/env python3
"""La posta in arrivo: i messaggi che arrivano, e che non devono morire.

Perche' esiste. Un agente che finisce manda un messaggio: la presa, il rilascio e il `next` del
report finiscono nei registri — quelli la piattaforma li legge — ma TUTTO IL RESTO di quel
messaggio (cosa ha consegnato, cosa non ha fatto, cosa serve dopo, cosa ha scoperto per strada)
resta in una chat. E una chat non e' un archivio: si perde, e con lei il lavoro fatto.

Misurato sul progetto di origine il 2026-10-16: 203 direzioni dichiarate nei report, e 41 consegne
**senza direzione** — cioe' 41 messaggi che contenevano qualcosa e non sono arrivati a nessun file.

Questa e' la cassetta dove si deposita quel messaggio, INTERO e COME E' ARRIVATO. Non serve un
formato da rispettare, non serve indovinare un campo: una ricevuta e' un file di testo con quattro
righe di intestazione e il messaggio sotto, parola per parola.

Perche' un file per messaggio e non un campo nei registri:

* i registri sono vivi e contesi — scriverci dentro dalla pagina richiede il lock e la validazione,
  e una scrittura sbagliata ferma le corsie. La posta e' una cartella a parte: nessun lock, nessun
  rischio per lo stato vivo;
* un messaggio puo' parlare di una fase che non esiste ancora (un prompt nuovo, un'idea, un
  vincolo): nei registri non avrebbe dove stare;
* il testo si deposita VERBATIM. Dentro un YAML ogni riga andrebbe quotata, e il primo apice
  storto corrompe il messaggio che si voleva salvare.

Una ricevuta si dice **lavorata** quando esiste un report di quella fase scritto DOPO di lei: e' una
misura, non una promessa. Chi vuole chiuderla a mano lo dice (`--chiudi`).

Uso::

    python3 registers/inbox.py --workspace <progetto> --list          # cosa e' arrivato
    python3 registers/inbox.py --workspace <progetto> --list --json    # per la pagina
    python3 registers/inbox.py --workspace <progetto> --add --text "..." --phase ES01R
    python3 registers/inbox.py --workspace <progetto> --add --file messaggio.md --phase ES01R
    python3 registers/inbox.py --workspace <progetto> --chiudi <ricevuta> --nota "lavorata"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workspace import Workspace, lock_file  # noqa: E402

#: Le nature di una ricevuta. Non sono un vincolo: sono un'etichetta per raggruppare in pagina.
KINDS = ("consegna", "direzione", "decisione", "nota")

RICHIESTA = "---"


def _carica(flusso):
    """Legge un frammento YAML col parser veloce quando c'e' (libyaml)."""
    caricatore = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return yaml.load(flusso, Loader=caricatore)


def _momento(valore):
    """Una data da quello che c'e' scritto, o da niente.

    Una data SENZA fuso si legge come ora locale, non come UTC: e' la convenzione che la linea del
    tempo usa gia' (`timeline.local_date`), ed e' quella giusta, perche' le date di questi registri
    le scrive chi lavora, col proprio orologio. Leggerle come UTC le sposterebbe di due ore e — qui
    — basterebbe questo a far risultare «lavorata» una ricevuta che nessuno ha aperto.
    """
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.astimezone()
    if not valore:
        return None
    testo = str(valore).strip().replace("Z", "+00:00")
    try:
        momento = datetime.fromisoformat(testo)
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.astimezone()


def cartella(ws) -> Path:
    """Dove vive la posta. Non si crea leggendo: chi deposita la trova, chi legge vede vuoto."""
    return ws.path(getattr(ws, "inbox", "inbox"))


def _intestazione(grezzo: str):
    """(intestazione, corpo) di una ricevuta. Senza intestazione, il file e' tutto messaggio."""
    if not grezzo.startswith(RICHIESTA):
        return {}, grezzo
    pezzi = grezzo.split(RICHIESTA, 2)
    if len(pezzi) < 3:
        return {}, grezzo
    try:
        testa = _carica(pezzi[1]) or {}
    except yaml.YAMLError:
        return {}, grezzo
    if not isinstance(testa, dict):
        return {}, grezzo
    return testa, pezzi[2].lstrip("\n")


def _fase_di(testa, nome, ws):
    """La fase che una ricevuta riguarda: dalla sua intestazione o dal nome del file."""
    fase = testa.get("phase") or testa.get("task_id")
    if fase:
        return str(fase).strip()
    # `20261016T1015-A11Y03R-corsia.md`: la fase e' la parola dopo il timestamp.
    parti = Path(nome).stem.split("-")
    return parti[1] if len(parti) > 1 and parti[0][:8].isdigit() else ""


def _quando_report(percorso):
    """(data, come lo so) di un report: prima la data che DICHIARA, poi l'mtime.

    Perche' non basta l'mtime: un `git pull`, un `touch`, un checkout riscrivono i file senza che
    nessuno abbia lavorato niente, e tutte le ricevute risulterebbero lavorate in un colpo — con la
    pagina che dice verde su un messaggio che nessuno ha letto. La data dichiarata dal report
    (`published_at`) non si muove da sola.
    """
    try:
        documento = _carica(percorso.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        documento = {}
    if isinstance(documento, dict):
        for chiave in ("published_at", "prepared_at", "completed_at", "dated"):
            momento = _momento(documento.get(chiave))
            if momento:
                return momento, "dichiarata"
    return datetime.fromtimestamp(percorso.stat().st_mtime).astimezone(), "mtime"


def _report_dopo(ws, fase: str, quando):
    """Il report di quella fase scritto dopo la ricevuta: e' la misura del «lavorata»."""
    if not fase or quando is None:
        return None
    candidati = []
    puntatore = ws.reports_dir / f"{fase}.yaml"
    if puntatore.is_file():
        candidati.append(puntatore)
    cartella_tentativi = ws.reports_dir / fase
    if cartella_tentativi.is_dir():
        candidati.extend(cartella_tentativi.glob("attempt-*.yaml"))
    dopo = [
        (percorso, _quando_report(percorso))
        for percorso in candidati
    ]
    # Se la fase ha anche un solo report che DICHIARA la sua data, si misura su quella e basta:
    # mescolare le due misure rimetterebbe in gioco l'mtime che si voleva togliere di mezzo.
    dichiarate = [voce for voce in dopo if voce[1][1] == "dichiarata"]
    misurate = dichiarate or dopo
    dopo = [voce for voce in misurate if voce[1][0] > quando]
    if not dopo:
        return None
    return max(dopo, key=lambda voce: voce[1][0])[0]


def voci(ws, tutte: bool = False):
    """Le ricevute, dalla piu' recente. Con `tutte=False` solo quelle non ancora lavorate."""
    base = cartella(ws)
    fuori = []
    if not base.is_dir():
        return fuori
    for percorso in sorted(base.glob("*.md")):
        # La documentazione della cartella non e' un messaggio: leggerla come tale la farebbe
        # comparire in pagina come «ricevuta da lavorare», che e' falso e rumoroso.
        if percorso.name.startswith((".", "_")) or percorso.stem.upper() == "README":
            continue
        grezzo = percorso.read_text(encoding="utf-8", errors="replace")
        testa, corpo = _intestazione(grezzo)
        quando = _momento(testa.get("received_at")) or datetime.fromtimestamp(
            percorso.stat().st_mtime
        ).astimezone()
        fase = _fase_di(testa, percorso.name, ws)
        chiusa = _momento(testa.get("closed_at"))
        report = None if chiusa else _report_dopo(ws, fase, quando)
        voce = {
            "ricevuta": percorso.stem,
            "file": str(percorso.relative_to(ws.root)),
            "phase": fase,
            "unit": str(testa.get("unit") or ""),
            "sender": str(testa.get("sender") or testa.get("from") or ""),
            "kind": str(testa.get("kind") or "nota"),
            "received_at": quando,
            "testo": corpo.strip(),
            "caratteri": len(corpo.strip()),
            "closed_at": chiusa,
            "worked_by": str(report.relative_to(ws.root)) if report else None,
        }
        voce["aperta"] = not chiusa and report is None
        if tutte or voce["aperta"]:
            fuori.append(voce)
    fuori.sort(key=lambda voce: voce["received_at"], reverse=True)
    return fuori


def non_lavorate(ws):
    """Quante ricevute nessuno ha ancora lavorato: e' il numero che va tenuto a zero."""
    return len(voci(ws, tutte=False))


def _nome(ws, fase: str, quando: datetime) -> Path:
    """`<timestamp>-<fase o nota>.md`, con un numero in coda se quel nome e' gia' preso."""
    base = cartella(ws)
    base.mkdir(parents=True, exist_ok=True)
    radice = f"{quando.strftime('%Y%m%dT%H%M%S')}-{fase or 'nota'}"
    for tentativo in range(1, 100):
        nome = f"{radice}.md" if tentativo == 1 else f"{radice}-{tentativo}.md"
        percorso = base / nome
        if not percorso.exists():
            return percorso
    raise RuntimeError(f"troppe ricevute nello stesso secondo in {base}")


def archivia(ws, testo, phase=None, sender=None, unit=None, kind=None, quando=None):
    """Deposita un messaggio nella posta, INTERO e senza interpretarlo.

    Il testo non si riscrive, non si riassume e non si quota: e' l'unica cosa che questa funzione
    deve garantire. Una ricevuta senza testo si rifiuta, perche' un file vuoto nella posta e' la
    cosa peggiore: sembra che il messaggio ci sia.
    """
    testo = (testo or "").strip()
    if not testo:
        raise ValueError("una ricevuta senza testo non e' una ricevuta")
    fase = str(phase or "").strip()
    when = quando or datetime.now().astimezone()
    percorso = _nome(ws, fase, when)
    testa = {
        "ricevuta": percorso.stem,
        "received_at": when.isoformat(timespec="seconds"),
        "sender": str(sender or "").strip(),
        "phase": fase,
        "unit": str(unit or "").strip(),
        "kind": str(kind or ("direzione" if fase else "nota")).strip(),
    }
    corpo = (
        f"{RICHIESTA}\n"
        + yaml.safe_dump(testa, sort_keys=False, allow_unicode=True).strip()
        + f"\n{RICHIESTA}\n\n"
        + testo
        + "\n"
    )
    # Scrittura atomica: il file compare intero o non compare. Una ricevuta a meta' e' peggio di
    # nessuna ricevuta, perche' nessuno va a controllare se c'era dell'altro.
    provvisorio = percorso.with_suffix(".md.parziale")
    provvisorio.write_text(corpo, encoding="utf-8")
    os.replace(provvisorio, percorso)
    return {
        "ricevuta": percorso.stem,
        "file": str(percorso.relative_to(ws.root)),
        "phase": fase,
        "kind": testa["kind"],
        "caratteri": len(testo),
    }


def trova(ws, identificatore: str) -> Path:
    """La ricevuta da un identificatore: il nome, il nome con estensione, o un pezzo unico."""
    base = cartella(ws)
    if not base.is_dir():
        raise ValueError(f"nessuna posta in {base}")
    cercato = Path(str(identificatore)).stem
    esatte = [p for p in base.glob("*.md") if p.stem == cercato]
    if esatte:
        return esatte[0]
    parziali = [p for p in base.glob("*.md") if cercato in p.stem]
    if len(parziali) == 1:
        return parziali[0]
    if not parziali:
        raise ValueError(f"nessuna ricevuta «{identificatore}» in {base}")
    raise ValueError(
        f"«{identificatore}» non e' unica: {', '.join(sorted(p.stem for p in parziali)[:5])}"
    )


def chiudi(ws, identificatore: str, nota=None):
    """Chiude una ricevuta: da qui in poi non conta piu' fra quelle da lavorare.

    Si scrive nell'INTESTAZIONE, sotto il lock, perche' e' l'unico campo che la piattaforma
    modifica: il messaggio sotto non si tocca nemmeno per aggiungere una nota.
    """
    percorso = trova(ws, identificatore)
    with open(lock_file(ws.root), "a+") as maniglia:
        import fcntl

        fcntl.flock(maniglia, fcntl.LOCK_EX)
        try:
            grezzo = percorso.read_text(encoding="utf-8", errors="replace")
            testa, corpo = _intestazione(grezzo)
            testa["closed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            if nota:
                testa["closed_note"] = str(nota)
            percorso.write_text(
                f"{RICHIESTA}\n"
                + yaml.safe_dump(testa, sort_keys=False, allow_unicode=True).strip()
                + f"\n{RICHIESTA}\n\n"
                + corpo,
                encoding="utf-8",
            )
        finally:
            fcntl.flock(maniglia, fcntl.LOCK_UN)
    return {"ricevuta": percorso.stem, "file": str(percorso.relative_to(ws.root))}


def rendi(voce) -> str:
    """Una riga leggibile: cosa ha lasciato, chi, quando, e se e' stata lavorata."""
    quando = voce["received_at"].astimezone().strftime("%Y-%m-%d %H:%M")
    stato = (
        "chiusa"
        if voce["closed_at"]
        else (f"lavorata da {voce['worked_by']}" if voce["worked_by"] else "DA LAVORARE")
    )
    return " · ".join(
        parte
        for parte in (voce["phase"] or "(senza fase)", voce["kind"], voce["sender"] or "-", quando, stato)
        if parte
    )


def _slug(testo: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", testo.strip())[:40].strip("-")


def main(argv=None):
    analizzatore = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizzatore.add_argument("--workspace", required=True, help="la radice del progetto")
    analizzatore.add_argument("--add", action="store_true", help="deposita una ricevuta")
    analizzatore.add_argument("--text", help="il messaggio, come e' arrivato")
    analizzatore.add_argument("--file", help="il messaggio sta in questo file: si copia intero")
    analizzatore.add_argument("--phase", default="", help="la fase che il messaggio riguarda")
    analizzatore.add_argument("--unit", default="", help="l'unita' che il messaggio riguarda")
    analizzatore.add_argument("--from", dest="sender", default="", help="chi lo lascia")
    analizzatore.add_argument("--kind", choices=KINDS, help="che cosa e' questo messaggio")
    analizzatore.add_argument("--chiudi", help="segna una ricevuta come lavorata")
    analizzatore.add_argument("--nota", help="con --chiudi: due parole su come e' stata chiusa")
    analizzatore.add_argument("--list", action="store_true", help="cosa e' arrivato")
    analizzatore.add_argument("--tutte", action="store_true", help="anche quelle lavorate")
    analizzatore.add_argument("--json", action="store_true", help="per la pagina")
    argomenti = analizzatore.parse_args(argv)

    ws = Workspace.load(argomenti.workspace)

    if argomenti.add:
        testo = argomenti.text
        if argomenti.file:
            testo = Path(argomenti.file).read_text(encoding="utf-8", errors="replace")
        if not testo:
            raise SystemExit("--add vuole --text oppure --file: senza messaggio non c'e' ricevuta")
        esito = archivia(
            ws,
            testo,
            phase=argomenti.phase,
            unit=argomenti.unit,
            sender=argomenti.sender,
            kind=argomenti.kind,
        )
        print(f"depositata {esito['ricevuta']} in {esito['file']} ({esito['caratteri']} caratteri)")
        return 0

    if argomenti.chiudi:
        esito = chiudi(ws, argomenti.chiudi, argomenti.nota)
        print(f"chiusa {esito['ricevuta']}")
        return 0

    elenco = voci(ws, tutte=argomenti.tutte)
    if argomenti.json:
        print(
            json.dumps(
                {
                    "cartella": str(cartella(ws)),
                    "non_lavorate": non_lavorate(ws),
                    "voci": [
                        {chiave: valore for chiave, valore in voce.items() if chiave != "received_at"}
                        | {"received_at": voce["received_at"].isoformat()}
                        for voce in elenco
                    ],
                },
                ensure_ascii=False,
                default=str,
            )
        )
        return 0
    if not elenco:
        print(f"posta in arrivo vuota ({cartella(ws)})")
        return 0
    for voce in elenco:
        print(f"{voce['ricevuta']}  {rendi(voce)}")
    print(f"\n{non_lavorate(ws)} non lavorate su {len(voci(ws, tutte=True))} ricevute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
