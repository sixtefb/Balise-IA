"""Cache local DuckDB.

Objectif : ne pas re-solliciter inutilement les API externes (INSEE, OFGL,
DECP) à chaque requête. Toutes les tables de cache vivent dans le même
fichier DuckDB.

- `insee_commune_cache` : cache dédié à la résolution commune -> identité
  (une ligne par (nom, code postal), avec son propre `fetched_at`).
- `api_query_cache` : cache générique par requête (clé arbitraire ->
  liste d'enregistrements JSON), utilisé par les clients OFGL et DECP qui
  interrogent l'API OpenDataSoft "records" avec des clauses `where`
  variables plutôt que de télécharger un jeu de données complet.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import duckdb

from balise.config import SETTINGS, Settings

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS insee_commune_cache (
        nom_recherche VARCHAR NOT NULL,
        code_postal VARCHAR NOT NULL,
        code_insee VARCHAR,
        payload_json VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL,
        PRIMARY KEY (nom_recherche, code_postal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_query_cache (
        cache_key VARCHAR PRIMARY KEY,
        payload_json VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL
    )
    """,
)


def get_connection(settings: Settings = SETTINGS) -> duckdb.DuckDBPyConnection:
    """Ouvre (ou crée) la base de cache locale et s'assure que le schéma existe."""
    settings.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.cache_db_path))
    for statement in _SCHEMA_STATEMENTS:
        con.execute(statement)
    return con


def read_query_cache(
    con: duckdb.DuckDBPyConnection,
    cache_key: str,
    ttl_days: int,
) -> list[dict] | None:
    """Retourne les enregistrements en cache pour `cache_key`, ou None si absent/expiré."""
    row = con.execute(
        "SELECT payload_json, fetched_at FROM api_query_cache WHERE cache_key = ?",
        [cache_key],
    ).fetchone()
    if row is None:
        return None

    payload_json, fetched_at = row
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched_at > timedelta(days=ttl_days):
        return None

    return json.loads(payload_json)


def write_query_cache(con: duckdb.DuckDBPyConnection, cache_key: str, records: list[dict]) -> None:
    """Enregistre le résultat d'une requête (liste de dicts JSON-sérialisables) en cache."""
    con.execute(
        """
        INSERT INTO api_query_cache (cache_key, payload_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT (cache_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        [cache_key, json.dumps(records, ensure_ascii=False), datetime.now(timezone.utc)],
    )
