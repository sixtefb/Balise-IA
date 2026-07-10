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
    "DECP_LOW_COVERAGE_THRESHOLD",
    "InseeError",
    "MAX_HISTORY_YEARS",
    "ScoringError",
    "audit_to_dict",
    "decp_coverage_note",
    "peer_group_note",
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
    marches_total_count: int
    demographie: dict | None
    generated_at: str
    data_freshness: dict[str, str | None]


def strate_label(score_card: CommuneScoreCard) -> str:
    """Libellé humain de la strate démographique OFGL utilisée pour le groupe de pairs."""
    return OFGL_STRATE_LABELS.get(score_card.strate_value, f"strate {score_card.strate_value}")


def peer_group_note(score_card: CommuneScoreCard) -> str | None:
    """Explication à afficher quand le groupe de comparaison a été affiné ou reste hétérogène.

    Voir balise.scoring._narrow_peer_group_by_population : la strate OFGL la
    plus haute ("100 000 habitants et plus") est ouverte et peut mélanger
    des villes de tailles très différentes.
    """
    if score_card.peer_group_refined:
        return (
            "Comparaison resserrée aux communes de la strate dont la population est du même "
            "ordre de grandeur (la strate complète est trop large pour rester pertinente pour "
            "les grandes villes)."
        )
    if score_card.peer_group_heterogeneous:
        return (
            "Cette commune est nettement plus grande ou plus petite que la médiane de sa strate "
            "démographique, et il n'y a pas assez d'autres communes d'ordre de grandeur comparable "
            "pour resserrer la comparaison : les écarts mesurés sont à interpréter avec prudence."
        )
    return None


# DECP est un système déclaratif : rien n'oblige une commune à publier tous
# ses marchés, et la rigueur de publication varie énormément d'une commune à
# l'autre. Sous ce seuil (nombre de marchés distincts retrouvés, tous
# exercices confondus), une valeur basse au poste "Entretien" (ou peu de
# marchés notables) est probablement le signe d'une faible couverture
# déclarative plutôt que d'une réelle absence de dépense - seuil empirique,
# pas une mesure statistique rigoureuse.
DECP_LOW_COVERAGE_THRESHOLD = 3


def decp_coverage_note(marches_total_count: int) -> str | None:
    """Avertissement de complétude déclarative DECP, si peu de marchés ont été retrouvés.

    Ne modifie ni ne filtre aucune donnée : signale seulement que l'absence
    de marchés notables peut refléter une faible publication par la commune
    plutôt qu'une absence réelle de dépense (DECP est déclaratif, pas
    exhaustif par construction).
    """
    if marches_total_count >= DECP_LOW_COVERAGE_THRESHOLD:
        return None
    if marches_total_count == 0:
        return (
            "Aucun marché public trouvé dans les données DECP pour cette commune. DECP est "
            "un système déclaratif : cette absence peut refléter une faible publication par la "
            "commune plutôt qu'une absence réelle de marchés (notamment pour le poste "
            "\"Entretien\", reconstruit à partir de ces mêmes données)."
        )
    return (
        f"Seulement {marches_total_count} marché(s) public(s) trouvé(s) dans les données DECP pour "
        "cette commune. DECP est un système déclaratif : ce nombre peut refléter une couverture "
        "déclarative incomplète plutôt qu'une réelle sobriété (notamment pour le poste "
        "\"Entretien\", reconstruit à partir de ces mêmes données)."
    )


# Un marché dont le montant dépasse le budget de fonctionnement annuel
# entier de la commune (agrégat OFGL "charges_de_fonctionnement", en valeur
# absolue, pas €/habitant) est presque certainement une anomalie de saisie
# (unité, décimale...) plutôt qu'un marché réel - constaté en direct sur un
# cas concret (~99,999 milliards d'euros pour de la maintenance
# d'équipements hospitaliers). Ne PAS filtrer/plafonner cette valeur (le
# montant affiché reste celui de la source) : seulement la signaler, pour
# que l'utilisateur sache qu'elle mérite une vérification avant d'être prise
# au pied de la lettre.
MARKET_OUTLIER_BUDGET_RATIO = 1.0


def _flag_outlier_markets(grouped_markets: list[dict], budget_reference: float | None) -> list[dict]:
    """Ajoute `montant_exceptionnel: bool` à chaque marché groupé, sans modifier `montant`."""
    if not budget_reference or budget_reference <= 0:
        return [{**m, "montant_exceptionnel": False} for m in grouped_markets]
    threshold = budget_reference * MARKET_OUTLIER_BUDGET_RATIO
    return [{**m, "montant_exceptionnel": (m.get("montant") or 0) > threshold} for m in grouped_markets]


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
    commune_financials = ofgl.get_financial_data(commune.code_insee, exercice=resolved_exercice, settings=settings)
    budget_reference = (commune_financials or {}).get("charges_de_fonctionnement")
    marches_grouped = _flag_outlier_markets(_group_markets(marches), budget_reference)
    marches_notables = tuple(marches_grouped[:markets_limit])
    demographie = insee_demographie.get_age_breakdown(commune.code_insee, settings=settings)

    ofgl_freshness = ofgl.get_data_freshness(commune.code_insee, settings=settings)
    decp_freshness = decp.get_markets_freshness(commune.siren, settings=settings) if commune.siren else None
    entretien_freshness = decp.get_maintenance_freshness(settings=settings)
    data_freshness = {
        "ofgl": ofgl_freshness.isoformat() if ofgl_freshness else None,
        "decp_marches": decp_freshness.isoformat() if decp_freshness else None,
        "decp_entretien": entretien_freshness.isoformat() if entretien_freshness else None,
    }

    return AuditResult(
        commune=commune,
        score_card=score_card,
        marches_notables=marches_notables,
        marches_total_count=len(marches_grouped),
        demographie=demographie,
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_freshness=data_freshness,
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
        "peer_group_note": peer_group_note(card),
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
                "montant_exceptionnel": m.get("montant_exceptionnel", False),
            }
            for m in result.marches_notables
        ],
        "marches_total_count": result.marches_total_count,
        "decp_coverage_note": decp_coverage_note(result.marches_total_count),
        "demographie": result.demographie,
        "generated_at": result.generated_at,
        "data_freshness": result.data_freshness,
    }
