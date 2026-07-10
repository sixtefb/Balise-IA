from __future__ import annotations

from balise import pipeline
from balise.scoring import CommuneScoreCard


def _card(peer_group_refined=False, peer_group_heterogeneous=False) -> CommuneScoreCard:
    return CommuneScoreCard(
        code_insee="99999",
        exercice=2023,
        strate_value="10",
        peer_group_size=41,
        global_score=50,
        verdict="Vigilance",
        items=(),
        peers=(),
        peer_group_refined=peer_group_refined,
        peer_group_heterogeneous=peer_group_heterogeneous,
    )


def test_peer_group_note_none_by_default():
    assert pipeline.peer_group_note(_card()) is None


def test_peer_group_note_when_refined():
    note = pipeline.peer_group_note(_card(peer_group_refined=True))
    assert note is not None
    assert "resserrée" in note


def test_peer_group_note_when_heterogeneous():
    note = pipeline.peer_group_note(_card(peer_group_heterogeneous=True))
    assert note is not None
    assert "prudence" in note


def test_decp_coverage_note_none_above_threshold():
    assert pipeline.decp_coverage_note(pipeline.DECP_LOW_COVERAGE_THRESHOLD) is None
    assert pipeline.decp_coverage_note(pipeline.DECP_LOW_COVERAGE_THRESHOLD + 10) is None


def test_decp_coverage_note_zero_markets():
    note = pipeline.decp_coverage_note(0)
    assert note is not None
    assert "Aucun marché" in note


def test_decp_coverage_note_few_markets():
    note = pipeline.decp_coverage_note(2)
    assert note is not None
    assert "2 marché" in note


# ---- Signalement des montants exceptionnels (marchés DECP) ----


def test_flag_outlier_markets_flags_montant_above_annual_budget():
    markets = [
        {"montant": 500_000.0},  # sous le budget de référence -> pas signalé
        {"montant": 99_999_997_952.0},  # très au-dessus -> signalé
    ]
    result = pipeline._flag_outlier_markets(markets, budget_reference=10_000_000.0)

    assert result[0]["montant_exceptionnel"] is False
    assert result[1]["montant_exceptionnel"] is True
    # Le montant lui-même n'est jamais modifié.
    assert result[1]["montant"] == 99_999_997_952.0


def test_flag_outlier_markets_no_flag_when_budget_reference_missing():
    markets = [{"montant": 99_999_997_952.0}]
    result = pipeline._flag_outlier_markets(markets, budget_reference=None)

    assert result[0]["montant_exceptionnel"] is False
    assert result[0]["montant"] == 99_999_997_952.0


def test_flag_outlier_markets_no_flag_when_budget_reference_zero():
    markets = [{"montant": 1_000_000.0}]
    result = pipeline._flag_outlier_markets(markets, budget_reference=0.0)

    assert result[0]["montant_exceptionnel"] is False


def test_flag_outlier_markets_exactly_at_threshold_not_flagged():
    markets = [{"montant": 10_000_000.0}]
    result = pipeline._flag_outlier_markets(markets, budget_reference=10_000_000.0)

    assert result[0]["montant_exceptionnel"] is False
