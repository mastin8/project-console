"""La Costituzione del progetto: bozza modificabile, approvazione umana, poi immutabile.

Il file resta Markdown leggibile. Il frontmatter contiene lo stato e l'impronta SHA-256 del solo
corpo: cambiare il testo dopo l'approvazione non e' una modifica "da riparare", e' un errore di
integrita' che il console deve mostrare e rifiutare.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

import onboarding_findings
from workspace import lock_file

SCHEMA = "project-console-constitution/1.0"
DRAFT = "draft"
APPROVED = "approved"

_FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


class ConstitutionError(Exception):
    """Errore che l'API espone con un codice stabile alla pagina."""

    code = "constitution_error"


class ConstitutionMissing(ConstitutionError):
    code = "constitution_missing"


class ConstitutionLocked(ConstitutionError):
    code = "constitution_locked"


class ConstitutionConflict(ConstitutionError):
    code = "constitution_conflict"


class ConstitutionIntegrityError(ConstitutionError):
    code = "constitution_integrity_failed"


class ConstitutionInvalid(ConstitutionError):
    code = "constitution_invalid"


class ConstitutionNotApproved(ConstitutionError):
    code = "constitution_not_approved"


def _normalize_body(body: str) -> str:
    """Una sola forma per lo stesso Markdown: niente differenze dovute a righe vuote finali."""
    return str(body or "").strip() + "\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(path: Path, project: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConstitutionMissing(
            f"{path} non esiste: usa «Crea la bozza» nella pagina Costituzione, "
            "oppure scaffold.py per un progetto nuovo"
        ) from error

    # I workspace creati prima del frontmatter restano leggibili. La prima scrittura aggiunge la
    # busta, senza inventare un'approvazione che non c'e' mai stata.
    metadata = {
        "schema": SCHEMA,
        "status": DRAFT,
        "project": project,
        "updated_at": "",
        "approved_at": "",
        "approved_sha256": "",
    }
    body = text
    if text.startswith("---"):
        trovato = _FRONTMATTER.match(text)
        if not trovato:
            raise ConstitutionIntegrityError(f"{path}: frontmatter aperto e non chiuso")
        try:
            caricato = yaml.safe_load(trovato.group(1)) or {}
        except yaml.YAMLError as error:
            raise ConstitutionIntegrityError(f"{path}: frontmatter illeggibile: {error}") from error
        if not isinstance(caricato, dict):
            raise ConstitutionIntegrityError(f"{path}: il frontmatter deve essere una mappa YAML")
        metadata.update({str(key): value for key, value in caricato.items()})
        body = text[trovato.end():]

    schema = str(metadata.get("schema") or SCHEMA)
    if schema != SCHEMA:
        raise ConstitutionIntegrityError(f"{path}: schema non riconosciuto: {schema}")
    status = str(metadata.get("status") or DRAFT)
    if status not in (DRAFT, APPROVED):
        raise ConstitutionIntegrityError(f"{path}: stato non riconosciuto: {status}")

    body = _normalize_body(body)
    body_sha256 = _sha256(body)
    approved_sha256 = str(metadata.get("approved_sha256") or "")
    if status == APPROVED and approved_sha256 != body_sha256:
        raise ConstitutionIntegrityError(
            f"{path}: il corpo approvato non corrisponde a approved_sha256"
        )

    metadata.update(
        {
            "schema": SCHEMA,
            "status": status,
            "project": str(metadata.get("project") or project),
            "updated_at": str(metadata.get("updated_at") or ""),
            "approved_at": str(metadata.get("approved_at") or ""),
            "approved_sha256": approved_sha256,
        }
    )
    return {"metadata": metadata, "body": body, "body_sha256": body_sha256}


@contextmanager
def _locked(workspace):
    with open(lock_file(workspace.root), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _serialize(metadata: dict, body: str) -> str:
    frontmatter = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{_normalize_body(body)}"


def _write(path: Path, metadata: dict, body: str, *, read_only: bool = False) -> None:
    """Sostituzione atomica: chi legge vede il file vecchio oppure quello nuovo, mai un mezzo file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    precedente = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporaneo = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".constitution-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_serialize(metadata, body))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporaneo, 0o444 if read_only else precedente)
        os.replace(temporaneo, path)
    finally:
        if os.path.exists(temporaneo):
            os.unlink(temporaneo)


def _payload(document: dict) -> dict:
    metadata = document["metadata"]
    sha256 = document["body_sha256"]
    approved = metadata["status"] == APPROVED
    return {
        "schema": metadata["schema"],
        "status": metadata["status"],
        "project": metadata["project"],
        "body": document["body"],
        "updated_at": metadata["updated_at"],
        "approved_at": metadata["approved_at"],
        "approved_sha256": metadata["approved_sha256"] if approved else "",
        "draft_sha256": sha256,
        "editable": not approved,
    }


def _findings_state(workspace):
    try:
        return {"blocking_findings": onboarding_findings.open_blocking(workspace.root)}
    except ValueError as error:
        return {"blocking_findings": [], "findings_error": str(error)}


def load(workspace) -> dict:
    """Legge la Costituzione e verifica il sigillo se e' gia' approvata."""
    payload = _payload(_parse(workspace.constitution_path, workspace.project))
    payload.update(_findings_state(workspace))
    return payload


def gate(workspace) -> dict:
    """Lo stato del cancello, senza far fallire la lettura generale della pagina."""
    try:
        documento = load(workspace)
    except ConstitutionError as error:
        return {
            "approved": False,
            "status": "missing" if isinstance(error, ConstitutionMissing) else "invalid",
            "code": error.code,
            "message": str(error),
        }
    blockers = _findings_state(workspace)
    aperte = len(blockers["blocking_findings"])
    message = "la Costituzione è ancora una bozza: approvazione richiesta"
    if aperte:
        message = (
            f"la Costituzione è ancora una bozza e {aperte} decisioni di partenza "
            "bloccano l'approvazione"
        )
    if blockers.get("findings_error"):
        message = "l'audit iniziale è illeggibile: l'approvazione resta bloccata"
    return {
        "approved": documento["status"] == APPROVED,
        "status": documento["status"],
        "code": "" if documento["status"] == APPROVED else ConstitutionNotApproved.code,
        "message": "" if documento["status"] == APPROVED else message,
        "sha256": documento["draft_sha256"],
        **blockers,
    }


def require_approved(workspace) -> dict:
    """Fallisce chiuso quando un task, una fase o un prompt proverebbero a partire."""
    documento = load(workspace)
    if documento["status"] != APPROVED:
        raise ConstitutionNotApproved(
            "la Costituzione non è approvata: nessun task o prompt può partire"
        )
    return documento


def create_draft(workspace) -> dict:
    """Crea la sola BOZZA per un workspace avviato prima della Costituzione."""
    percorso = workspace.constitution_path
    if percorso.exists():
        return load(workspace)
    modello = Path(__file__).resolve().parent.parent / "templates" / "workspace" / "constitution.md"
    if not modello.is_file():
        raise ConstitutionMissing(f"modello della Costituzione non trovato: {modello}")
    testo = modello.read_text(encoding="utf-8").replace("__PROJECT__", workspace.project)
    trovato = _FRONTMATTER.match(testo)
    corpo = testo[trovato.end():] if trovato else testo
    metadata = {
        "schema": SCHEMA,
        "status": DRAFT,
        "project": workspace.project,
        "updated_at": "",
        "approved_at": "",
        "approved_sha256": "",
    }
    with _locked(workspace):
        if percorso.exists():
            return _payload(_parse(percorso, workspace.project))
        _write(percorso, metadata, corpo)
    return load(workspace)


def _sezioni(body: str) -> list:
    """Le sezioni Markdown `##`, con il titolo e il testo."""
    trovati = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
    fuori = []
    for indice, trovato in enumerate(trovati):
        fine = trovati[indice + 1].start() if indice + 1 < len(trovati) else len(body)
        fuori.append((trovato.group(1).strip(), body[trovato.start():fine].strip()))
    return fuori


def prompt_context(workspace, limit=9000) -> str:
    """I vincoli stabili da mettere in OGNI prompt, automaticamente.

    Non si copia tutta la Costituzione: si prendono le sezioni che governano il lavoro e si cita
    l'impronta approvata. Obiettivo e fuori perimetro restano inclusi perché cambiano cosa significa
    «fatto»; le domande dell'onboarding no.
    """
    documento = require_approved(workspace)
    chiavi = (
        "obiettivo",
        "fuori perimetro",
        "stack tecnico",
        "deliverable finale",
        "ampiezza",
        "flusso di lavoro",
        "parallelismo",
        "test e accettazione",
        "rischi",
        "stop rule",
    )
    selezionate = []
    for titolo, testo in _sezioni(documento["body"]):
        basso = titolo.lower()
        if any(chiave in basso for chiave in chiavi):
            selezionate.append(testo)
    if not selezionate:
        selezionate = [documento["body"]]
    contenuto = "\n\n".join(selezionate)
    if len(contenuto) > limit:
        contenuto = contenuto[:limit].rstrip() + "\n… [testo troncato dal limite del prompt]"
    return (
        "════ VINCOLI DELLA COSTITUZIONE APPROVATA ════\n"
        f"Sigillo SHA-256: {documento['draft_sha256']}\n"
        "Questi vincoli vengono prima delle preferenze dell'esecutore. Se il lavoro richiesto li "
        "contraddice, fermati e dichiara il conflitto.\n\n"
        f"{contenuto}\n"
        "══════════════════════════════════════════\n"
    )


def save_draft(workspace, body: str, expected_sha256: str | None = None) -> dict:
    """Salva una bozza; una Costituzione approvata non entra mai da questa porta."""
    with _locked(workspace):
        document = _parse(workspace.constitution_path, workspace.project)
        metadata = dict(document["metadata"])
        if metadata["status"] == APPROVED:
            raise ConstitutionLocked("la Costituzione e' approvata e non puo' piu' essere modificata")
        if expected_sha256 and expected_sha256 != document["body_sha256"]:
            raise ConstitutionConflict(
                "la bozza e' cambiata mentre la modificavi: ricaricala prima di salvare"
            )
        nuovo_corpo = _normalize_body(body)
        metadata["status"] = DRAFT
        metadata["updated_at"] = _now()
        metadata["approved_at"] = ""
        metadata["approved_sha256"] = ""
        _write(workspace.constitution_path, metadata, nuovo_corpo)
        return _payload(_parse(workspace.constitution_path, workspace.project))


def approve(
    workspace,
    expected_sha256: str | None = None,
    body: str | None = None,
) -> dict:
    """Approva e blocca in un solo atto sotto lock.

    `body` permette di approvare esattamente il testo ancora presente nell'editor senza un salvataggio
    separato e senza la finestra in cui un'altra scrittura potrebbe cambiarlo.
    """
    with _locked(workspace):
        document = _parse(workspace.constitution_path, workspace.project)
        metadata = dict(document["metadata"])
        if metadata["status"] == APPROVED:
            raise ConstitutionLocked("la Costituzione e' gia' approvata")
        if expected_sha256 and expected_sha256 != document["body_sha256"]:
            raise ConstitutionConflict(
                "la bozza e' cambiata mentre la modificavi: ricaricala prima di approvarla"
            )
        nuovo_corpo = _normalize_body(document["body"] if body is None else body)
        if not nuovo_corpo.strip():
            raise ConstitutionInvalid("la Costituzione non puo' essere approvata vuota")
        try:
            aperti = onboarding_findings.open_blocking(workspace.root)
        except ValueError as error:
            raise ConstitutionInvalid(str(error)) from error
        if aperti:
            identificatori = [
                str(gap.get("id") or "SENZA-ID")
                for gap in aperti
            ]
            anteprima = ", ".join(identificatori[:8])
            altre = (
                f" e altre {len(identificatori) - 8} voci"
                if len(identificatori) > 8
                else ""
            )
            raise ConstitutionInvalid(
                "la Costituzione contiene decisioni bloccanti ancora aperte: "
                f"{anteprima}{altre}. Chiudile con onboarding_findings.py --resolve e una nota."
            )
        adesso = _now()
        metadata["status"] = APPROVED
        metadata["updated_at"] = adesso
        metadata["approved_at"] = adesso
        metadata["approved_sha256"] = _sha256(nuovo_corpo)
        _write(
            workspace.constitution_path,
            metadata,
            nuovo_corpo,
            read_only=True,
        )
        return _payload(_parse(workspace.constitution_path, workspace.project))
