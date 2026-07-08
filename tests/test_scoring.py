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
    assert len(card.items) == 6

    by_key = {it.key: it for it in card.items}
    assert by_key["charges_de_fonctionnement"].qualification == "conforme"
    assert by_key["charges_de_personnel"].qualification == "efficient"
    assert by_key["achats_et_charges_externes"].qualification == "conforme"
    assert by_key["achats_et_charges_externes"].z_score == 0.0
    assert by_key["depenses_d_equipement"].qualification == "conforme"
    assert by_key["encours_de_dette"].qualification == "alerte"
    assert by_key["encours_de_dette"].z_score > 2.0
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
