"""Client générique pour l'API OpenDataSoft v2.1 "records", utilisé par OFGL et DECP.

Endpoint : {base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records
Pagination : `limit` (<= 100) + `offset`. La réponse JSON contient
`total_count` et `results` (liste d'enregistrements "plats", un dict par
enregistrement, clé = nom de champ).
"""

from __future__ import annotations

import time

import requests

ODS_MAX_LIMIT = 100


class OpenDataSoftError(Exception):
    """Erreur générique d'appel à une API OpenDataSoft (réseau, HTTP, ou format de réponse)."""


def fetch_records(
    base_url: str,
    dataset_id: str,
    where: str | None = None,
    limit_per_page: int = ODS_MAX_LIMIT,
    max_records: int | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    retry_backoff_seconds: float = 1.0,
) -> list[dict]:
    """Récupère, en paginant, tous les enregistrements correspondant à `where` (clause ODSQL)."""
    url = f"{base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records"
    limit_per_page = min(limit_per_page, ODS_MAX_LIMIT)

    records: list[dict] = []
    offset = 0
    while True:
        params: dict = {"limit": limit_per_page, "offset": offset}
        if where:
            params["where"] = where

        payload = _get_json_with_retries(url, params, timeout, max_retries, retry_backoff_seconds)
        results = payload.get("results", [])
        records.extend(results)

        total_count = payload.get("total_count", len(records))
        offset += limit_per_page

        if not results or offset >= total_count:
            break
        if max_records is not None and len(records) >= max_records:
            records = records[:max_records]
            break

    return records


def _get_json_with_retries(
    url: str,
    params: dict,
    timeout: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * attempt)
    raise OpenDataSoftError(
        f"Échec de l'appel à {url} (params={params}) après {max_retries} tentatives : {last_error}"
    ) from last_error
