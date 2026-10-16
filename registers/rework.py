#!/usr/bin/env python3
"""Quante volte una fase e' gia' tornata indietro, e per cosa.

Perche' esiste. La pagina diceva «respinta in verifica» e metteva la fase nella coda col pulsante
«Attiva»: identica a una fase respinta ieri per la prima volta. Ma una fase respinta DIECI volte,
sempre per gli stessi due motivi, non e' la stessa cosa: li' un altro tentativo non e' la leva, e
l'utente lo scopre solo leggendo dieci report a mano. Misurato sul progetto di origine il
2026-10-16: `UPL04ZR` 10 tentativi e 10 respinte, con `UPL04Z-DISTINCT-SIGNATURE` e
`UPL04Z-T-ON-CURRENT-REVISION` in TUTTI e dieci — e il primo dei due dichiara di essere dovuto
dall'utente, non da un agente. `NAV03R` 7 respinte, `TODO03E` 9 atti di cui 2 rifiutati come
dispatch stantio.

Questo modulo misura tre cose, e nient'altro:

* quanti tentativi esistono su disco, e con quale verdetto;
* quali residui/finding TORNANO, in quante prove, e se bloccanti;
* chi li deve, quando il report lo dice (`owner`): e' la riga che distingue «serve un altro
  tentativo» da «serve una decisione che nessun agente puo' prendere».

Non decide niente e non scrive niente: e' una lettura dei report, come la linea del tempo.

Uso::

    python3 registers/rework.py --workspace <progetto>            # le fasi che tornano indietro
    python3 registers/rework.py --workspace <progetto> --fase X   # una sola
    python3 registers/rework.py --workspace <progetto> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workspace import Workspace  # noqa: E402

#: Un verdetto che consegna. Tutto il resto e' un atto che NON ha chiuso la fase.
POSITIVI = ("pass", "accepted", "delivered", "ok")
#: Sotto questa soglia una ripetizione e' statistica, non un ostacolo.
SOGLIA = 3
#: Un identificatore che NOMINA un ostacolo: parole maiuscole legate da trattini
#: (`UPL04Z-DISTINCT-SIGNATURE`). Non lo sono `R1`, `F2`, `T4`: quelle sono numerazioni LOCALI
#: all'atto, e contarle insieme direbbe che «R1» torna da sette atti — quando l'R1 dell'atto 1 e
#: l'R1 dell'atto 7 sono due cose diverse. Misurato: senza questa distinzione NAV03R risultava con
#: «lo stesso ostacolo in 6 su 6: R1», che e' falso.
STABILE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
#: Un ostacolo che riguarda la FIRMA, non il prodotto: non e' lavoro da rifare, e' una condizione.
#: Serve a dirlo in pagina, perche' e' la differenza fra «rifai» e «serve qualcuno che firmi» — e
#: chi legge una riga che dice «non si sblocca con un altro tentativo» su una cosa che si sblocca (con
#: una firma) non sa cosa fare.
FIRMA = re.compile(r"signature|firmat|firma|indipendenz|independence|indipendent", re.I)
#: Il report dichiara che la sostanza e' chiusa e resta solo la firma. E' la sua frase, non una mia
#: lettura: «nessuno per la sostanza: chiuso da questo atto sui byte di …; la sola parte viva e'
#: l'indipendenza della firma». Serve a non scrivere «rifai» ne' «non si sblocca» su una cosa che si
#: sblocca in un modo preciso.
CHIUSA_SALVO_FIRMA = re.compile(
    r"nessuno per la sostanza|la sola parte viva|chiuso da questo atto|resta (solo|soltanto) la firma",
    re.I,
)


def _carica(testo):
    return yaml.load(testo, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def _leggi(percorso: Path):
    try:
        return _carica(percorso.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _numero(percorso: Path) -> int:
    trovato = re.findall(r"\d+", percorso.stem)
    return int(trovato[0]) if trovato else 0


def _positivo(verdetto: str) -> bool:
    testo = str(verdetto or "").lower()
    return any(testo.startswith(prefisso) for prefisso in POSITIVI)


def stabile(identificatore: str) -> bool:
    """Se un identificatore nomina un ostacolo, o e' solo il numero della riga in quell'atto."""
    return bool(STABILE.match(str(identificatore).strip()))


def _residui(documento):
    """I residui e i finding di un atto, nella forma (id, bloccante, chi, prima_di).

    Due nomi per la stessa cosa: `residuals` (cio' che l'atto lascia aperto) e `findings` (cio' che
    ha trovato). Si leggono entrambi, e si accettano sia la lista di dizionari sia la mappa
    id -> dizionario, perche' sul progetto di origine convivono.
    """
    fuori = []
    for chiave in ("residuals", "findings"):
        valore = documento.get(chiave)
        voci = []
        if isinstance(valore, list):
            voci = [voce if isinstance(voce, dict) else {"id": voce} for voce in valore]
        elif isinstance(valore, dict):
            voci = [
                dict(voce, id=voce.get("id") or chiave_id)
                for chiave_id, voce in valore.items()
                if isinstance(voce, dict)
            ]
        for voce in voci:
            identificatore = voce.get("id") or voce.get("code") or voce.get("name")
            if not identificatore:
                continue
            fuori.append(
                {
                    "id": str(identificatore).strip(),
                    "bloccante": bool(voce.get("blocking") or voce.get("bloccante")),
                    "chi": str(voce.get("owner") or voce.get("chi") or "").strip(),
                    "prima_di": str(voce.get("required_before") or "").strip(),
                    "nota": str(voce.get("what") or voce.get("why") or voce.get("reason") or "").strip(),
                }
            )
    return fuori


def per_fase(ws, fasi=None, soglia: int = SOGLIA):
    """Le fasi che tornano indietro, con la misura della ripetizione.

    `fasi` limita la lettura (la coda chiede solo le respinte): leggere i report di tutte le fasi di
    un progetto maturo costa, e non serve a nessuno mostrare la storia di una fase accettata.
    """
    fuori = {}
    if fasi is None:
        if not ws.reports_dir.is_dir():
            return fuori
        fasi = sorted(
            {
                percorso.parent.name if percorso.parent != ws.reports_dir else percorso.stem
                for percorso in ws.reports_dir.glob("*.yaml")
            }
            | {cartella.name for cartella in ws.reports_dir.iterdir() if cartella.is_dir()}
        )
    for fase in fasi:
        cartella = ws.reports_dir / str(fase)
        if not cartella.is_dir():
            continue
        tentativi = sorted(cartella.glob("attempt-*.yaml"), key=_numero)
        if not tentativi:
            continue
        verdetti = Counter()
        respinte = 0
        visti = {}
        for percorso in tentativi:
            documento = _leggi(percorso)
            verdetto = str(documento.get("verdict") or "senza-verdetto")
            verdetti[verdetto] += 1
            if not _positivo(verdetto):
                respinte += 1
            for residuo in _residui(documento):
                voce = visti.setdefault(
                    residuo["id"],
                    {
                        "id": residuo["id"],
                        "volte": 0,
                        "bloccante": False,
                        "chi": "",
                        "prima_di": "",
                        "nota": "",
                        "prima": percorso.name,
                        "ultima": percorso.name,
                    },
                )
                voce["volte"] += 1
                voce["ultima"] = percorso.name
                voce["bloccante"] = voce["bloccante"] or residuo["bloccante"]
                voce["firma"] = bool(
                    FIRMA.search(voce["id"] + " " + residuo["nota"] + " " + residuo["chi"])
                )
                voce["chiude"] = bool(CHIUSA_SALVO_FIRMA.search(residuo["nota"] + " " + residuo["chi"]))
                # L'ultima dichiarazione vince: chi deve un residuo puo' cambiare da un atto
                # all'altro, e quello che conta e' cosa dice l'atto piu' recente.
                for campo in ("chi", "prima_di", "nota"):
                    if residuo[campo]:
                        voce[campo] = residuo[campo]
        # `visti` serve anche a sapere cosa e' NUOVO nell'ultimo atto; `ricorrenti` invece tiene solo
        # gli identificatori che nominano un ostacolo, perche' solo quelli si possono confrontare.
        nomi = {voce["id"] for voce in visti.values() if stabile(voce["id"])}
        ricorrenti = [
            voce
            for voce in visti.values()
            if stabile(voce["id"]) and voce["volte"] >= max(2, int(soglia))
        ]
        ricorrenti.sort(key=lambda voce: (-voce["volte"], not voce["bloccante"], voce["id"]))
        # «Solo la firma»: tutti gli ostacoli che tornano riguardano la firma. Vuol dire che il
        # prodotto non e' in discussione: manca una condizione. E' il caso misurato di `UPL04ZR`
        # (11 respinte, `DISTINCT-SIGNATURE`), ed e' l'unico caso in cui la riga non deve dire
        # «rifai» ne' «non si sblocca».
        solo_firma = any(voce["chiude"] and voce["firma"] for voce in ricorrenti)
        ultimo = tentativi[-1]
        precedenti = set()
        for percorso in tentativi[:-1]:
            precedenti |= {residuo["id"] for residuo in _residui(_leggi(percorso))}
        nuovi = [
            residuo["id"]
            for residuo in _residui(_leggi(ultimo))
            if residuo["id"] not in precedenti
        ]
        fuori[str(fase)] = {
            "phase": str(fase),
            "tentativi": len(tentativi),
            "respinte": respinte,
            "verdetti": dict(verdetti),
            "ricorrenti": ricorrenti[:3],
            "nuovi_ultimo": nuovi,
            "nomi": len(nomi),
            "ultimo": str(ultimo.relative_to(ws.root)),
            "ultimo_verdetto": str(_leggi(ultimo).get("verdict") or ""),
            # «Si ripete» vuol dire: qualcuno ci e' tornato sopra almeno `soglia` volte E c'e' un
            # ostacolo che compare in tutte le ultime prove. Senza il secondo pezzo sarebbe solo
            # «tanti tentativi», che non e' un'informazione utile.
            "ripetuta": bool(
                len(tentativi) >= max(2, int(soglia))
                and any(voce["volte"] >= len(tentativi) - 1 for voce in ricorrenti)
            ),
            "solo_firma": solo_firma,
        }
    return fuori


def frase(voce) -> str:
    """La riga da leggere: quanti tentativi, quante respinte, e cosa si ripete."""
    if not voce:
        return ""
    parti = [f"{voce['tentativi']} tentativi", f"{voce['respinte']} respinte"]
    ricorrenti = voce.get("ricorrenti") or []
    if ricorrenti:
        primo = ricorrenti[0]
        parti.append(f"lo stesso ostacolo in {primo['volte']} su {voce['tentativi']}: {primo['id']}")
        if primo["bloccante"]:
            parti.append("bloccante")
        if primo["chi"]:
            parti.append(f"chi lo deve: {primo['chi']}")
    elif voce["respinte"]:
        nuovi = len(voce.get("nuovi_ultimo") or [])
        parti.append(
            f"nessun ostacolo con lo stesso nome negli atti precedenti"
            + (f": l'ultimo ne nomina {nuovi} nuovi" if nuovi else "")
        )
    return " · ".join(parti)


def main(argv=None):
    analizzatore = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizzatore.add_argument("--workspace", required=True)
    analizzatore.add_argument("--fase", action="append", help="una fase sola (ripetibile)")
    analizzatore.add_argument("--json", action="store_true")
    argomenti = analizzatore.parse_args(argv)
    ws = Workspace.load(argomenti.workspace)
    voci = per_fase(ws, argomenti.fase)
    if argomenti.json:
        print(json.dumps(voci, ensure_ascii=False, indent=1, default=str))
        return 0
    if not voci:
        print("nessuna fase con tentativi su disco")
        return 0
    for voce in sorted(voci.values(), key=lambda v: (-v["respinte"], v["phase"])):
        print(f"{voce['phase']:<14} {frase(voce)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
