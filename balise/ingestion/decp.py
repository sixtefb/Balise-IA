"""Ingestion des Données Essentielles de la Commande Publique (DECP, data.gouv.fr).

Non implémenté à ce stade (étape 3 de Balise IA, à valider avant démarrage).
Prévu :
- téléchargement du fichier consolidé DECP (marchés publics >= 40 000 € HT)
- indexation dans le cache DuckDB local, filtrée sur une liste de codes CPV
  pertinents pour l'audit de dépenses communales (liste à établir : espaces
  verts, nettoyage, collecte des déchets, etc.)
- get_markets_for_commune(siret_acheteur) -> marchés passés par la commune
- get_comparable_markets(code_cpv, perimetre) -> marchés comparables passés
  par d'autres communes pour un même type de prestation
"""

from __future__ import annotations


def get_markets_for_commune(siret_acheteur: str) -> list[dict]:
    raise NotImplementedError("Module DECP non implémenté - étape 3 de Balise IA.")


def get_comparable_markets(code_cpv: str) -> list[dict]:
    raise NotImplementedError("Module DECP non implémenté - étape 3 de Balise IA.")
