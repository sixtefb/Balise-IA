from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from balise.report.pdf import generate_pdf

CATEGORY_TEMPLATE = {
    "peer_count": 20,
    "peer_values": [100.0 + i * 5 for i in range(20)],
}


def _category(key, label, qualification, delta_pct, commune_value=150.0, peer_median=140.0):
    return {
        **CATEGORY_TEMPLATE,
        "key": key,
        "label": label,
        "commune_par_habitant": commune_value,
        "peer_median_par_habitant": peer_median,
        "delta_pct": delta_pct,
        "qualification": qualification,
    }


def _audit(
    categories=None,
    marches_notables=None,
    demographie=None,
    peer_group_note=None,
    decp_coverage_note=None,
    data_freshness=None,
    custom_peer_group=False,
    custom_compare_note=None,
    context_note=None,
):
    return {
        "commune": {
            "nom": "Testville",
            "code_insee": "99999",
            "siren": "123456789",
            "codes_postaux": ["99000"],
            "population": 12345,
            "departement": "Test",
            "code_departement": "99",
            "region": "Testrégion",
            "code_region": "00",
            "epci": None,
        },
        "exercice": 2023,
        "strate_label": "groupe personnalisé" if custom_peer_group else "10 000 à 19 999 habitants",
        "peer_group_size": 20,
        "peer_group_note": peer_group_note,
        "context_note": context_note,
        "custom_peer_group": custom_peer_group,
        "custom_compare_note": custom_compare_note,
        "score": {"global": 62, "verdict": "Vigilance"},
        "categories": categories if categories is not None else [
            _category("charges_de_fonctionnement", "Charges de fonctionnement", "conforme", 0.02),
            _category("charges_de_personnel", "Charges de personnel", "efficient", -0.15),
            _category("achats_et_charges_externes", "Achats et charges externes", "a_surveiller", 0.35),
            _category("depenses_d_equipement", "Dépenses d'équipement", "alerte", 0.9),
            _category("encours_de_dette", "Encours de la dette", "donnee_absente", None, None, 500.0),
            _category("subventions_associations", "Subventions aux associations", "conforme", 0.01),
            _category("entretien", "Entretien (voirie, espaces verts, bâtiments)", "alerte", 0.6),
        ],
        "peer_communes": [],
        "marches_notables": marches_notables if marches_notables is not None else [
            {
                "reference": "2023/001",
                "objet": "Rénovation de la voirie centrale",
                "montant": 1_250_000.0,
                "lot_count": 2,
                "date_notification": "2023-04-01",
                "titulaires": ["Entreprise Dupont", "Entreprise Martin"],
            },
        ],
        "decp_coverage_note": decp_coverage_note,
        "demographie": demographie if demographie is not None else {
            "millesime": 2021,
            "population_totale": 12345,
            "brackets": [
                {"label": "0-14 ans", "population": 2000},
                {"label": "15-24 ans", "population": 1500},
                {"label": "65-79 ans", "population": 1800},
            ],
        },
        "generated_at": "2024-01-01T00:00:00+00:00",
        "data_freshness": data_freshness if data_freshness is not None else {
            "ofgl": "2024-01-01T10:00:00+00:00",
            "decp_marches": "2023-12-15T08:30:00+00:00",
            "decp_entretien": "2023-11-01T00:00:00+00:00",
        },
    }


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(BytesIO(pdf_bytes)).pages)


def test_generate_pdf_returns_valid_pdf_bytes():
    pdf_bytes = generate_pdf(_audit(), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_pdf_stays_within_ten_pages():
    assert _page_count(generate_pdf(_audit(), generated_on=date(2024, 1, 1))) <= 10


def test_generate_pdf_includes_commune_name_and_score():
    pdf_bytes = generate_pdf(_audit(), generated_on=date(2024, 1, 1))
    text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)
    assert "Testville" in text
    assert "62" in text


def test_generate_pdf_without_weak_categories():
    categories = [
        _category("charges_de_fonctionnement", "Charges de fonctionnement", "conforme", 0.0),
        _category("charges_de_personnel", "Charges de personnel", "efficient", -0.2),
    ]
    pdf_bytes = generate_pdf(_audit(categories=categories), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_pdf_without_marches_or_demographie():
    pdf_bytes = generate_pdf(
        _audit(marches_notables=[], demographie=None), generated_on=date(2024, 1, 1)
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert _page_count(pdf_bytes) <= 10


def test_generate_pdf_handles_many_weak_categories_and_long_labels():
    categories = [
        _category(f"poste_{i}", f"Poste de dépense numéro {i} avec un intitulé assez long", "alerte", 1.5 + i * 0.1)
        for i in range(7)
    ]
    pdf_bytes = generate_pdf(_audit(categories=categories), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")
    assert _page_count(pdf_bytes) <= 10


def test_generate_pdf_sanitizes_unencodable_characters():
    marches = [
        {
            "reference": "2023/999",
            "objet": "Marché avec caractère invalide � dans l'objet",
            "montant": 999_999.0,
            "lot_count": 1,
            "date_notification": "2023-05-01",
            "titulaires": ["Titulaire � invalide"],
        }
    ]
    pdf_bytes = generate_pdf(_audit(marches_notables=marches), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_pdf_truncates_long_market_object_without_overlap():
    marches = [
        {
            "reference": "2023/002",
            "objet": "X" * 300,
            "montant": 42.0,
            "lot_count": 1,
            "date_notification": "2023-01-01",
            "titulaires": ["Y" * 300],
        }
    ]
    pdf_bytes = generate_pdf(_audit(marches_notables=marches), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_pdf_shows_peer_group_note_on_cover():
    note = "Cette commune est nettement plus grande... interpréter avec prudence."
    pdf_bytes = generate_pdf(_audit(peer_group_note=note), generated_on=date(2024, 1, 1))
    text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text() or ""
    assert "interpréter avec prudence" in text


def test_generate_pdf_without_peer_group_note_stays_valid():
    pdf_bytes = generate_pdf(_audit(peer_group_note=None), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_pdf_shows_decp_coverage_note_on_sources_page():
    note = "Seulement 1 marché(s) public(s) trouvé(s) dans les données DECP pour cette commune."
    pdf_bytes = generate_pdf(_audit(decp_coverage_note=note), generated_on=date(2024, 1, 1))
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "marché(s) public(s) trouvé" in full_text


def test_generate_pdf_shows_data_freshness_on_sources_page():
    pdf_bytes = generate_pdf(_audit(), generated_on=date(2024, 1, 1))
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "Fraîcheur des données" in full_text
    assert "01/01/2024" in full_text


def test_generate_pdf_without_data_freshness_stays_valid():
    pdf_bytes = generate_pdf(_audit(data_freshness={}), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "Fraîcheur des données" not in full_text


def test_generate_pdf_flags_outlier_market():
    marches = [
        {
            "reference": "2023/003",
            "objet": "Maintenance équipements hospitaliers",
            "montant": 99_999_997_952.0,
            "lot_count": 1,
            "date_notification": "2023-06-01",
            "titulaires": ["Fournisseur X"],
            "montant_exceptionnel": True,
        },
    ]
    pdf_bytes = generate_pdf(_audit(marches_notables=marches), generated_on=date(2024, 1, 1))
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "Montant exceptionnel" in full_text
    # Le montant affiché reste celui de la source, jamais plafonné/modifié.
    assert "99" in full_text and "997" in full_text and "952" in full_text


def test_generate_pdf_no_flag_for_normal_market():
    marches = [
        {
            "reference": "2023/004",
            "objet": "Marché normal",
            "montant": 50_000.0,
            "lot_count": 1,
            "date_notification": "2023-06-01",
            "titulaires": ["Fournisseur Y"],
            "montant_exceptionnel": False,
        },
    ]
    pdf_bytes = generate_pdf(_audit(marches_notables=marches), generated_on=date(2024, 1, 1))
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "Montant exceptionnel" not in full_text


def test_generate_pdf_shows_custom_compare_note_instead_of_peer_group_note():
    note = "Comparaison à 2 commune(s) choisie(s) manuellement, au lieu du groupe automatique."
    pdf_bytes = generate_pdf(
        _audit(custom_peer_group=True, custom_compare_note=note, peer_group_note="devrait être ignoré"),
        generated_on=date(2024, 1, 1),
    )
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "Comparaison à 2 commune(s) choisie(s) manuellement" in full_text
    assert "devrait être ignoré" not in full_text


def test_generate_pdf_custom_peer_group_methodology_text():
    pdf_bytes = generate_pdf(_audit(custom_peer_group=True), generated_on=date(2024, 1, 1))
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "choisie" in full_text and "manuellement" in full_text
    assert "strate démographique (" not in full_text


def test_generate_pdf_shows_context_note_alongside_peer_group_note():
    context = "Contexte à prendre en compte pour interpréter les écarts : commune touristique."
    pdf_bytes = generate_pdf(
        _audit(peer_group_note="Comparaison resserrée aux communes proches en population.", context_note=context),
        generated_on=date(2024, 1, 1),
    )
    pages = PdfReader(BytesIO(pdf_bytes)).pages
    full_text = "".join(p.extract_text() or "" for p in pages)
    assert "resserrée aux communes proches" in full_text
    assert "commune touristique" in full_text


def test_generate_pdf_without_context_note_stays_valid():
    pdf_bytes = generate_pdf(_audit(context_note=None), generated_on=date(2024, 1, 1))
    assert pdf_bytes.startswith(b"%PDF")
