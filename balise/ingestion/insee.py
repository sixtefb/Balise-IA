"""Résolution commune -> code INSEE + métadonnées, via l'API Découpage administratif.

Source : geo.api.gouv.fr (Etalab/DINUM), construite à partir du Code Officiel
Géographique de l'INSEE. Pas de clé d'API requise. Deux appels successifs :

    GET {base_url}/communes?codePostal={code_postal}&fields=...
        -> liste des communes du code postal (désambiguïsation par nom en local)
    GET {base_url}/communes/{code_insee}?fields=nom,code,siren,population
        -> détail (SIREN notamment) de la commune retenue

Les réponses brutes sont mises en cache localement (voir balise.storage.db)
pour éviter de re-solliciter l'API à chaque exécution.
"""

from __future__ import annotations

import json
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import duckdb
import requests

from balise.config import SETTINGS, Settings
from balise.models import CommuneIdentity
from balise.normalization.strates import strate_for_population
from balise.storage.db import get_connection

LIST_FIELDS = (
    "nom,code,codesPostaux,population,surface,"
    "codeDepartement,departement,codeRegion,region,codeEpci,epci"
)
DETAIL_FIELDS = "nom,code,siren,population"


class InseeError(Exception):
    """Erreur générique lors de la résolution d'une commune."""


class CommuneNotFoundError(InseeError):
    """Aucune commune ne correspond aux critères fournis."""


class CommuneAmbiguousError(InseeError):
    """Plusieurs communes correspondent aux critères fournis."""

    def __init__(self, message: str, candidates: list[tuple[str, str]]):
        super().__init__(message)
        self.candidates = candidates


def _normalize(text: str) -> str:
    """Normalise un nom de commune pour comparaison (insensible accents/casse)."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.strip().casefold()


def resolve_commune(
    nom: str,
    code_postal: str,
    settings: Settings = SETTINGS,
    use_cache: bool = True,
) -> CommuneIdentity:
    """Résout un couple (nom, code postal) vers une CommuneIdentity.

    Lève CommuneNotFoundError, CommuneAmbiguousError, ou InseeError (erreur
    réseau/API après épuisement des tentatives).
    """
    con = get_connection(settings)
    nom_key = _normalize(nom)

    if use_cache:
        cached_payload = _read_cache(con, nom_key, code_postal, settings.cache_ttl_days)
        if cached_payload is not None:
            return _identity_from_payload(cached_payload)

    candidates = _fetch_list_by_code_postal(code_postal, settings)
    selected = _select_result(candidates, nom, code_postal)
    detail = _fetch_detail_by_code_insee(selected["code"], settings)
    payload = {**selected, **detail}

    _write_cache(con, nom_key, code_postal, payload)
    return _identity_from_payload(payload)


def _fetch_list_by_code_postal(code_postal: str, settings: Settings) -> list[dict]:
    url = f"{settings.insee.base_url}/communes"
    params = {"codePostal": code_postal, "fields": LIST_FIELDS, "format": "json"}
    return _get_json_with_retries(url, params, settings)


def _fetch_detail_by_code_insee(code_insee: str, settings: Settings) -> dict:
    url = f"{settings.insee.base_url}/communes/{code_insee}"
    params = {"fields": DETAIL_FIELDS, "format": "json"}
    return _get_json_with_retries(url, params, settings)


def _get_json_with_retries(url: str, params: dict, settings: Settings):
    last_error: Exception | None = None
    for attempt in range(1, settings.insee.max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=settings.insee.request_timeout_seconds)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < settings.insee.max_retries:
                time.sleep(settings.insee.retry_backoff_seconds * attempt)

    raise InseeError(
        f"Échec de connexion à l'API géo INSEE ({url}) après "
        f"{settings.insee.max_retries} tentatives : {last_error}"
    ) from last_error


def _select_result(results: list[dict], nom: str, code_postal: str) -> dict:
    if not results:
        raise CommuneNotFoundError(f"Aucune commune trouvée pour '{nom}' ({code_postal}).")

    if len(results) == 1:
        return results[0]

    exact_matches = [r for r in results if _normalize(r.get("nom", "")) == _normalize(nom)]
    if len(exact_matches) == 1:
        return exact_matches[0]

    candidates = [(r.get("nom", "?"), r.get("code", "?")) for r in results]
    raise CommuneAmbiguousError(
        f"{len(results)} communes correspondent à '{nom}' ({code_postal}) : "
        f"{', '.join(f'{n} ({c})' for n, c in candidates)}. "
        "Précisez le nom exact de la commune.",
        candidates=candidates,
    )


def _identity_from_payload(payload: dict) -> CommuneIdentity:
    population = payload.get("population")
    departement = payload.get("departement") or {}
    region = payload.get("region") or {}
    epci = payload.get("epci") or {}

    return CommuneIdentity(
        code_insee=payload["code"],
        nom=payload["nom"],
        codes_postaux=tuple(payload.get("codesPostaux", [])),
        siren=payload.get("siren"),
        population=population,
        surface_km2=payload.get("surface"),
        code_departement=payload.get("codeDepartement") or departement.get("code", ""),
        departement=departement.get("nom", ""),
        code_region=payload.get("codeRegion") or region.get("code", ""),
        region=region.get("nom", ""),
        code_epci=payload.get("codeEpci") or (epci.get("code") if epci else None),
        epci=epci.get("nom") if epci else None,
        strate_demographique=strate_for_population(population) if population is not None else None,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def _read_cache(
    con: duckdb.DuckDBPyConnection,
    nom_key: str,
    code_postal: str,
    ttl_days: int,
) -> dict | None:
    row = con.execute(
        "SELECT payload_json, fetched_at FROM insee_commune_cache "
        "WHERE nom_recherche = ? AND code_postal = ?",
        [nom_key, code_postal],
    ).fetchone()
    if row is None:
        return None

    payload_json, fetched_at = row
    if fetched_at is None:
        return None
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched_at > timedelta(days=ttl_days):
        return None

    return json.loads(payload_json)


def _write_cache(con: duckdb.DuckDBPyConnection, nom_key: str, code_postal: str, payload: dict) -> None:
    con.execute(
        """
        INSERT INTO insee_commune_cache (nom_recherche, code_postal, code_insee, payload_json, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (nom_recherche, code_postal) DO UPDATE SET
            code_insee = excluded.code_insee,
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        [nom_key, code_postal, payload.get("code"), json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc)],
    )
