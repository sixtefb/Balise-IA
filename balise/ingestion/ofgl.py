"""Ingestion des agrégats financiers OFGL (data.ofgl.fr, API OpenDataSoft v2.1).

Endpoints "records" (JSON, sans clé), interrogés directement plutôt que par
téléchargement de fichier complet :

    GET {base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records
        ?where=insee="{code_insee}"
    GET {base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records
        ?where=tranche_population="{valeur_strate}"

Les jeux "ofgl-base-communes" / "ofgl-base-communes-consolidee" sont publiés
au format long (une ligne par commune x exercice x agrégat).

Champs confirmés par appel réel (voir scripts/probe_apis.py) : `insee` et
`tranche_population` (le champ démographique s'appelle `tranche_population`
dans ce dataset, pas `strate`). Le reste du schéma (agrégats, montants,
population, département/région) se résout par correspondance tolérante
(balise.config.OFGL_COLUMN_ALIASES / OFGL_AGGREGATE_ALIASES) qui échoue
explicitement, avec la liste des champs réellement présents, plutôt que de
produire silencieusement un résultat erroné. Utiliser describe_schema()
pour valider/corriger ces alias au fil de l'eau.
"""

from __future__ import annotations

import unicodedata

from balise.config import OFGL_AGGREGATE_ALIASES, OFGL_COLUMN_ALIASES, SETTINGS, Settings
from balise.ingestion._opendatasoft import OpenDataSoftError, fetch_records
from balise.storage.db import get_connection, read_query_cache, write_query_cache


class OfglError(Exception):
    """Erreur générique du module d'ingestion OFGL."""


class OfglSchemaError(OfglError):
    """Un champ attendu n'a pas pu être identifié dans les enregistrements OFGL reçus."""

    def __init__(self, canonical_field: str, available_fields: list[str]):
        super().__init__(
            f"Impossible d'identifier le champ correspondant à '{canonical_field}' dans "
            f"la réponse OFGL. Champs disponibles : {available_fields}. "
            "Complétez balise.config.OFGL_COLUMN_ALIASES avec le nom exact constaté."
        )
        self.canonical_field = canonical_field
        self.available_fields = available_fields


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.strip().lower()


def _resolve_field(available_fields: list[str], canonical: str) -> str:
    normalized_map = {_normalize(f): f for f in available_fields}
    candidates = [_normalize(c) for c in OFGL_COLUMN_ALIASES.get(canonical, ())]

    for candidate in candidates:
        if candidate in normalized_map:
            return normalized_map[candidate]

    for norm_field, orig_field in normalized_map.items():
        if any(candidate in norm_field for candidate in candidates):
            return orig_field

    raise OfglSchemaError(canonical, available_fields)


def _try_resolve_field(available_fields: list[str], canonical: str) -> str | None:
    try:
        return _resolve_field(available_fields, canonical)
    except OfglSchemaError:
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


def _match_aggregate(agregat_label) -> str | None:
    """Match un libellé d'agrégat OFGL à un poste de dépense canonique.

    Comparaison exacte (et non par sous-chaîne) : le jeu réel contient des
    libellés qui se chevauchent en sous-chaîne (ex. "Dépenses de
    fonctionnement" vs "Autres dépenses de fonctionnement", "Encours de
    dette" vs "Encours de dette - Dettes bancaires et assimilées"). Une
    correspondance par sous-chaîne ferait écraser la valeur totale par une
    valeur de sous-catégorie selon l'ordre d'arrivée des enregistrements.
    """
    if not agregat_label:
        return None
    normalized_label = _normalize(agregat_label)
    for item_key, aliases in OFGL_AGGREGATE_ALIASES.items():
        if any(_normalize(alias) == normalized_label for alias in aliases):
            return item_key
    return None


def _dataset_id(dataset: str, settings: Settings) -> str:
    return getattr(settings.ofgl, f"dataset_{dataset}")


def _fetch_cached(dataset_id: str, where: str, settings: Settings) -> list[dict]:
    con = get_connection(settings)
    cache_key = f"ofgl:{dataset_id}:{where}"

    cached = read_query_cache(con, cache_key, settings.cache_ttl_days)
    if cached is not None:
        return cached

    try:
        records = fetch_records(
            settings.ofgl.base_url,
            dataset_id,
            where=where,
            max_records=settings.ofgl.max_records_per_query,
            timeout=settings.ofgl.request_timeout_seconds,
            max_retries=settings.ofgl.max_retries,
            retry_backoff_seconds=settings.ofgl.retry_backoff_seconds,
        )
    except OpenDataSoftError as exc:
        raise OfglError(str(exc)) from exc

    write_query_cache(con, cache_key, records)
    return records


def _pivot_records(records: list[dict], exercice: int | None = None) -> dict[str, dict]:
    if not records:
        return {}

    sample_fields = list(records[0].keys())
    code_insee_field = _resolve_field(sample_fields, "code_insee")
    siren_field = _try_resolve_field(sample_fields, "siren")
    population_field = _try_resolve_field(sample_fields, "population")
    dep_field = _try_resolve_field(sample_fields, "code_departement")
    reg_field = _try_resolve_field(sample_fields, "code_region")
    exercice_field = _try_resolve_field(sample_fields, "exercice")
    agregat_field = _resolve_field(sample_fields, "agregat")
    montant_field = _resolve_field(sample_fields, "montant")

    by_commune: dict[str, dict] = {}
    for record in records:
        if exercice is not None and exercice_field is not None:
            record_exercice = _parse_number(record.get(exercice_field))
            if record_exercice is not None and int(record_exercice) != int(exercice):
                continue

        code_insee_value = str(record.get(code_insee_field) or "").strip()
        if not code_insee_value:
            continue

        entry = by_commune.setdefault(
            code_insee_value,
            {
                "code_insee": code_insee_value,
                "siren": record.get(siren_field) if siren_field else None,
                "population": _parse_number(record.get(population_field)) if population_field else None,
                "code_departement": (
                    str(record.get(dep_field)).strip() if dep_field and record.get(dep_field) is not None else None
                ),
                "code_region": (
                    str(record.get(reg_field)).strip() if reg_field and record.get(reg_field) is not None else None
                ),
            },
        )

        item_key = _match_aggregate(record.get(agregat_field))
        if item_key is not None:
            entry[item_key] = _parse_number(record.get(montant_field))

    return by_commune


def get_financial_data(
    code_insee: str,
    exercice: int | None = None,
    dataset: str = "communes",
    settings: Settings = SETTINGS,
) -> dict | None:
    """Retourne les agrégats financiers d'une commune (éventuellement filtrés sur un exercice)."""
    dataset_id = _dataset_id(dataset, settings)
    where = f'insee="{code_insee}"'
    records = _fetch_cached(dataset_id, where, settings)
    by_commune = _pivot_records(records, exercice=exercice)
    return by_commune.get(str(code_insee))


def get_peer_group_financial_data(
    strate_value: str,
    exercice: int | None = None,
    code_departement: str | None = None,
    code_region: str | None = None,
    exclude_code_insee: str | None = None,
    dataset: str = "communes",
    settings: Settings = SETTINGS,
) -> list[dict]:
    """Retourne les agrégats financiers des communes de la même strate OFGL (`where=strate=...`).

    Le filtrage par département/région se fait côté client (après réception),
    faute de connaître avec certitude le nom exact du champ correspondant
    pour l'inclure dans la clause `where` envoyée à l'API.
    """
    dataset_id = _dataset_id(dataset, settings)
    where = f'tranche_population="{strate_value}"'
    records = _fetch_cached(dataset_id, where, settings)
    by_commune = _pivot_records(records, exercice=exercice)

    peers = list(by_commune.values())
    if code_departement is not None:
        peers = [p for p in peers if p.get("code_departement") == code_departement]
    if code_region is not None:
        peers = [p for p in peers if p.get("code_region") == code_region]
    if exclude_code_insee is not None:
        peers = [p for p in peers if p["code_insee"] != exclude_code_insee]
    return peers


def describe_schema(code_insee: str, dataset: str = "communes", settings: Settings = SETTINGS) -> dict:
    """Diagnostic : champs réels + valeurs distinctes de l'agrégat, pour une commune donnée.

    À utiliser après un premier appel réel pour valider/corriger
    balise.config.OFGL_COLUMN_ALIASES et OFGL_AGGREGATE_ALIASES.
    """
    dataset_id = _dataset_id(dataset, settings)
    where = f'insee="{code_insee}"'
    records = _fetch_cached(dataset_id, where, settings)
    if not records:
        return {"fields": [], "agregat_distinct_values": [], "sample_record": None}

    fields = list(records[0].keys())
    result: dict = {"fields": fields, "sample_record": records[0]}
    agregat_field = _try_resolve_field(fields, "agregat")
    if agregat_field is not None:
        result["agregat_field"] = agregat_field
        result["agregat_distinct_values"] = sorted({r.get(agregat_field) for r in records if r.get(agregat_field)})
    return result
