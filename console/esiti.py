"""Gli esiti di un atto, ridotti ai punti che si leggono prima di firmare.

Il formato dei report e' del progetto: la console non impone uno schema. Qui si leggono solo le
liste che hanno una forma riconoscibile — criteri di accettazione, casi, finding, limiti — e si
butta via il resto. Se un progetto usa altre chiavi, la pagina dice che il report non ha punti
leggibili e resta il report intero: meglio un vuoto dichiarato che un riassunto inventato.
"""
from __future__ import annotations

SEZIONI = (
    (
        "Criteri di accettazione",
        ("acceptance_checks_from_tasks", "acceptance_checks", "acceptance_criteria", "criteria_map"),
    ),
    ("Casi", ("cases",)),
    ("Finding", ("findings", "finding")),
    (
        "Limiti dichiarati",
        ("limits", "limits_and_risks", "declared_residuals", "residui", "limitations", "risks"),
    ),
)

#: Il primo campo che somiglia a una frase leggibile. `criterion` prima di `method`: «C2 negativo»
#: dice cosa si sta provando, `test_T3_...` dice solo come si chiama la funzione.
CHIAVI_TESTO = (
    "text",
    "what",
    "title",
    "criterion",
    "why",
    "note",
    "method",
    "summary",
    "description",
    "statement",
)
CHIAVI_ESITO = ("outcome", "esito", "severity", "status")
MAX_TESTO = 240


def _testo(voce):
    for chiave in CHIAVI_TESTO:
        valore = voce.get(chiave)
        if isinstance(valore, str) and valore.strip():
            testo = " ".join(valore.split())
            if len(testo) <= MAX_TESTO:
                return testo
            return testo[:MAX_TESTO].rsplit(" ", 1)[0] + "…"
    return ""


def _esito(voce):
    for chiave in CHIAVI_ESITO:
        valore = voce.get(chiave)
        if isinstance(valore, str) and valore.strip():
            return valore.strip()
    return ""


def _voci(valore):
    """Una lista di punti, anche quando il progetto scrive un dizionario `C1: {...}`."""
    if isinstance(valore, dict) and (valore.get("id") or valore.get("what") or valore.get("text")):
        # Un finding scritto al singolare (`finding:` con id e what) e' UN punto, non una mappa.
        yield valore
        return
    if isinstance(valore, list):
        for voce in valore:
            if isinstance(voce, dict):
                yield voce
            elif isinstance(voce, str) and voce.strip():
                yield {"text": voce}
    elif isinstance(valore, dict):
        for chiave, voce in valore.items():
            if isinstance(voce, dict):
                yield dict(voce, id=voce.get("id") or chiave)
            elif isinstance(voce, str) and voce.strip():
                yield {"id": chiave, "text": voce}


def _sezione(documento, chiavi):
    for chiave in chiavi:
        if chiave not in documento:
            continue
        punti = []
        for voce in _voci(documento.get(chiave)):
            punto = {
                "id": str(voce.get("id") or ""),
                "testo": _testo(voce),
                "esito": _esito(voce),
            }
            if punto["id"] or punto["testo"] or punto["esito"]:
                punti.append(punto)
        if punti:
            return punti
    return []


def estrai(documento, percorso=""):
    """I punti di un report, divisi per sezione. Nessuna interpretazione: solo cio' che c'e' scritto."""
    documento = documento if isinstance(documento, dict) else {}
    sezioni = []
    for titolo, chiavi in SEZIONI:
        punti = _sezione(documento, chiavi)
        if punti:
            sezioni.append({"titolo": titolo, "punti": punti})
    if not sezioni:
        sintesi = _testo({"text": documento.get("summary") or documento.get("completion_statement")})
        if sintesi:
            sezioni.append({"titolo": "Sintesi", "punti": [{"id": "", "testo": sintesi, "esito": ""}]})
    return {
        "phase": str(documento.get("task_id") or ""),
        "attempt": documento.get("attempt"),
        "verdict": str(documento.get("verdict") or documento.get("recommendation") or ""),
        "report": percorso,
        "sezioni": sezioni,
    }
