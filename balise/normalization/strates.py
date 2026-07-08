"""Classement d'une commune dans une strate démographique (seuils configurables)."""

from __future__ import annotations

from balise.config import SETTINGS, StrateThreshold


def strate_for_population(
    population: int,
    strates: tuple[StrateThreshold, ...] = SETTINGS.strates,
) -> str | None:
    """Retourne le libellé de la strate démographique correspondant à `population`.

    Retourne None si `population` ne rentre dans aucune tranche configurée
    (ne devrait pas arriver avec les bornes par défaut, qui couvrent
    0 -> +l'infini, mais peut survenir avec une configuration personnalisée).
    """
    for strate in strates:
        if population < strate.population_min:
            continue
        if strate.population_max is None or population <= strate.population_max:
            return strate.label
    return None
