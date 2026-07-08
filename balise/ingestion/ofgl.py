"""Ingestion des agrégats financiers OFGL (data.ofgl.fr, API OpenDataSoft).

Non implémenté à ce stade (étape 2 de Balise IA, à valider avant démarrage).
Prévu :
- téléchargement des jeux "ofgl-base-communes" et "ofgl-base-communes-consolidee"
- indexation dans des tables dédiées du cache DuckDB local (balise.storage.db)
- get_financial_data(code_insee, annee) -> agrégats de la commune
  (fonctionnement, investissement, dette, principaux postes de dépense)
- get_peer_group_financial_data(strate, code_departement, annee) -> agrégats
  des communes comparables, pour alimenter balise.scoring
"""

from __future__ import annotations


def get_financial_data(code_insee: str, annee: int) -> dict:
    raise NotImplementedError("Module OFGL non implémenté - étape 2 de Balise IA.")


def get_peer_group_financial_data(strate: str, code_departement: str, annee: int) -> list[dict]:
    raise NotImplementedError("Module OFGL non implémenté - étape 2 de Balise IA.")
