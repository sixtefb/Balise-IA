"""Ingestion des marchés publics DECP (data.economie.gouv.fr, API OpenDataSoft v2.1).

Endpoints "records" (JSON, sans clé), interrogés directement :

    GET {base_url}/api/explore/v2.1/catalog/datasets/decp_augmente/records
        ?where=acheteur_id like "{siren}"

Remarque : le jeu `decp_augmente` est signalé "obsolète" sur certaines pages
data.gouv.fr recensant les sources DECP (une alternative plus récente, le
fichier consolidé "format tabulaire", existe sur data.gouv.fr). Utilisé ici
sur demande explicite.

Seul le champ "acheteur_id" est confirmé (clause `where` validée). Le reste
du schéma n'a pas pu être vérifié en direct depuis l'environnement où ce
module a été écrit (data.economie.gouv.fr n'y est pas joignable) : sa
résolution passe par une correspondance tolérante
(balise.config.DECP_COLUMN_ALIASES) qui échoue explicitement, avec la liste
des champs réellement présents, plutôt que de produire silencieusement un
résultat erroné. Utiliser describe_schema() après le premier appel réel pour
valider/corriger ces alias.
"""

from __future__ import annotations

import unicodedata

from balise.config import DECP_COLUMN_ALIASES, SETTINGS, Settings
from balise.ingestion._opendatasoft import OpenDataSoftError, fetch_records
from balise.storage.db import get_connection, read_query_cache, write_query_cache


class DecpError(Exception):
    """Erreur générique du module d'ingestion DECP."""


class DecpSchemaError(DecpError):
    """Un champ attendu n'a pas pu être identifié dans les enregistrements DECP reçus."""

    def __init__(self, canonical_field: str, available_fields: list[str]):
        super().__init__(
            f"Impossible d'identifier le champ correspondant à '{canonical_field}' dans "
            f"la réponse DECP. Champs disponibles : {available_fields}. "
            "Complétez balise.config.DECP_COLUMN_ALIASES avec le nom exact constaté."
        )
        self.canonical_field = canonical_field
        self.available_fields = available_fields


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.strip().lower()


def _resolve_field(available_fields: list[str], canonical: str) -> str:
    normalized_map = {_normalize(f): f for f in available_fields}
    candidates = [_normalize(c) for c in DECP_COLUMN_ALIASES.get(canonical, ())]

    for candidate in candidates:
        if candidate in normalized_map:
            return normalized_map[candidate]

    for norm_field, orig_field in normalized_map.items():
        if any(candidate in norm_field for candidate in candidates):
            return orig_field

    raise DecpSchemaError(canonical, available_fields)


def _try_resolve_field(available_fields: list[str], canonical: str) -> str | None:
    try:
        return _resolve_field(available_fields, canonical)
    except DecpSchemaError:
        return None


def _parse_number(raw_value) -> float | None:
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    cleaned = str(raw_value).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fetch_cached(where: str, settings: Settings) -> list[dict]:
    con = get_connection(settings)
    dataset_id = settings.decp.dataset_marches
    cache_key = f"decp:{dataset_id}:{where}"

    cached = read_query_cache(con, cache_key, settings.cache_ttl_days)
    if cached is not None:
        return cached

    try:
        records = fetch_records(
            settings.decp.base_url,
            dataset_id,
            where=where,
            max_records=settings.decp.max_records_per_query,
            timeout=settings.decp.request_timeout_seconds,
            max_retries=settings.decp.max_retries,
            retry_backoff_seconds=settings.decp.retry_backoff_seconds,
        )
    except OpenDataSoftError as exc:
        raise DecpError(str(exc)) from exc

    write_query_cache(con, cache_key, records)
    return records


def _normalize_records(records: list[dict], montant_minimum: float) -> list[dict]:
    if not records:
        return []

    sample_fields = list(records[0].keys())
    field_map = {
        "id": _try_resolve_field(sample_fields, "id"),
        "acheteur_id": _try_resolve_field(sample_fields, "acheteur_id"),
        "acheteur_nom": _try_resolve_field(sample_fields, "acheteur_nom"),
        "objet": _try_resolve_field(sample_fields, "objet"),
        "code_cpv": _try_resolve_field(sample_fields, "code_cpv"),
        "montant": _resolve_field(sample_fields, "montant"),
        "date_notification": _try_resolve_field(sample_fields, "date_notification"),
        "titulaire_id": _try_resolve_field(sample_fields, "titulaire_id"),
        "titulaire_denomination": _try_resolve_field(sample_fields, "titulaire_denomination"),
    }

    normalized = []
    for record in records:
        montant = _parse_number(record.get(field_map["montant"]))
        if montant is None or montant < montant_minimum:
            continue
        entry = {
            canonical: (record.get(field) if field else None)
            for canonical, field in field_map.items()
            if canonical != "montant"
        }
        entry["montant"] = montant
        normalized.append(entry)
    return normalized


def get_markets_for_commune(siret_acheteur: str, settings: Settings = SETTINGS) -> list[dict]:
    """Retourne les marchés passés par une commune (SIRET/SIREN acheteur), montant >= seuil configuré."""
    where = f'acheteur_id like "{siret_acheteur}"'
    records = _fetch_cached(where, settings)
    return _normalize_records(records, settings.decp.montant_minimum_pertinent)


def get_comparable_markets(code_cpv_prefix: str, settings: Settings = SETTINGS) -> list[dict]:
    """Retourne les marchés d'une même famille CPV, passés par différentes communes.

    Champ CPV non confirmé en direct : where= construit sur le meilleur
    candidat ("codeCPV"). Si l'appel échoue, corriger avec le nom exact
    constaté via describe_schema().
    """
    where = f'codeCPV like "{code_cpv_prefix}%"'
    records = _fetch_cached(where, settings)
    return _normalize_records(records, settings.decp.montant_minimum_pertinent)


def describe_schema(siret_acheteur: str, settings: Settings = SETTINGS) -> dict:
    """Diagnostic : champs réels reçus pour les marchés d'un acheteur donné.

    À utiliser après un premier appel réel pour valider/corriger
    balise.config.DECP_COLUMN_ALIASES.
    """
    where = f'acheteur_id like "{siret_acheteur}"'
    records = _fetch_cached(where, settings)
    if not records:
        return {"fields": [], "sample_record": None}
    return {"fields": list(records[0].keys()), "sample_record": records[0]}
