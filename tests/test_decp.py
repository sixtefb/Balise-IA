from __future__ import annotations

import pytest

from balise.ingestion import decp

VERNON_MARKETS = [
    {
        "id": "M001",
        "acheteur_id": "21270681000019",
        "acheteur_nom": "Mairie de Vernon",
        "objet": "Entretien des espaces verts municipaux",
        "codeCPV": "77300000-3",
        "montant": "85000",
        "dateNotification": "2023-03-01",
        "titulaire_id_1": "12345678900011",
        "titulaire_denominationSociale_1": "Espaces Verts SAS",
    },
    {
        "id": "M004",
        "acheteur_id": "21270681000019",
        "acheteur_nom": "Mairie de Vernon",
        "objet": "Fournitures de bureau",
        "codeCPV": "30190000-7",
        "montant": "30000",
        "dateNotification": "2023-04-01",
        "titulaire_id_1": "11122233300044",
        "titulaire_denominationSociale_1": "Bureau Plus",
    },
]

CPV_MARKETS = VERNON_MARKETS + [
    {
        "id": "M003",
        "acheteur_id": "21271000000015",
        "acheteur_nom": "Mairie d'Une Autre Commune",
        "objet": "Entretien des espaces verts",
        "codeCPV": "77300000-3",
        "montant": "60000",
        "dateNotification": "2023-02-10",
        "titulaire_id_1": "55566677700033",
        "titulaire_denominationSociale_1": "Jardins Pro",
    },
]


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    def fake_fetch_records(base_url, dataset_id, where=None, **kwargs):
        calls.append(where)
        if where == 'acheteur_id like "21270681000019"':
            return VERNON_MARKETS
        if where == 'codeCPV like "77300000%"':
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

    assert "acheteur_id" in schema["fields"]
    assert schema["sample_record"]["id"] == "M001"


def test_resolve_field_raises_with_available_fields():
    with pytest.raises(decp.DecpSchemaError) as excinfo:
        decp._resolve_field(["champ_inconnu_1", "champ_inconnu_2"], "montant")

    assert "champ_inconnu_1" in str(excinfo.value)
