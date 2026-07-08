from __future__ import annotations

import pytest

from balise.ingestion import _opendatasoft as ods


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ods.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_records_single_page(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({"total_count": 2, "results": [{"a": 1}, {"a": 2}]})

    monkeypatch.setattr(ods.requests, "get", fake_get)

    records = ods.fetch_records("https://example.org", "some-dataset", where='insee="27681"')

    assert records == [{"a": 1}, {"a": 2}]
    assert len(calls) == 1
    assert calls[0]["where"] == 'insee="27681"'
    assert calls[0]["limit"] == 100
    assert calls[0]["offset"] == 0


def test_fetch_records_paginates_until_total_count(monkeypatch):
    pages = {
        0: {"total_count": 5, "results": [{"a": i} for i in range(3)]},
        3: {"total_count": 5, "results": [{"a": i} for i in range(3, 5)]},
    }
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(pages[params["offset"]])

    monkeypatch.setattr(ods.requests, "get", fake_get)

    records = ods.fetch_records("https://example.org", "some-dataset", limit_per_page=3)

    assert [r["a"] for r in records] == [0, 1, 2, 3, 4]
    assert len(calls) == 2


def test_fetch_records_stops_at_max_records(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return FakeResponse({"total_count": 1000, "results": [{"a": 1}] * 100})

    monkeypatch.setattr(ods.requests, "get", fake_get)

    records = ods.fetch_records("https://example.org", "some-dataset", max_records=150)

    assert len(records) == 150


def test_fetch_records_retries_then_raises(monkeypatch):
    attempts = []

    def fake_get(url, params=None, timeout=None):
        attempts.append(1)
        raise ods.requests.ConnectionError("boom")

    monkeypatch.setattr(ods.requests, "get", fake_get)

    with pytest.raises(ods.OpenDataSoftError):
        ods.fetch_records(
            "https://example.org", "some-dataset", max_retries=2, retry_backoff_seconds=0
        )

    assert len(attempts) == 2
