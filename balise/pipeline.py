"""Orchestration complète d'un audit : identité + score + marchés notables.

Point d'entrée unique utilisé par `audit.py` (CLI) et le serveur HTTP
(`server.py`), pour éviter que les deux ne divergent sur l'enchaînement des
appels aux modules d'ingestion/scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from balise.config import OFGL_STRATE_LABELS, SETTINGS, Settings
from balise.ingestion import decp, insee_demographie
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
    "MAX_HISTORY_YEARS",
    "ScoringError",
    "audit_to_dict",
    "run_audit",
    "run_history",
    "strate_label",
]

# Chaque année d'historique = une requête nationale OFGL par exercice
# (~10-15s non cachée). Chargé à la demande côté interface (bouton "Voir
# l'évolution"), pas automatiquement à chaque audit.
MAX_HISTORY_YEARS = 10


class AuditError(Exception):
    """Erreur générique lors de la constitution d'un audit (enveloppe ScoringError/DecpError)."""


@dataclass(frozen=True)
class AuditResult:
    commune: CommuneIdentity
    score_card: CommuneScoreCard
    marches_notables: tuple[dict, ...]
    demographie: dict | None
    generated_at: str


def strate_label(score_card: CommuneScoreCard) -> str:
    """Libellé humain de la strate démographique OFGL utilisée pour le groupe de pairs."""
    return OFGL_STRATE_LABELS.get(score_card.strate_value, f"strate {score_card.strate_value}")


# Beaucoup de marchés DECP sont allotis : un même marché à bons de commande
# ou accord-cadre ("2023/004", "2020-053"...) est décliné en plusieurs lots
# (un par corps de métier), chacun publié comme un enregistrement séparé.
# Ce n'est pas un doublon de données, mais ça se présente comme tel à
# l'affichage si on liste chaque lot individuellement — on les regroupe donc
# sous une seule entrée par référence de marché détectée dans l'objet.
_MARKET_REFERENCE_RE = re.compile(r"\b(\d{4}[/-]\d{2,4})\b")
_PLACEHOLDER_ID = "0000000000000000"


def _market_group_key(market: dict, index: int) -> str:
    match = _MARKET_REFERENCE_RE.search(market.get("objet") or "")
    if match:
        return match.group(1)
    market_id = market.get("id")
    if market_id and market_id != _PLACEHOLDER_ID:
        return market_id
    # Ni référence détectable dans l'objet, ni id fiable (beaucoup de
    # marchés DECP partagent le même id "0000000000000000") : on garde ce
    # marché seul plutôt que de risquer de le mélanger à un autre sans lien.
    return f"__singleton_{index}"


def _group_markets(markets: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for i, market in enumerate(markets):
        groups.setdefault(_market_group_key(market, i), []).append(market)

    grouped = []
    for reference, lots in groups.items():
        lots_by_montant = sorted(lots, key=lambda lot: lot.get("montant") or 0, reverse=True)
        titulaires = sorted({lot["titulaire_denomination"] for lot in lots if lot.get("titulaire_denomination")})
        dates = [lot["date_notification"] for lot in lots if lot.get("date_notification")]
        grouped.append(
            {
                "reference": None if reference.startswith("__singleton_") else reference,
                "objet": lots_by_montant[0].get("objet"),
                "montant": sum(lot.get("montant") or 0 for lot in lots),
                "lot_count": len(lots),
                "titulaires": titulaires,
                "date_notification": min(dates) if dates else None,
            }
        )
    return sorted(grouped, key=lambda g: g["montant"] or 0, reverse=True)


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
    marches_notables = tuple(_group_markets(marches)[:markets_limit])
    demographie = insee_demographie.get_age_breakdown(commune.code_insee, settings=settings)

    return AuditResult(
        commune=commune,
        score_card=score_card,
        marches_notables=marches_notables,
        demographie=demographie,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def run_history(
    commune_nom: str,
    code_postal: str,
    years: int = 5,
    settings: Settings = SETTINGS,
    use_cache: bool = True,
) -> dict:
    """Évolution du score sur plusieurs exercices, du plus récent en remontant.

    Coûteux (une requête nationale OFGL par exercice manquant du cache) :
    à déclencher explicitement (bouton dans l'interface), pas à chaque audit.
    Les exercices sans donnée OFGL exploitable sont silencieusement omis.
    """
    years = max(1, min(years, MAX_HISTORY_YEARS))
    commune = resolve_commune(commune_nom, code_postal, settings=settings, use_cache=use_cache)

    from balise.ingestion import ofgl  # import tardif : évite un cycle avec balise.scoring

    latest = ofgl.latest_exercice(commune.code_insee, settings=settings)
    if latest is None:
        raise AuditError(f"Aucun exercice OFGL disponible pour la commune {commune.code_insee}.")

    points = []
    for exercice in range(latest, latest - years, -1):
        try:
            card = score_commune(commune.code_insee, exercice=exercice, settings=settings)
        except ScoringError:
            continue
        points.append(
            {
                "exercice": exercice,
                "global_score": card.global_score,
                "verdict": card.verdict,
                "peer_group_size": card.peer_group_size,
                "categories": [
                    {
                        "key": it.key,
                        "label": it.label,
                        "commune_par_habitant": it.commune_par_habitant,
                        "peer_median_par_habitant": it.peer_median_par_habitant,
                        "delta_pct": it.delta_pct,
                    }
                    for it in card.items
                ],
            }
        )
    points.sort(key=lambda p: p["exercice"])

    return {
        "commune": {"nom": commune.nom, "code_insee": commune.code_insee},
        "years": points,
    }


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
                "peer_values": list(it.peer_values),
                "qualification": it.qualification,
            }
            for it in card.items
        ],
        "peer_communes": [
            {"code_insee": p.code_insee, "nom": p.nom, "population": p.population} for p in card.peers
        ],
        "marches_notables": [
            {
                "reference": m.get("reference"),
                "objet": m.get("objet"),
                "montant": m.get("montant"),
                "lot_count": m.get("lot_count"),
                "date_notification": m.get("date_notification"),
                "titulaires": m.get("titulaires") or [],
            }
            for m in result.marches_notables
        ],
        "demographie": result.demographie,
        "generated_at": result.generated_at,
    }
