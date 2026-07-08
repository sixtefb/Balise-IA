from __future__ import annotations

import pytest

from balise.ingestion import insee


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise insee.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


VERNON_PAYLOAD = {
    "nom": "Vernon",
    "code": "27681",
    "codesPostaux": ["27200"],
    "siren": "212706810",
    "population": 23346,
    "surface": 15.28,
    "codeDepartement": "27",
    "departement": {"code": "27", "nom": "Eure"},
    "codeRegion": "28",
    "region": {"code": "28", "nom": "Normandie"},
    "codeEpci": "200023414",
    "epci": {"code": "200023414", "nom": "CA Seine Normandie Agglomération"},
}


def test_resolve_commune_success(monkeypatch, settings_with_tmp_cache):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse([VERNON_PAYLOAD])

    monkeypatch.setattr(insee.requests, "get", fake_get)

    commune = insee.resolve_commune("Vernon", "27200", settings=settings_with_tmp_cache)

    assert commune.code_insee == "27681"
    assert commune.siren == "212706810"
    assert commune.population == 23346
    assert commune.codes_postaux == ("27200",)
    assert commune.departement == "Eure"
    assert commune.region == "Normandie"
    assert commune.strate_demographique == "20 000 à 49 999 habitants"
    assert len(calls) == 1


def test_resolve_commune_uses_cache_on_second_call(monkeypatch, settings_with_tmp_cache):
    call_count = 0

    def fake_get(url, params=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return FakeResponse([VERNON_PAYLOAD])

    monkeypatch.setattr(insee.requests, "get", fake_get)

    insee.resolve_commune("Vernon", "27200", settings=settings_with_tmp_cache)
    insee.resolve_commune("Vernon", "27200", settings=settings_with_tmp_cache)

    assert call_count == 1


def test_resolve_commune_not_found(monkeypatch, settings_with_tmp_cache):
    monkeypatch.setattr(insee.requests, "get", lambda url, params=None, timeout=None: FakeResponse([]))

    with pytest.raises(insee.CommuneNotFoundError):
        insee.resolve_commune("Villeimaginaire", "00000", settings=settings_with_tmp_cache)


def test_resolve_commune_ambiguous(monkeypatch, settings_with_tmp_cache):
    payload = [
        {**VERNON_PAYLOAD, "nom": "Saint-Martin", "code": "11111"},
        {**VERNON_PAYLOAD, "nom": "Saint-Martin-le-Vieux", "code": "22222"},
    ]
    monkeypatch.setattr(insee.requests, "get", lambda url, params=None, timeout=None: FakeResponse(payload))

    with pytest.raises(insee.CommuneAmbiguousError) as excinfo:
        insee.resolve_commune("Saint", "27200", settings=settings_with_tmp_cache)

    assert len(excinfo.value.candidates) == 2


def test_resolve_commune_disambiguates_on_exact_name_match(monkeypatch, settings_with_tmp_cache):
    payload = [
        {**VERNON_PAYLOAD, "nom": "Vernon", "code": "27681"},
        {**VERNON_PAYLOAD, "nom": "Vernonnet", "code": "99999"},
    ]
    monkeypatch.setattr(insee.requests, "get", lambda url, params=None, timeout=None: FakeResponse(payload))

    commune = insee.resolve_commune("Vernon", "27200", settings=settings_with_tmp_cache)

    assert commune.code_insee == "27681"


def test_resolve_commune_retries_then_raises(monkeypatch, settings_with_tmp_cache):
    import dataclasses

    fast_settings = dataclasses.replace(
        settings_with_tmp_cache,
        insee=dataclasses.replace(settings_with_tmp_cache.insee, max_retries=2, retry_backoff_seconds=0),
    )

    attempts = []

    def fake_get(url, params=None, timeout=None):
        attempts.append(1)
        raise insee.requests.ConnectionError("boom")

    monkeypatch.setattr(insee.requests, "get", fake_get)

    with pytest.raises(insee.InseeError):
        insee.resolve_commune("Vernon", "27200", settings=fast_settings)

    assert len(attempts) == 2
