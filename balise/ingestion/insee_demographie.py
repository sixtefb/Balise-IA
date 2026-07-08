"""Démographie détaillée (population par tranche d'âge), api.insee.fr (Melodi).

Endpoint (JSON, sans clé — confirmé en direct, contrairement à l'ancienne
API Insee "api.insee.fr/donnees-locales" qui exigeait un jeton) :

    GET https://api.insee.fr/melodi/data/DS_RP_POPULATION_PRINC?GEO=COM-{code_insee}

Champ confirmé par appel réel : GEO doit être au format "COM-{code_insee}"
(le code seul renvoie une erreur 400 "Type de territoire non reconnu").
Plusieurs millésimes de recensement sont disponibles par commune
(TIME_PERIOD, ex. 2012/2017/2023 au moment de l'écriture) ; on retient le
plus récent disponible.

Contexte, pas score : contrairement aux postes de dépense (OFGL) ou à
"Entretien" (DECP), la démographie ne se compare pas en "efficace/pas
efficace" — elle sert à contextualiser le rapport (une commune plus âgée
dépense normalement plus en social, ce n'est pas un signe d'inefficacité).
N'entre donc pas dans balise.scoring.
"""

from __future__ import annotations

import requests

from balise.config import SETTINGS, Settings
from balise.storage.db import get_connection, read_query_cache, write_query_cache

MELODI_BASE_URL = "https://api.insee.fr/melodi"
POPULATION_DATASET = "DS_RP_POPULATION_PRINC"
REQUEST_TIMEOUT_SECONDS = 15.0

# Tranches d'âge non chevauchantes confirmées par appel réel (leur somme
# est strictement égale à la population totale du millésime) — à distinguer
# des dimensions "cumulatives" du même jeu (Y_LT20, Y20T64, Y_GE65...), non
# retenues ici pour éviter tout double comptage.
AGE_BRACKETS: tuple[tuple[str, str], ...] = (
    ("Y_LT15", "0-14 ans"),
    ("Y15T24", "15-24 ans"),
    ("Y25T39", "25-39 ans"),
    ("Y40T54", "40-54 ans"),
    ("Y55T64", "55-64 ans"),
    ("Y65T79", "65-79 ans"),
    ("Y_GE80", "80 ans et plus"),
)


class InseeDemographieError(Exception):
    """Erreur générique du module démographie INSEE (Melodi)."""


def _fetch_cached(code_insee: str, settings: Settings) -> list[dict]:
    con = get_connection(settings)
    cache_key = f"insee_demo:{POPULATION_DATASET}:{code_insee}"

    cached = read_query_cache(con, cache_key, settings.cache_ttl_days)
    if cached is not None:
        return cached

    url = f"{MELODI_BASE_URL}/data/{POPULATION_DATASET}"
    try:
        response = requests.get(url, params={"GEO": f"COM-{code_insee}"}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise InseeDemographieError(f"Échec de l'appel à {url} pour {code_insee} : {exc}") from exc

    observations = response.json().get("observations", [])
    write_query_cache(con, cache_key, observations)
    return observations


def get_age_breakdown(code_insee: str, settings: Settings = SETTINGS) -> dict | None:
    """Répartition de la population par tranche d'âge (millésime le plus récent disponible).

    Retourne None si aucune donnée n'est exploitable pour cette commune.
    """
    try:
        observations = _fetch_cached(code_insee, settings)
    except InseeDemographieError:
        return None
    if not observations:
        return None

    years = sorted({o["dimensions"]["TIME_PERIOD"] for o in observations})
    if not years:
        return None
    latest_year = years[-1]

    values_by_age = {
        o["dimensions"]["AGE"]: o["measures"]["OBS_VALUE_NIVEAU"]["value"]
        for o in observations
        if o["dimensions"]["TIME_PERIOD"] == latest_year and o["dimensions"]["SEX"] == "_T"
    }

    brackets = []
    total = 0.0
    for code, label in AGE_BRACKETS:
        value = values_by_age.get(code)
        if value is None:
            continue
        brackets.append({"code": code, "label": label, "population": round(value)})
        total += value

    if not brackets:
        return None

    return {
        "millesime": latest_year,
        "population_totale": round(total),
        "brackets": brackets,
    }
