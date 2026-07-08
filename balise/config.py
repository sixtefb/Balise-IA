"""Paramètres configurables de Balise IA.

Toutes les valeurs susceptibles d'influencer un résultat métier (seuils de
score, bornes de strates démographiques, tailles minimales de groupe de
comparaison, TTL de cache...) sont centralisées ici plutôt que codées en dur
dans les modules d'ingestion, de scoring ou de rapport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DB_PATH = PROJECT_ROOT / "data" / "cache" / "balise.duckdb"


@dataclass(frozen=True)
class StrateThreshold:
    """Une tranche de strate démographique (bornes inclusives, max=None = pas de plafond)."""

    label: str
    population_min: int
    population_max: int | None


# Bornes usuelles des strates démographiques utilisées pour les comparaisons
# de finances locales (DGCL/OFGL). À aligner/recaler une fois le jeu de
# données OFGL intégré, si ses libellés de strates diffèrent.
DEFAULT_STRATES: tuple[StrateThreshold, ...] = (
    StrateThreshold("0 à 249 habitants", 0, 249),
    StrateThreshold("250 à 499 habitants", 250, 499),
    StrateThreshold("500 à 999 habitants", 500, 999),
    StrateThreshold("1 000 à 1 999 habitants", 1_000, 1_999),
    StrateThreshold("2 000 à 3 499 habitants", 2_000, 3_499),
    StrateThreshold("3 500 à 4 999 habitants", 3_500, 4_999),
    StrateThreshold("5 000 à 9 999 habitants", 5_000, 9_999),
    StrateThreshold("10 000 à 19 999 habitants", 10_000, 19_999),
    StrateThreshold("20 000 à 49 999 habitants", 20_000, 49_999),
    StrateThreshold("50 000 à 99 999 habitants", 50_000, 99_999),
    StrateThreshold("100 000 à 199 999 habitants", 100_000, 199_999),
    StrateThreshold("200 000 habitants et plus", 200_000, None),
)


@dataclass(frozen=True)
class ScoringThresholds:
    """Seuils utilisés pour qualifier un écart (module de scoring, étapes suivantes)."""

    watch_abs_zscore: float = 1.0
    alert_abs_zscore: float = 2.0
    min_peer_group_size: int = 15
    target_peer_group_size: int = 20


@dataclass(frozen=True)
class InseeApiSettings:
    """Paramètres d'accès à l'API Découpage administratif (geo.api.gouv.fr)."""

    base_url: str = "https://geo.api.gouv.fr"
    request_timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0


@dataclass(frozen=True)
class Settings:
    cache_db_path: Path = DEFAULT_CACHE_DB_PATH
    cache_ttl_days: int = 30
    insee: InseeApiSettings = field(default_factory=InseeApiSettings)
    strates: tuple[StrateThreshold, ...] = DEFAULT_STRATES
    scoring: ScoringThresholds = field(default_factory=ScoringThresholds)


SETTINGS = Settings()
