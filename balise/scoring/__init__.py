"""Groupe de comparaison et calcul des écarts par poste de dépense.

- `build_peer_group` : communes de même strate démographique OFGL
  (`tranche_population`), à l'échelle nationale, hors la commune auditée.
  Pas d'élargissement géographique supplémentaire à ce stade : à l'échelle
  nationale le groupe est déjà largement > `ScoringThresholds.min_peer_group_size`
  en pratique (voir `CommuneScoreCard.peer_group_size`, exposé pour que
  l'appelant puisse alerter si ce n'était pas le cas).
- `score_commune` : calcule, pour chaque poste de dépense configuré, le
  z-score de la commune par rapport à son groupe de comparaison (en
  €/habitant), et un score global 0-100 dérivé de la moyenne de ces z-scores.

Hypothèse simplificatrice assumée : pour chaque poste de dépense, dépenser
moins que le groupe de comparaison est considéré "efficient" et dépenser
plus est considéré "à surveiller"/"alerte". C'est une lecture raisonnable
pour un premier score global, mais elle ne capture pas les cas où une
dépense plus faible refléterait un sous-investissement (ex. dépenses
d'équipement) plutôt qu'une efficience réelle - à affiner si besoin.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, pstdev

from balise.config import SETTINGS, Settings
from balise.ingestion import ofgl
from balise.normalization.spending import normalize_financial_data


class ScoringError(Exception):
    """Erreur générique du module de scoring."""


@dataclass(frozen=True)
class SpendingItemScore:
    """Comparaison d'un poste de dépense (en €/habitant) à son groupe de pairs."""

    key: str
    label: str
    commune_par_habitant: float | None
    peer_median_par_habitant: float | None
    peer_count: int
    peer_values: tuple[float, ...]  # €/habitant de chaque pair, pour affichage de distribution
    z_score: float | None
    delta_pct: float | None  # (commune - médiane pairs) / médiane pairs
    qualification: str  # "efficient" | "conforme" | "a_surveiller" | "alerte" | "donnee_absente"
    item_score: int | None  # 0-100, None si donnee_absente


@dataclass(frozen=True)
class PeerCommune:
    """Une commune du groupe de comparaison (identité minimale, pour affichage)."""

    code_insee: str
    nom: str | None
    population: float | None


@dataclass(frozen=True)
class CommuneScoreCard:
    """Résultat complet du scoring d'une commune pour un exercice donné."""

    code_insee: str
    exercice: int | None
    strate_value: str
    peer_group_size: int
    global_score: int
    verdict: str  # "Efficace" | "Vigilance" | "Alerte"
    items: tuple[SpendingItemScore, ...]
    peers: tuple[PeerCommune, ...]


def _qualify(z_score: float, thresholds=SETTINGS.scoring) -> str:
    if z_score >= thresholds.alert_abs_zscore:
        return "alerte"
    if z_score >= thresholds.watch_abs_zscore:
        return "a_surveiller"
    if z_score <= -thresholds.watch_abs_zscore:
        return "efficient"
    return "conforme"


def _item_score(z_score: float) -> int:
    """Convertit un z-score en note 0-100 (50 = moyenne du groupe de pairs)."""
    return round(max(0.0, min(100.0, 50 - 20 * z_score)))


def _verdict(global_score: int) -> str:
    if global_score < 45:
        return "Alerte"
    if global_score >= 70:
        return "Efficace"
    return "Vigilance"


def build_peer_group(
    code_insee: str,
    strate_value: str,
    exercice: int | None,
    settings: Settings = SETTINGS,
    code_departement: str | None = None,
    code_region: str | None = None,
) -> list[dict]:
    """Communes de même strate démographique OFGL, hors la commune auditée."""
    return ofgl.get_peer_group_financial_data(
        strate_value,
        exercice=exercice,
        code_departement=code_departement,
        code_region=code_region,
        exclude_code_insee=code_insee,
        settings=settings,
    )


def score_commune(
    code_insee: str,
    exercice: int | None = None,
    settings: Settings = SETTINGS,
) -> CommuneScoreCard:
    """Calcule le score d'efficacité budgétaire d'une commune vs son groupe de pairs."""
    commune_data = ofgl.get_financial_data(code_insee, exercice=exercice, settings=settings)
    if commune_data is None:
        raise ScoringError(f"Aucune donnée OFGL pour la commune {code_insee}.")

    strate_value = commune_data.get("strate")
    if not strate_value:
        raise ScoringError(f"Strate démographique OFGL introuvable pour la commune {code_insee}.")

    peers = build_peer_group(code_insee, strate_value, exercice, settings=settings)
    commune_norm = normalize_financial_data(commune_data, settings=settings)
    peers_norm = [normalize_financial_data(p, settings=settings) for p in peers]

    items: list[SpendingItemScore] = []
    for item in settings.spending_items:
        commune_value = commune_norm[item.key]
        peer_values = [v[item.key] for v in peers_norm if v[item.key] is not None]

        if commune_value is None or len(peer_values) < 2:
            items.append(
                SpendingItemScore(
                    key=item.key,
                    label=item.label,
                    commune_par_habitant=commune_value,
                    peer_median_par_habitant=median(peer_values) if peer_values else None,
                    peer_count=len(peer_values),
                    peer_values=tuple(peer_values),
                    z_score=None,
                    delta_pct=None,
                    qualification="donnee_absente",
                    item_score=None,
                )
            )
            continue

        peer_mean = mean(peer_values)
        peer_sd = pstdev(peer_values)
        z_score = 0.0 if peer_sd == 0 else (commune_value - peer_mean) / peer_sd
        peer_median = median(peer_values)
        delta_pct = None if peer_median == 0 else (commune_value - peer_median) / peer_median

        items.append(
            SpendingItemScore(
                key=item.key,
                label=item.label,
                commune_par_habitant=commune_value,
                peer_median_par_habitant=peer_median,
                peer_count=len(peer_values),
                peer_values=tuple(peer_values),
                z_score=z_score,
                delta_pct=delta_pct,
                qualification=_qualify(z_score, settings.scoring),
                item_score=_item_score(z_score),
            )
        )

    scored = [it.item_score for it in items if it.item_score is not None]
    global_score = round(mean(scored)) if scored else 50

    peer_communes = tuple(
        sorted(
            (
                PeerCommune(code_insee=p["code_insee"], nom=p.get("nom"), population=p.get("population"))
                for p in peers
            ),
            key=lambda p: p.population or 0,
            reverse=True,
        )
    )

    return CommuneScoreCard(
        code_insee=code_insee,
        exercice=exercice,
        strate_value=str(strate_value),
        peer_group_size=len(peers),
        global_score=global_score,
        verdict=_verdict(global_score),
        items=tuple(items),
        peers=peer_communes,
    )
