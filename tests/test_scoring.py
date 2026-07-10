from __future__ import annotations

import pytest

from balise import scoring
from balise.ingestion.decp import DecpError

COMMUNE_DATA = {
    "code_insee": "99999",
    "population": 1000.0,
    "strate": "8",
    "charges_de_fonctionnement": 1_000_000.0,  # 1000 €/hab : pile la moyenne des pairs -> conforme
    "charges_de_personnel": 500_000.0,  # 500 €/hab : nettement sous les pairs -> efficient
    "achats_et_charges_externes": 300_000.0,  # identique à tous les pairs (sd=0) -> conforme
    "depenses_d_equipement": 300_000.0,  # identique à tous les pairs (sd=0) -> conforme
    "encours_de_dette": 1_600_000.0,  # 1600 €/hab : très au-dessus des pairs -> alerte
    "subventions_associations": 200_000.0,  # 200 €/hab : pile la moyenne des pairs -> conforme
}

PEERS = [
    {
        "code_insee": f"0000{i}",
        "nom": f"Peer{i}",
        "population": 1000.0,
        "charges_de_fonctionnement": (800_000 + i * 100_000),
        "charges_de_personnel": (700_000 + i * 100_000),
        "achats_et_charges_externes": 300_000.0,
        "depenses_d_equipement": 300_000.0,
        "encours_de_dette": (400_000 + i * 100_000),
        "subventions_associations": (150_000 + i * 25_000),
    }
    for i in range(5)
]

MAINTENANCE_TOTALS = {
    "99999": 50_000.0,  # 50 €/hab : pile la moyenne des pairs -> conforme
    "00000": 40_000.0,
    "00001": 45_000.0,
    "00002": 50_000.0,
    "00003": 55_000.0,
    "00004": 60_000.0,
}


@pytest.fixture
def mocked_sources(monkeypatch):
    monkeypatch.setattr(scoring.ofgl, "get_financial_data", lambda code_insee, exercice=None, settings=None: (
        COMMUNE_DATA if code_insee == "99999" else None
    ))
    monkeypatch.setattr(
        scoring.ofgl,
        "get_peer_group_financial_data",
        lambda strate_value, **kwargs: list(PEERS),
    )
    monkeypatch.setattr(
        scoring.decp,
        "get_maintenance_spending_by_commune",
        lambda settings=None: dict(MAINTENANCE_TOTALS),
    )


def test_score_commune_qualifications(mocked_sources):
    card = scoring.score_commune("99999", exercice=2024)

    assert card.strate_value == "8"
    assert card.peer_group_size == 5
    assert len(card.items) == 7

    by_key = {it.key: it for it in card.items}
    assert by_key["charges_de_fonctionnement"].qualification == "conforme"
    assert by_key["charges_de_personnel"].qualification == "efficient"
    assert by_key["achats_et_charges_externes"].qualification == "conforme"
    assert by_key["achats_et_charges_externes"].z_score == 0.0
    assert by_key["depenses_d_equipement"].qualification == "conforme"
    assert by_key["encours_de_dette"].qualification == "alerte"
    assert by_key["encours_de_dette"].z_score > 2.0
    assert by_key["subventions_associations"].qualification == "conforme"
    assert by_key["subventions_associations"].z_score == 0.0
    assert by_key["entretien"].qualification == "conforme"
    assert by_key["entretien"].commune_par_habitant == pytest.approx(50.0)
    assert by_key["entretien"].peer_median_par_habitant == pytest.approx(50.0)


def test_score_commune_global_score_and_verdict(mocked_sources):
    card = scoring.score_commune("99999", exercice=2024)

    assert 0 <= card.global_score <= 100
    assert card.verdict in {"Efficace", "Vigilance", "Alerte"}
    # Score par poste : fonctionnement=50 (conforme), personnel=100 (très
    # efficient, plafonné), achats=50, équipement=50, dette=0 (très alerté,
    # plafonné), entretien=50 -> moyenne exactement 50, l'effet "personnel
    # très efficient" compense exactement l'effet "dette très alertée".
    assert card.global_score == 50
    assert card.verdict == "Vigilance"


def test_score_commune_peers_sorted_by_population_desc(mocked_sources):
    card = scoring.score_commune("99999", exercice=2024)

    populations = [p.population for p in card.peers]
    assert populations == sorted(populations, reverse=True)
    assert {p.code_insee for p in card.peers} == {p["code_insee"] for p in PEERS}


def test_score_commune_not_found(mocked_sources):
    with pytest.raises(scoring.ScoringError, match="Aucune donnée OFGL"):
        scoring.score_commune("00000", exercice=2024)


def test_score_commune_not_found_mentions_exercice(mocked_sources):
    with pytest.raises(scoring.ScoringError, match="exercice 2024"):
        scoring.score_commune("00000", exercice=2024)


def test_score_commune_missing_strate(monkeypatch):
    monkeypatch.setattr(
        scoring.ofgl,
        "get_financial_data",
        lambda code_insee, exercice=None, settings=None: {"code_insee": code_insee, "population": 1000.0},
    )
    with pytest.raises(scoring.ScoringError, match="Strate démographique"):
        scoring.score_commune("99999", exercice=2024)


def test_maintenance_item_degrades_gracefully_on_decp_error(monkeypatch):
    monkeypatch.setattr(scoring.ofgl, "get_financial_data", lambda code_insee, exercice=None, settings=None: (
        COMMUNE_DATA if code_insee == "99999" else None
    ))
    monkeypatch.setattr(scoring.ofgl, "get_peer_group_financial_data", lambda strate_value, **kwargs: list(PEERS))

    def raise_decp_error(settings=None):
        raise DecpError("panne DECP simulée")

    monkeypatch.setattr(scoring.decp, "get_maintenance_spending_by_commune", raise_decp_error)

    card = scoring.score_commune("99999", exercice=2024)
    entretien = next(it for it in card.items if it.key == "entretien")
    assert entretien.qualification == "donnee_absente"
    assert entretien.item_score is None


# ---- Affinement du groupe de pairs par population (strate OFGL "100 000+" ouverte) ----


def _make_peers_with_population(populations: list[float]) -> list[dict]:
    return [
        {"code_insee": f"peer{i}", "nom": f"Peer{i}", "population": pop}
        for i, pop in enumerate(populations)
    ]


def test_narrow_peer_group_no_narrowing_when_population_close_to_median():
    # Toutes les populations sont dans un facteur 3 de la commune (200_000) : pas d'affinement.
    peers = _make_peers_with_population([150_000.0 + i * 5_000 for i in range(20)])
    result, refined, heterogeneous = scoring._narrow_peer_group_by_population(
        200_000.0, peers, scoring.SETTINGS
    )
    assert result == peers
    assert refined is False
    assert heterogeneous is False


def test_narrow_peer_group_narrows_when_enough_similar_peers_remain():
    # 25 pairs très petites (tirent la médiane du groupe vers le bas, ratio > 3 avec la
    # commune) + 15 pairs proches en ordre de grandeur de la commune (2_000_000) : assez
    # pour resserrer sans repasser sous min_peer_group_size (15).
    far_peers = _make_peers_with_population([50_000.0] * 25)
    close_peers = _make_peers_with_population([1_000_000.0 + i * 10_000 for i in range(15)])
    peers = far_peers + close_peers
    result, refined, heterogeneous = scoring._narrow_peer_group_by_population(
        2_000_000.0, peers, scoring.SETTINGS
    )
    assert refined is True
    assert heterogeneous is False
    assert len(result) == 15
    assert all(p["population"] >= 1_000_000.0 for p in result)


def test_narrow_peer_group_falls_back_when_not_enough_similar_peers():
    # Seulement 3 pairs d'ordre de grandeur comparable à la commune (2_000_000) : pas assez
    # pour resserrer (min_peer_group_size=15) -> groupe complet conservé, signalé hétérogène.
    close_peers = _make_peers_with_population([1_800_000.0, 1_900_000.0, 2_100_000.0])
    far_peers = _make_peers_with_population([120_000.0 + i * 1_000 for i in range(20)])
    peers = close_peers + far_peers
    result, refined, heterogeneous = scoring._narrow_peer_group_by_population(
        2_000_000.0, peers, scoring.SETTINGS
    )
    assert result == peers
    assert refined is False
    assert heterogeneous is True


def test_narrow_peer_group_noop_when_too_few_peers_to_judge():
    # Moins de min_peer_group_size pairs au total : on ne tente même pas d'affiner.
    peers = _make_peers_with_population([5_000.0, 6_000.0])
    result, refined, heterogeneous = scoring._narrow_peer_group_by_population(
        2_000_000.0, peers, scoring.SETTINGS
    )
    assert result == peers
    assert refined is False
    assert heterogeneous is False


def test_score_commune_flags_heterogeneous_peer_group(monkeypatch):
    outlier_commune = {**COMMUNE_DATA, "population": 2_000_000.0}
    close_peers = _make_peers_with_population([1_800_000.0, 1_900_000.0])
    far_peers = [
        {**p, "population": 120_000.0 + i * 1_000}
        for i, p in enumerate(PEERS * 4)  # 20 pairs, toutes petites
    ]
    all_peers = close_peers + far_peers

    monkeypatch.setattr(scoring.ofgl, "get_financial_data", lambda code_insee, exercice=None, settings=None: (
        outlier_commune if code_insee == "99999" else None
    ))
    monkeypatch.setattr(scoring.ofgl, "get_peer_group_financial_data", lambda strate_value, **kwargs: all_peers)
    monkeypatch.setattr(scoring.decp, "get_maintenance_spending_by_commune", lambda settings=None: dict(MAINTENANCE_TOTALS))

    card = scoring.score_commune("99999", exercice=2024)
    assert card.peer_group_heterogeneous is True
    assert card.peer_group_refined is False
    assert card.peer_group_size == len(all_peers)
