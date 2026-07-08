"""Orchestration complète d'un audit : identité + score + marchés notables.

Point d'entrée unique utilisé par `audit.py` (CLI) et le serveur HTTP
(`server.py`), pour éviter que les deux ne divergent sur l'enchaînement des
appels aux modules d'ingestion/scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from balise.config import OFGL_STRATE_LABELS, SETTINGS, Settings
from balise.ingestion import decp
from balise.ingestion.decp import DecpError
from balise.ingestion.insee import (
    CommuneAmbiguousError,
    CommuneNotFoundError,
    InseeError,
    resolve_commune,
)
from balise.models import CommuneIdentity
from balise.scoring import CommuneScoreCard, ScoringError, score_commune

__all__ = [
    "AuditError",
    "AuditResult",
    "CommuneAmbiguousError",
    "CommuneNotFoundError",
    "InseeError",
    "ScoringError",
    "audit_to_dict",
    "run_audit",
    "strate_label",
]


class AuditError(Exception):
    """Erreur générique lors de la constitution d'un audit (enveloppe ScoringError/DecpError)."""


@dataclass(frozen=True)
class AuditResult:
    commune: CommuneIdentity
    score_card: CommuneScoreCard
    marches_notables: tuple[dict, ...]
    generated_at: str


def strate_label(score_card: CommuneScoreCard) -> str:
    """Libellé humain de la strate démographique OFGL utilisée pour le groupe de pairs."""
    return OFGL_STRATE_LABELS.get(score_card.strate_value, f"strate {score_card.strate_value}")


def run_audit(
    commune_nom: str,
    code_postal: str,
    exercice: int | None = None,
    settings: Settings = SETTINGS,
    use_cache: bool = True,
    markets_limit: int = 8,
) -> AuditResult:
    """Résout la commune, calcule son score budgétaire et récupère ses marchés notables.

    Lève CommuneNotFoundError/CommuneAmbiguousError/InseeError (résolution
    commune) ou AuditError (score OFGL indisponible pour cette commune).
    """
    commune = resolve_commune(commune_nom, code_postal, settings=settings, use_cache=use_cache)

    from balise.ingestion import ofgl  # import tardif : évite un cycle avec balise.scoring

    resolved_exercice = exercice if exercice is not None else ofgl.latest_exercice(
        commune.code_insee, settings=settings
    )

    try:
        score_card = score_commune(commune.code_insee, exercice=resolved_exercice, settings=settings)
    except ScoringError as exc:
        raise AuditError(str(exc)) from exc

    marches: list[dict] = []
    if commune.siren:
        try:
            marches = decp.get_markets_for_commune(commune.siren, settings=settings)
        except DecpError:
            marches = []
    marches_notables = tuple(sorted(marches, key=lambda m: m["montant"] or 0, reverse=True)[:markets_limit])

    return AuditResult(
        commune=commune,
        score_card=score_card,
        marches_notables=marches_notables,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def audit_to_dict(result: AuditResult) -> dict:
    """Sérialise un AuditResult pour l'API HTTP / le rendu du rapport."""
    commune = result.commune
    card = result.score_card
    return {
        "commune": {
            "nom": commune.nom,
            "code_insee": commune.code_insee,
            "siren": commune.siren,
            "codes_postaux": list(commune.codes_postaux),
            "population": commune.population,
            "departement": commune.departement,
            "code_departement": commune.code_departement,
            "region": commune.region,
            "code_region": commune.code_region,
            "epci": commune.epci,
        },
        "exercice": card.exercice,
        "strate_label": strate_label(card),
        "peer_group_size": card.peer_group_size,
        "score": {"global": card.global_score, "verdict": card.verdict},
        "categories": [
            {
                "key": it.key,
                "label": it.label,
                "commune_par_habitant": it.commune_par_habitant,
                "peer_median_par_habitant": it.peer_median_par_habitant,
                "delta_pct": it.delta_pct,
                "peer_count": it.peer_count,
                "qualification": it.qualification,
            }
            for it in card.items
        ],
        "marches_notables": [
            {
                "id": m.get("id"),
                "objet": m.get("objet"),
                "montant": m.get("montant"),
                "date_notification": m.get("date_notification"),
                "titulaire": m.get("titulaire_denomination"),
            }
            for m in result.marches_notables
        ],
        "generated_at": result.generated_at,
    }
