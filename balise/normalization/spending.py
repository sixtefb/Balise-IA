"""Conversion des agrégats financiers OFGL (montants totaux) en €/habitant.

La comparaison entre communes de tailles différentes n'a de sens qu'une
fois ramenée à un dénominateur commun : l'euro par habitant.
"""

from __future__ import annotations

from balise.config import SETTINGS, Settings


def per_capita(montant: float | None, population: float | None) -> float | None:
    """Convertit un montant total en €/habitant. None si l'une des deux valeurs manque."""
    if montant is None or not population:
        return None
    return montant / population


def normalize_financial_data(
    financial_data: dict,
    settings: Settings = SETTINGS,
) -> dict[str, float | None]:
    """Retourne, pour chaque poste de dépense configuré, le montant en €/habitant.

    `financial_data` est le dict retourné par `balise.ingestion.ofgl.get_financial_data`
    (ou une entrée de `get_peer_group_financial_data`) : il doit contenir
    "population" et un sous-ensemble des clés de `settings.spending_items`.
    """
    population = financial_data.get("population")
    return {
        item.key: per_capita(financial_data.get(item.key), population)
        for item in settings.spending_items
    }
