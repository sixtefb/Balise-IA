"""Structures de données partagées.

Séparation volontaire en deux couches, pensée pour accueillir plus tard des
données transmises par le client sans refonte :

- couche "public benchmark" (ce module + balise.ingestion.*) : uniquement
  des données ouvertes (INSEE, OFGL, DECP), utilisées pour construire le
  groupe de comparaison et les moyennes/médianes de référence.
- couche "données client" (balise.client_data) : réservée à la comptabilité
  détaillée ou tout autre document transmis par la commune auditée. Rien
  dans cette couche n'alimente le groupe de comparaison : elle ne fait que
  se comparer AU benchmark public, jamais l'inverse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommuneIdentity:
    """Identité et métadonnées publiques d'une commune (couche "public benchmark")."""

    code_insee: str
    nom: str
    codes_postaux: tuple[str, ...]
    siren: str | None
    population: int | None
    surface_km2: float | None
    code_departement: str
    departement: str
    code_region: str
    region: str
    code_epci: str | None
    epci: str | None
    strate_demographique: str | None
    source: str = "geo.api.gouv.fr"
    fetched_at: str | None = None
