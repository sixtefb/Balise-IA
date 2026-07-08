from __future__ import annotations

import pytest

from balise.ingestion import decp

VERNON_MARKETS = [
    {
        "id": "M001",
        "idacheteur": "21270681000019",
        "nomacheteur": "Mairie de Vernon",
        "objetmarche": "Entretien des espaces verts municipaux",
        "codecpv": "77300000-3",
        "montant": "85000",
        "datenotification": "2023-03-01",
        "siretetablissement": "12345678900011",
        "denominationsocialeetablissement": "Espaces Verts SAS",
    },
    {
        "id": "M004",
        "idacheteur": "21270681000019",
        "nomacheteur": "Mairie de Vernon",
        "objetmarche": "Fournitures de bureau",
        "codecpv": "30190000-7",
        "montant": "30000",
        "datenotification": "2023-04-01",
        "siretetablissement": "11122233300044",
        "denominationsocialeetablissement": "Bureau Plus",
    },
]

CPV_MARKETS = VERNON_MARKETS + [
    {
        "id": "M003",
        "idacheteur": "21271000000015",
        "nomacheteur": "Mairie d'Une Autre Commune",
        "objetmarche": "Entretien des espaces verts",
        "codecpv": "77300000-3",
        "montant": "60000",
        "datenotification": "2023-02-10",
        "siretetablissement": "55566677700033",
        "denominationsocialeetablissement": "Jardins Pro",
    },
]


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    def fake_fetch_records(base_url, dataset_id, where=None, **kwargs):
        calls.append(where)
        if where == 'startswith(idacheteur, "21270681000019")':
            return VERNON_MARKETS
        if where == 'startswith(codecpv, "77300000")':
            return CPV_MARKETS
        return []

    monkeypatch.setattr(decp, "fetch_records", fake_fetch_records)
    return calls


def test_get_markets_for_commune_filters_montant_minimum(fake_fetch, settings_with_tmp_cache):
    markets = decp.get_markets_for_commune("21270681000019", settings=settings_with_tmp_cache)

    ids = {m["id"] for m in markets}
    assert ids == {"M001"}
    assert markets[0]["titulaire_denomination"] == "Espaces Verts SAS"
    assert markets[0]["montant"] == pytest.approx(85_000.0)


def test_get_markets_for_commune_uses_cache(fake_fetch, settings_with_tmp_cache):
    decp.get_markets_for_commune("21270681000019", settings=settings_with_tmp_cache)
    decp.get_markets_for_commune("21270681000019", settings=settings_with_tmp_cache)

    assert len(fake_fetch) == 1


def test_get_comparable_markets_by_cpv(fake_fetch, settings_with_tmp_cache):
    markets = decp.get_comparable_markets("77300000", settings=settings_with_tmp_cache)

    ids = {m["id"] for m in markets}
    assert ids == {"M001", "M003"}


def test_describe_schema(fake_fetch, settings_with_tmp_cache):
    schema = decp.describe_schema("21270681000019", settings=settings_with_tmp_cache)

    assert "idacheteur" in schema["fields"]
    assert schema["sample_record"]["id"] == "M001"


def test_resolve_field_raises_with_available_fields():
    with pytest.raises(decp.DecpSchemaError) as excinfo:
        decp._resolve_field(["champ_inconnu_1", "champ_inconnu_2"], "montant")

    assert "champ_inconnu_1" in str(excinfo.value)
