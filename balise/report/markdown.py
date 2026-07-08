"""Génération de rapports Markdown.

À ce stade (étape 1), seule la fiche d'identité de la commune est
disponible : le rapport d'audit complet (résumé exécutif, écarts par poste
de dépense, marchés publics anormaux) nécessite les modules OFGL et DECP,
non encore implémentés.
"""

from __future__ import annotations

from datetime import date

from balise.models import CommuneIdentity


def render_commune_identity_card(commune: CommuneIdentity, generated_on: date | None = None) -> str:
    """Fiche d'identité minimale d'une commune (étape 1 : résolution INSEE seule)."""
    generated_on = generated_on or date.today()
    codes_postaux = ", ".join(commune.codes_postaux) if commune.codes_postaux else "n/a"
    population = f"{commune.population:,}".replace(",", " ") if commune.population is not None else "n/a"
    surface = f"{commune.surface_km2:.2f} km²" if commune.surface_km2 is not None else "n/a"

    lines = [
        f"# Balise IA - Fiche d'identité : {commune.nom}",
        "",
        f"*Généré le {generated_on.isoformat()} — étape 1/3 (résolution INSEE uniquement)*",
        "",
        "> ⚠️ Ce document ne constitue pas encore un rapport d'audit. Les modules",
        "> OFGL (agrégats financiers) et DECP (marchés publics) doivent être",
        "> intégrés avant de pouvoir produire des comparaisons et des scores.",
        "",
        "## Identité",
        "",
        f"- **Code INSEE** : {commune.code_insee}",
        f"- **SIREN** : {commune.siren or 'n/a'}",
        f"- **Codes postaux** : {codes_postaux}",
        f"- **Population** : {population} habitants",
        f"- **Superficie** : {surface}",
        f"- **Strate démographique** : {commune.strate_demographique or 'n/a'}",
        f"- **Département** : {commune.departement} ({commune.code_departement})",
        f"- **Région** : {commune.region} ({commune.code_region})",
        f"- **EPCI** : {commune.epci or 'n/a'} ({commune.code_epci or 'n/a'})",
        "",
        f"*Source : {commune.source}, interrogée le {commune.fetched_at or 'n/a'}.*",
        "",
    ]
    return "\n".join(lines)


def render_audit_report(*args, **kwargs) -> str:
    """Rapport d'audit complet — nécessite les modules OFGL et DECP (étapes 2 et 3)."""
    raise NotImplementedError(
        "Le rapport d'audit complet nécessite balise.ingestion.ofgl et "
        "balise.ingestion.decp, non encore implémentés."
    )
