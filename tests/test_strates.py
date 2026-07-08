from __future__ import annotations

from balise.normalization.strates import strate_for_population


def test_strate_boundaries():
    assert strate_for_population(0) == "0 à 249 habitants"
    assert strate_for_population(249) == "0 à 249 habitants"
    assert strate_for_population(250) == "250 à 499 habitants"
    assert strate_for_population(23_346) == "20 000 à 49 999 habitants"
    assert strate_for_population(500_000) == "200 000 habitants et plus"
