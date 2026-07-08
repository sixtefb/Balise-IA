"""Cache local DuckDB.

Objectif : ne jamais retélécharger les gros jeux de données (OFGL, DECP) à
chaque requête, ni re-solliciter inutilement les API externes. Toutes les
tables de cache par source vivent dans le même fichier DuckDB, avec une
colonne `fetched_at` permettant d'appliquer un TTL par source.
"""

from __future__ import annotations

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
)


def get_connection(settings: Settings = SETTINGS) -> duckdb.DuckDBPyConnection:
    """Ouvre (ou crée) la base de cache locale et s'assure que le schéma existe."""
    settings.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.cache_db_path))
    for statement in _SCHEMA_STATEMENTS:
        con.execute(statement)
    return con
