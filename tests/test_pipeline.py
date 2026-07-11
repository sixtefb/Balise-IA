from __future__ import annotations

from balise import pipeline
from balise.config import SETTINGS
from balise.scoring import CommuneScoreCard, ContextInfo


def _card(
    peer_group_refined=False,
    peer_group_heterogeneous=False,
    custom_peer_group=False,
    custom_peer_unavailable=(),
    peer_group_size=41,
    context=None,
) -> CommuneScoreCard:
    return CommuneScoreCard(
        code_insee="99999",
        exercice=2023,
        strate_value="10",
        peer_group_size=peer_group_size,
        global_score=50,
        verdict="Vigilance",
        items=(),
        peers=(),
        peer_group_refined=peer_group_refined,
        peer_group_heterogeneous=peer_group_heterogeneous,
        custom_peer_group=custom_peer_group,
        custom_peer_unavailable=custom_peer_unavailable,
        context=context,
    )


def _context(**overrides) -> ContextInfo:
    defaults = dict(
        commune_touristique=None,
        commune_montagne=None,
        commune_rural=None,
        commune_qpv=None,
        commune_tranche_revenu=None,
        peer_touristique_share=None,
        peer_montagne_share=None,
        peer_rural_share=None,
        peer_qpv_share=None,
        peer_revenu_median=None,
    )
    defaults.update(overrides)
    return ContextInfo(**defaults)


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


# ---- Groupe de comparaison choisi manuellement (custom_compare_note, strate_label) ----


def test_strate_label_custom_group():
    assert pipeline.strate_label(_card(custom_peer_group=True)) == "groupe personnalisé"


def test_peer_group_note_none_when_custom_group():
    # custom_compare_note prend le relais dans ce cas, pas peer_group_note.
    card = _card(custom_peer_group=True, peer_group_heterogeneous=True)
    assert pipeline.peer_group_note(card) is None


def test_custom_compare_note_none_for_automatic_group():
    assert pipeline.custom_compare_note(_card(custom_peer_group=False)) is None


def test_custom_compare_note_too_few_peers():
    note = pipeline.custom_compare_note(_card(custom_peer_group=True, peer_group_size=1))
    assert note is not None
    assert "moins de deux communes" in note


def test_custom_compare_note_below_min_group_size():
    card = _card(custom_peer_group=True, peer_group_size=3)
    note = pipeline.custom_compare_note(card, settings=SETTINGS)
    assert note is not None
    assert "peu représentatif" in note


def test_custom_compare_note_enough_peers_no_caveat():
    card = _card(custom_peer_group=True, peer_group_size=SETTINGS.scoring.min_peer_group_size)
    note = pipeline.custom_compare_note(card, settings=SETTINGS)
    assert note is not None
    assert "peu représentatif" not in note
    assert "communes choisies manuellement" in note


def test_custom_compare_note_lists_unresolved_and_unavailable():
    card = _card(custom_peer_group=True, peer_group_size=5, custom_peer_unavailable=("00099",))
    note = pipeline.custom_compare_note(card, unresolved_names=["Villeinconnue (99999)"], settings=SETTINGS)
    assert "Villeinconnue (99999)" in note
    assert "00099" in note


# ---- Contexte OFGL (context_note) ----


def test_context_note_none_without_context():
    assert pipeline.context_note(_card(context=None)) is None


def test_context_note_none_when_context_matches_peers():
    card = _card(context=_context(commune_touristique=False, peer_touristique_share=0.8))
    assert pipeline.context_note(card) is None


def test_context_note_flags_touristique_mismatch():
    card = _card(context=_context(commune_touristique=True, peer_touristique_share=0.05))
    note = pipeline.context_note(card)
    assert note is not None
    assert "touristique" in note


def test_context_note_flags_revenu_mismatch():
    card = _card(context=_context(commune_tranche_revenu="5", peer_revenu_median=1.0))
    note = pipeline.context_note(card)
    assert note is not None
    assert "niveau de vie" in note
    assert "30 000" in note


def test_context_note_no_flag_when_revenu_gap_small():
    card = _card(context=_context(commune_tranche_revenu="2", peer_revenu_median=1.0))
    assert pipeline.context_note(card) is None


def test_context_note_combines_multiple_mismatches():
    card = _card(
        context=_context(
            commune_touristique=True,
            peer_touristique_share=0.0,
            commune_qpv=True,
            peer_qpv_share=0.0,
        )
    )
    note = pipeline.context_note(card)
    assert "touristique" in note
    assert "quartier prioritaire" in note
