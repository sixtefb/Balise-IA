from __future__ import annotations

import pytest

from balise.ingestion import ofgl

VERNON_RECORDS = [
    {
        "insee": "27681",
        "siren": "212706810",
        "population": "23346",
        "dep_code": "27",
        "reg_code": "28",
        "exercice": "2023",
        "agregat": "Charges de fonctionnement",
        "montant": "18500000,50",
    },
    {
        "insee": "27681",
        "siren": "212706810",
        "population": "23346",
        "dep_code": "27",
        "reg_code": "28",
        "exercice": "2023",
        "agregat": "Charges de personnel",
        "montant": "9000000,00",
    },
    {
        "insee": "27681",
        "siren": "212706810",
        "population": "23346",
        "dep_code": "27",
        "reg_code": "28",
        "exercice": "2022",
        "agregat": "Charges de fonctionnement",
        "montant": "18000000,00",
    },
]

STRATE_RECORDS = VERNON_RECORDS + [
    {
        "insee": "27100",
        "siren": "210271000",
        "population": "22000",
        "dep_code": "27",
        "reg_code": "28",
        "exercice": "2023",
        "agregat": "Charges de fonctionnement",
        "montant": "17000000,00",
    },
    {
        "insee": "75056",
        "siren": "219750563",
        "population": "2100000",
        "dep_code": "75",
        "reg_code": "11",
        "exercice": "2023",
        "agregat": "Charges de fonctionnement",
        "montant": "5000000000,00",
    },
]


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    def fake_fetch_records(base_url, dataset_id, where=None, **kwargs):
        calls.append(where)
        if where == 'insee="27681"':
            return VERNON_RECORDS
        # Le where= du groupe de pairs est composite (budget principal +
        # agrégats connus + exercice) : on ne vérifie que le préfixe
        # correspondant à la strate demandée, pour ne pas dupliquer ici le
        # détail de sa construction (balise.ingestion.ofgl).
        if where and where.startswith('tranche_population="20000-49999"'):
            return STRATE_RECORDS
        return []

    monkeypatch.setattr(ofgl, "fetch_records", fake_fetch_records)
    return calls


def test_get_financial_data_filters_by_exercice(fake_fetch, settings_with_tmp_cache):
    data = ofgl.get_financial_data("27681", exercice=2023, settings=settings_with_tmp_cache)

    assert data["siren"] == "212706810"
    assert data["population"] == 23346.0
    assert data["code_departement"] == "27"
    assert data["charges_de_fonctionnement"] == pytest.approx(18_500_000.50)
    assert data["charges_de_personnel"] == pytest.approx(9_000_000.0)


def test_get_financial_data_uses_cache_on_second_call(fake_fetch, settings_with_tmp_cache):
    ofgl.get_financial_data("27681", exercice=2023, settings=settings_with_tmp_cache)
    ofgl.get_financial_data("27681", exercice=2023, settings=settings_with_tmp_cache)

    assert len(fake_fetch) == 1


def test_get_financial_data_not_found(fake_fetch, settings_with_tmp_cache):
    assert ofgl.get_financial_data("99999", exercice=2023, settings=settings_with_tmp_cache) is None


def test_get_peer_group_financial_data_filters_departement_client_side(fake_fetch, settings_with_tmp_cache):
    peers = ofgl.get_peer_group_financial_data(
        "20000-49999",
        exercice=2023,
        code_departement="27",
        exclude_code_insee="27681",
        settings=settings_with_tmp_cache,
    )

    codes = {p["code_insee"] for p in peers}
    assert codes == {"27100"}


def test_get_peer_group_financial_data_without_geo_filter_includes_all(fake_fetch, settings_with_tmp_cache):
    peers = ofgl.get_peer_group_financial_data("20000-49999", exercice=2023, settings=settings_with_tmp_cache)

    codes = {p["code_insee"] for p in peers}
    assert codes == {"27681", "27100", "75056"}


def test_describe_schema(fake_fetch, settings_with_tmp_cache):
    schema = ofgl.describe_schema("27681", settings=settings_with_tmp_cache)

    assert "agregat" in schema["fields"]
    assert "Charges de fonctionnement" in schema["agregat_distinct_values"]


def test_resolve_field_raises_with_available_fields():
    with pytest.raises(ofgl.OfglSchemaError) as excinfo:
        ofgl._resolve_field(["champ_inconnu_1", "champ_inconnu_2"], "code_insee")

    assert "champ_inconnu_1" in str(excinfo.value)
