from __future__ import annotations

import pytest

from balise.ingestion import insee_demographie as demo


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise demo.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _observation(age: str, sex: str, year: str, value: float) -> dict:
    return {
        "attributes": {"OBS_STATUS": "A"},
        "dimensions": {"GEO": "2026-COM-27681", "SEX": sex, "FREQ": "A", "TIME_PERIOD": year, "AGE": age},
        "measures": {"OBS_VALUE_NIVEAU": {"value": value}},
    }


VERNON_OBSERVATIONS = [
    # Ancien millésime : ne doit pas être retenu.
    _observation("Y_LT15", "_T", "2017", 4000.0),
    _observation("Y_LT15", "F", "2017", 2000.0),
    # Millésime le plus récent, sexes détaillés + total (_T) par tranche.
    _observation("Y_LT15", "F", "2023", 2400.0),
    _observation("Y_LT15", "M", "2023", 2454.0),
    _observation("Y_LT15", "_T", "2023", 4854.0),
    _observation("Y15T24", "_T", "2023", 3018.0),
    _observation("Y25T39", "_T", "2023", 4597.0),
    _observation("Y40T54", "_T", "2023", 4835.0),
    _observation("Y55T64", "_T", "2023", 2958.0),
    _observation("Y65T79", "_T", "2023", 3344.0),
    _observation("Y_GE80", "_T", "2023", 1684.0),
    # Dimensions cumulatives présentes dans le vrai jeu mais volontairement
    # ignorées (chevauchent les tranches ci-dessus) : ne doivent pas fausser
    # le total.
    _observation("Y_GE65", "_T", "2023", 5028.0),
    _observation("Y_LT20", "_T", "2023", 6500.0),
    _observation("_T", "_T", "2023", 25290.0),
]


@pytest.fixture
def fake_get(monkeypatch):
    calls = []

    def fake_requests_get(url, params=None, timeout=None):
        calls.append((url, params))
        if params.get("GEO") == "COM-27681":
            return FakeResponse({"observations": VERNON_OBSERVATIONS})
        return FakeResponse({"observations": []})

    monkeypatch.setattr(demo.requests, "get", fake_requests_get)
    return calls


def test_get_age_breakdown_uses_latest_millesime_only(fake_get, settings_with_tmp_cache):
    result = demo.get_age_breakdown("27681", settings=settings_with_tmp_cache)

    assert result["millesime"] == "2023"
    by_code = {b["code"]: b["population"] for b in result["brackets"]}
    assert by_code["Y_LT15"] == 4854
    assert "Y_GE65" not in by_code  # dimension cumulative ignorée
    assert "Y_LT20" not in by_code  # dimension cumulative ignorée
    assert result["population_totale"] == sum(by_code.values())
    assert result["population_totale"] == 25290


def test_get_age_breakdown_uses_cache_on_second_call(fake_get, settings_with_tmp_cache):
    demo.get_age_breakdown("27681", settings=settings_with_tmp_cache)
    demo.get_age_breakdown("27681", settings=settings_with_tmp_cache)

    assert len(fake_get) == 1


def test_get_age_breakdown_returns_none_when_no_data(fake_get, settings_with_tmp_cache):
    assert demo.get_age_breakdown("00000", settings=settings_with_tmp_cache) is None


def test_get_age_breakdown_returns_none_on_network_error(monkeypatch, settings_with_tmp_cache):
    def raise_error(url, params=None, timeout=None):
        raise demo.requests.ConnectionError("panne réseau simulée")

    monkeypatch.setattr(demo.requests, "get", raise_error)

    assert demo.get_age_breakdown("27681", settings=settings_with_tmp_cache) is None
