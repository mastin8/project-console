"""Chi tiene davvero una fase: una sola precedenza per tutte le viste."""
from __future__ import annotations


def owner(claim) -> str:
    """Il titolare osservabile di una presa.

    `taken_by` e' il campo scritto quando un esecutore prende una fase. `owner` puo' invece essere
    il residuo dell'attivazione («NESSUN TITOLARE: …») e non deve mai prevalere.
    """
    claim = claim if isinstance(claim, dict) else {}
    return str(
        claim.get("taken_by")
        or claim.get("owner_agent")
        or claim.get("owner")
        or ""
    ).strip()
