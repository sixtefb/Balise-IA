"""Génération du rapport d'audit en PDF (téléchargeable depuis l'interface web).

Choix : `fpdf2`, pur Python, sans dépendance système (contrairement à une
conversion HTML->PDF via WeasyPrint, qui nécessite Pango/Cairo, absents de
l'environnement de déploiement actuel - voir la discussion produit). Les
graphiques (barres, histogrammes de distribution) sont dessinés directement
avec les primitives de dessin de `fpdf2` (rect/line), en reprenant la même
logique que les histogrammes SVG de `static/app.js`, pour rester cohérent
avec le rapport web plutôt que d'ajouter une seconde façon de représenter
les mêmes chiffres.

Ce module ne fait AUCUN calcul : il met en forme le dictionnaire produit par
`balise.pipeline.audit_to_dict`, chiffres inchangés.
"""

from __future__ import annotations

from datetime import date, datetime

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

# Palette reprise de static/index.html et static/app.js, pour une identité
# visuelle cohérente entre le rapport web et le PDF.
NAVY = (43, 58, 74)
CREAM = (242, 241, 236)
INK = (28, 29, 33)
BODY = (51, 53, 60)
MUTED = (138, 140, 148)
MUTED_DARK = (86, 88, 97)
BORDER = (226, 225, 219)
BORDER_LIGHT = (236, 234, 228)
WHITE = (255, 255, 255)

QUALIF_STYLE = {
    "alerte": {"text": "Alerte", "color": (143, 56, 38), "bg": (243, 226, 220), "bar": (165, 67, 47)},
    "a_surveiller": {"text": "À surveiller", "color": (146, 103, 26), "bg": (244, 236, 216), "bar": (169, 121, 31)},
    "conforme": {"text": "Conforme", "color": (86, 88, 97), "bg": (236, 234, 228), "bar": (86, 88, 97)},
    "efficient": {"text": "Efficient", "color": (47, 85, 64), "bg": (230, 239, 233), "bar": (47, 85, 64)},
    "donnee_absente": {"text": "Donnée indisponible", "color": (154, 155, 159), "bg": (236, 234, 228), "bar": (216, 215, 210)},
}

VERDICT_STYLE = {
    "Efficace": {"color": (47, 85, 64), "bg": (230, 239, 233)},
    "Vigilance": {"color": (146, 103, 26), "bg": (244, 236, 216)},
    "Alerte": {"color": (165, 67, 47), "bg": (243, 226, 220)},
}

PAGE_W = 210.0
MARGIN = 18.0
CONTENT_W = PAGE_W - 2 * MARGIN


def _fmt_eur(v: float | None) -> str:
    if v is None:
        return "n/d"
    return f"{round(v):,}".replace(",", " ") + " €"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/d"
    pct = round(v * 100)
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct)}%"


def _fmt_pop(v: float | None) -> str:
    if v is None:
        return "n/d"
    return f"{round(v):,}".replace(",", " ") + " hab."


def _fmt_short_date(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _format_freshness_line(freshness: dict | None) -> str | None:
    """Ligne de fraîcheur des données (mêmes libellés que static/app.js::buildFreshnessLine)."""
    if not freshness:
        return None
    parts = []
    if freshness.get("ofgl"):
        parts.append(f"comptes OFGL récupérés le {_fmt_short_date(freshness['ofgl'])}")
    if freshness.get("decp_marches"):
        parts.append(f"marchés DECP récupérés le {_fmt_short_date(freshness['decp_marches'])}")
    if freshness.get("decp_entretien"):
        parts.append(f'poste "Entretien" récupéré le {_fmt_short_date(freshness["decp_entretien"])}')
    if not parts:
        return None
    return "Fraîcheur des données - " + " . ".join(parts) + "."


class _ReportPDF(FPDF):
    def __init__(self, commune_nom: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        # cp1252 (Windows-1252) plutôt que le latin-1 par défaut : mêmes polices de
        # base (Helvetica/Courier, pas de fichier de police à embarquer), mais couvre
        # en plus le symbole euro (absent de latin-1), utilisé partout dans ce rapport.
        self.core_fonts_encoding = "cp1252"
        self._commune_nom = commune_nom
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(MARGIN, 16, MARGIN)
        self.alias_nb_pages()

    def normalize_text(self, text: str) -> str:
        # Certains libellés DECP contiennent des caractères mal encodés en amont
        # (source ouverte, pas de contrôle possible) qui n'ont pas d'équivalent
        # dans les polices de base du PDF (cp1252) : on les remplace par "?"
        # plutôt que de faire planter la génération. Aucune valeur numérique
        # n'est concernée, uniquement l'affichage de texte libre.
        try:
            return text.encode(self.core_fonts_encoding).decode("latin-1")
        except UnicodeEncodeError:
            return text.encode(self.core_fonts_encoding, errors="replace").decode("latin-1")

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*MUTED)
        self.set_y(8)
        self.cell(0, 5, "BALISE IA", new_x=XPos.LMARGIN, new_y=YPos.TOP)
        self.set_xy(-MARGIN - 80, 8)
        self.cell(80, 5, f"Rapport d'audit - {self._commune_nom}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*BORDER)
        self.set_line_width(0.2)
        self.line(MARGIN, 14, PAGE_W - MARGIN, 14)
        self.set_y(20)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, text: str, subtitle: str = "") -> None:
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(*INK)
        self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if subtitle:
            self.set_font("Helvetica", "", 9.5)
            self.set_text_color(*MUTED_DARK)
            self.multi_cell(CONTENT_W, 5, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def body_text(self, text: str, size: float = 10.5, color=BODY, leading: float = 5.6) -> None:
        self.set_font("Helvetica", "", size)
        self.set_text_color(*color)
        self.multi_cell(CONTENT_W, leading, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def badge(self, x: float, y: float, text: str, color, bg, w: float | None = None) -> float:
        self.set_font("Helvetica", "B", 8.5)
        text_w = self.get_string_width(text) + 6
        w = w or text_w
        self.set_fill_color(*bg)
        self.rect(x, y, w, 6, style="F")
        self.set_text_color(*color)
        self.set_xy(x, y + 0.9)
        self.cell(w, 4.2, text, align="C")
        return w


def generate_pdf(audit: dict, generated_on: date | None = None) -> bytes:
    """Rapport PDF complet (10 pages maximum) à partir du dict `audit_to_dict()`.

    Ne modifie ni ne filtre aucune valeur : reprend exactement les chiffres
    calculés par `balise.scoring`/`balise.pipeline`.
    """
    generated_on = generated_on or date.today()
    commune = audit["commune"]
    score = audit["score"]
    categories = audit["categories"]

    pdf = _ReportPDF(commune["nom"])
    _cover_page(pdf, audit, generated_on)
    _methodology_page(pdf, audit)
    _overview_page(pdf, audit)
    _weakness_pages(pdf, categories)
    if audit.get("marches_notables"):
        _markets_page(pdf, audit["marches_notables"])
    if audit.get("demographie") and audit["demographie"].get("brackets"):
        _demographie_page(pdf, audit["demographie"])
    _sources_page(pdf, audit)

    out = pdf.output()
    return bytes(out)


def _draw_note_box(pdf: _ReportPDF, text: str) -> None:
    """Encart d'avertissement (fond ambre) mesuré dynamiquement puis dessiné - voir
    _draw_weakness_block pour la même précaution sur le calcul de hauteur du bloc."""
    note_y = pdf.get_y() + 2
    qs = QUALIF_STYLE["a_surveiller"]
    pdf.set_font("Helvetica", "", 8.5)
    text_h = pdf.multi_cell(CONTENT_W - 8, 4, text, dry_run=True, output=MethodReturnValue.HEIGHT)
    note_h = text_h + 4
    pdf.set_fill_color(*qs["bg"])
    pdf.rect(MARGIN, note_y, CONTENT_W, note_h, style="F")
    pdf.set_xy(MARGIN + 4, note_y + 2)
    pdf.set_text_color(*qs["color"])
    pdf.multi_cell(CONTENT_W - 8, 4, text)
    pdf.set_y(note_y + note_h + 4)


def _cover_page(pdf: _ReportPDF, audit: dict, generated_on: date) -> None:
    commune = audit["commune"]
    score = audit["score"]
    vs = VERDICT_STYLE.get(score["verdict"], VERDICT_STYLE["Vigilance"])

    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, PAGE_W, 78, style="F")

    pdf.set_xy(MARGIN, 16)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*CREAM)
    pdf.cell(0, 6, "BALISE IA", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(0, 5, "Rapport d'audit budgétaire", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_xy(MARGIN, 34)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, commune["nom"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(210, 214, 220)
    cp_list = commune.get("codes_postaux") or []
    codes_postaux = ", ".join(cp_list[:5]) + (f" (+{len(cp_list) - 5})" if len(cp_list) > 5 else "") if cp_list else "n/d"
    pdf.cell(
        0, 6,
        f"{commune.get('departement', 'n/d')} ({commune.get('code_departement', '')}) - "
        f"{codes_postaux} - INSEE {commune['code_insee']}",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.set_x(MARGIN)
    pdf.cell(
        0, 6,
        f"Exercice {audit.get('exercice', 'n/d')} - généré le {generated_on.strftime('%d/%m/%Y')}",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )

    pdf.set_y(94)
    gauge_cx, gauge_cy, gauge_r = MARGIN + 24, 94 + 24, 24
    pdf.set_fill_color(*BORDER_LIGHT)
    pdf.ellipse(gauge_cx - gauge_r, gauge_cy - gauge_r, gauge_r * 2, gauge_r * 2, style="F")
    _draw_score_ring(pdf, gauge_cx, gauge_cy, gauge_r, score["global"], vs["color"])
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.set_xy(gauge_cx - gauge_r, gauge_cy - 6)
    pdf.cell(gauge_r * 2, 10, str(score["global"]), align="C")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(gauge_cx - gauge_r, gauge_cy + 3)
    pdf.cell(gauge_r * 2, 5, "/ 100", align="C")

    badge_x = gauge_cx + gauge_r + 12
    pdf.badge(badge_x, gauge_cy - 3, score["verdict"], vs["color"], vs["bg"], w=32)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED_DARK)
    pdf.set_xy(badge_x, gauge_cy + 5)
    peer_group_size = audit.get("peer_group_size", 0)
    subtitle = (
        f"vs {peer_group_size} commune(s) choisie(s)"
        if audit.get("custom_peer_group")
        else f"vs {peer_group_size} communes de la strate\n{audit.get('strate_label', '')}"
    )
    pdf.multi_cell(70, 4.8, subtitle)

    pdf.set_xy(MARGIN, 150)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.3)
    pdf.line(MARGIN, 148, PAGE_W - MARGIN, 148)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    pdf.set_xy(MARGIN, 154)
    pdf.cell(0, 6, "En résumé", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(MARGIN)
    pdf.body_text(_build_synthese(audit), size=11, leading=6.2)

    active_note = audit.get("custom_compare_note") or audit.get("peer_group_note")
    if active_note:
        _draw_note_box(pdf, active_note)
    if audit.get("context_note"):
        _draw_note_box(pdf, audit["context_note"])

    vigilance = [c for c in audit["categories"] if c["qualification"] in ("alerte", "a_surveiller")]
    efficient = [c for c in audit["categories"] if c["qualification"] == "efficient"]
    y = pdf.get_y() + 6
    col_w = (CONTENT_W - 8) / 2
    _mini_list(pdf, MARGIN, y, col_w, "Points de vigilance", vigilance, QUALIF_STYLE["alerte"]["color"])
    _mini_list(pdf, MARGIN + col_w + 8, y, col_w, "Points forts", efficient, QUALIF_STYLE["efficient"]["color"])


def _mini_list(pdf: _ReportPDF, x: float, y: float, w: float, title: str, items: list[dict], color) -> None:
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(*color)
    pdf.cell(w, 5, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*BODY)
    if not items:
        pdf.set_x(x)
        pdf.multi_cell(w, 4.8, "Aucun poste concerné.")
        return
    for item in items[:4]:
        pdf.set_x(x)
        pdf.multi_cell(w, 4.8, f"- {item['label']} ({_fmt_pct(item['delta_pct'])})")


def _draw_score_ring(pdf: _ReportPDF, cx: float, cy: float, r: float, score: int, color, steps: int = 90) -> None:
    """Anneau de progression 0-100 dessiné comme une succession de segments (fpdf2 n'a pas d'arc natif)."""
    import math

    pdf.set_draw_color(*color)
    pdf.set_line_width(3.2)
    n_segments = round(steps * score / 100)
    for i in range(n_segments):
        a0 = -math.pi / 2 + (i / steps) * 2 * math.pi
        a1 = -math.pi / 2 + ((i + 1) / steps) * 2 * math.pi
        inner = r - 1.6
        x0, y0 = cx + inner * math.cos(a0), cy + inner * math.sin(a0)
        x1, y1 = cx + inner * math.cos(a1), cy + inner * math.sin(a1)
        pdf.line(x0, y0, x1, y1)


def _build_synthese(audit: dict) -> str:
    score = audit["score"]
    categories = audit["categories"]
    vigilance = [c for c in categories if c["qualification"] in ("alerte", "a_surveiller")]
    efficient = [c for c in categories if c["qualification"] == "efficient"]

    peer_group_size = audit.get("peer_group_size", 0)
    group_desc = (
        f"des {peer_group_size} commune(s) choisie(s)"
        if audit.get("custom_peer_group")
        else f"des {peer_group_size} communes de sa strate démographique"
    )
    text = (
        f"La commune présente un indice d'efficacité budgétaire de {score['global']}/100 "
        f"({score['verdict'].lower()}) vis-à-vis {group_desc}."
    )
    if vigilance:
        labels = ", ".join(c["label"].lower() for c in vigilance)
        text += f" Les écarts se concentrent sur {labels}, au-dessus de la médiane du groupe."
    if efficient:
        labels = ", ".join(c["label"].lower() for c in efficient)
        text += f" À l'inverse, {labels} apparaissent maîtrisés."
    return text


def _methodology_page(pdf: _ReportPDF, audit: dict) -> None:
    pdf.add_page()
    pdf.section_title("Comment ce score est calculé")
    if audit.get("custom_peer_group"):
        pdf.body_text(
            "Pour chaque poste de dépense, Balise IA compare la commune au groupe de "
            f"{audit.get('peer_group_size', 0)} commune(s) choisie(s) manuellement pour ce rapport, "
            "à la place du groupe automatique par strate démographique. La comparaison se fait en "
            "euros par habitant, pour que la taille de la commune n'influence pas l'écart mesuré."
        )
    else:
        pdf.body_text(
            "Pour chaque poste de dépense, Balise IA compare la commune à un groupe de "
            f"{audit.get('peer_group_size', 0)} communes de même strate démographique "
            f"({audit.get('strate_label', 'n/d')}), à l'échelle nationale. La comparaison se fait en "
            "euros par habitant, pour que la taille de la commune n'influence pas l'écart mesuré."
        )
    pdf.ln(2)
    pdf.body_text(
        "L'écart est résumé par un z-score : le nombre d'écarts-types séparant la commune de la "
        "moyenne de son groupe de comparaison. Un z-score de 0 signifie une dépense dans la moyenne "
        "du groupe ; un z-score positif signifie une dépense supérieure à la moyenne du groupe."
    )
    pdf.ln(2)
    pdf.body_text(
        "Chaque poste reçoit ensuite une note sur 100 (50 = dépense moyenne du groupe, note qui "
        "diminue quand la dépense s'écarte au-dessus de la moyenne). Le score global est la moyenne "
        "des notes obtenues sur les 7 postes."
    )
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Seuils de qualification par poste", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    rows = [
        ("Efficient", "z-score <= -1", QUALIF_STYLE["efficient"]["color"]),
        ("Conforme", "-1 < z-score < 1", QUALIF_STYLE["conforme"]["color"]),
        ("À surveiller", "1 <= z-score < 2", QUALIF_STYLE["a_surveiller"]["color"]),
        ("Alerte", "z-score >= 2", QUALIF_STYLE["alerte"]["color"]),
    ]
    for label, rule, color in rows:
        y = pdf.get_y()
        pdf.badge(MARGIN, y, label, color, tuple(min(255, c + 20) for c in color), w=34)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*BODY)
        pdf.set_xy(MARGIN + 38, y + 0.5)
        pdf.cell(0, 5, rule, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_y(y + 8)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Verdict global", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.body_text(
        "Alerte : score global < 45  -  Vigilance : entre 45 et 69  -  Efficace : score global >= 70.",
        size=9.5,
    )

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "D'où viennent les données", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    sources = [
        ("Identité de la commune", "geo.api.gouv.fr (INSEE, Code Officiel Géographique)"),
        ("6 postes de dépense (fonctionnement, personnel, achats, équipement, dette, subventions)", "data.ofgl.fr - comptes individuels des communes (DGFiP/OFGL)"),
        ("Entretien (voirie, espaces verts, bâtiments)", "data.economie.gouv.fr - marchés publics DECP, reconstruit faute de ligne dédiée dans OFGL"),
        ("Démographie (contexte, hors score)", "api.insee.fr - recensement de la population"),
    ]
    for label, source in sources:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(CONTENT_W, 4.6, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED_DARK)
        pdf.multi_cell(CONTENT_W, 4.6, source, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.5)

    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        CONTENT_W, 4.6,
        "Ces écarts statistiques ne constituent pas, en eux-mêmes, la preuve d'une malversation : "
        "ce sont des pistes de vérification.",
    )


def _overview_page(pdf: _ReportPDF, audit: dict) -> None:
    categories = audit["categories"]
    pdf.add_page()
    pdf.section_title(
        "Vue d'ensemble des 7 postes de dépense",
        "Écart de la commune par rapport à la médiane de son groupe de pairs, en €/habitant.",
    )

    max_abs_delta = max((abs(c["delta_pct"] or 0) for c in categories), default=0.01) or 0.01
    row_h = 23
    for c in categories:
        y = pdf.get_y()
        if y + row_h > 270:
            pdf.add_page()
            y = pdf.get_y()
        _draw_delta_row(pdf, MARGIN, y, CONTENT_W, c, max_abs_delta)
        pdf.set_y(y + row_h)


def _draw_delta_row(pdf: _ReportPDF, x: float, y: float, w: float, cat: dict, max_abs_delta: float) -> None:
    qs = QUALIF_STYLE.get(cat["qualification"], QUALIF_STYLE["conforme"])

    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(*INK)
    pdf.set_xy(x, y)
    pdf.cell(w - 60, 5, cat["label"], new_x=XPos.LMARGIN, new_y=YPos.TOP)
    pdf.badge(x + w - 58, y - 0.5, qs["text"], qs["color"], qs["bg"], w=34)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED_DARK)
    pdf.set_xy(x + w - 24, y - 0.5)
    pdf.cell(24, 6, _fmt_pct(cat["delta_pct"]), align="R")

    bar_y = y + 8
    bar_h = 5
    mid_x = x + w / 2
    half_w = w / 2 - 2
    pdf.set_fill_color(*BORDER_LIGHT)
    pdf.rect(x, bar_y, w, bar_h, style="F")
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.3)
    pdf.line(mid_x, bar_y - 1, mid_x, bar_y + bar_h + 1)

    delta = cat["delta_pct"]
    if delta is not None:
        frac = max(-1.0, min(1.0, delta / max_abs_delta))
        bar_w = abs(frac) * half_w
        bx = mid_x if frac >= 0 else mid_x - bar_w
        pdf.set_fill_color(*qs["bar"])
        pdf.rect(bx, bar_y, bar_w, bar_h, style="F")

    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(x, bar_y + 5.5)
    pdf.cell(w / 2, 4, f"commune : {_fmt_eur(cat['commune_par_habitant'])}/hab", align="L")
    pdf.set_xy(x + w / 2, bar_y + 5.5)
    pdf.cell(w / 2, 4, f"médiane groupe : {_fmt_eur(cat['peer_median_par_habitant'])}/hab", align="R")


def _weakness_pages(pdf: _ReportPDF, categories: list[dict]) -> None:
    weak = sorted(
        [c for c in categories if c["qualification"] in ("alerte", "a_surveiller")],
        key=lambda c: -(c["delta_pct"] or 0),
    )
    if not weak:
        pdf.add_page()
        pdf.section_title("Analyse détaillée par poste")
        pdf.body_text(
            "Aucun poste de dépense n'est actuellement qualifié « à surveiller » ou "
            "« alerte » pour cette commune : tous les postes comparés sont dans la "
            "moyenne ou en dessous de la médiane de leur groupe de pairs."
        )
        return

    weak = weak[:4]
    pdf.add_page()
    pdf.section_title(
        "Analyse détaillée des points de vigilance",
        "Position de la commune dans la distribution des communes comparées, poste par poste.",
    )
    for i, cat in enumerate(weak):
        if pdf.get_y() + 78 > 268:
            pdf.add_page()
        _draw_weakness_block(pdf, cat)
        pdf.ln(6)


def _draw_weakness_block(pdf: _ReportPDF, cat: dict) -> None:
    qs = QUALIF_STYLE.get(cat["qualification"], QUALIF_STYLE["alerte"])
    y0 = pdf.get_y()
    pdf.set_font("Helvetica", "B", 11.5)
    pdf.set_text_color(*INK)
    pdf.set_xy(MARGIN, y0)
    pdf.cell(CONTENT_W - 40, 6, cat["label"], new_x=XPos.LMARGIN, new_y=YPos.TOP)
    pdf.badge(MARGIN + CONTENT_W - 38, y0, qs["text"], qs["color"], qs["bg"], w=38)
    pdf.set_y(y0 + 8)

    is_maintenance = cat["key"] == "entretien"
    if is_maintenance:
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(
            CONTENT_W, 4.2,
            "Source différente des autres postes : cumul des marchés publics DECP notifiés "
            "(voirie, espaces verts, bâtiments, nettoyage), pas une dépense annuelle OFGL.",
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        pdf.ln(1)

    pdf.set_font("Courier", "", 8.5)
    pdf.set_text_color(*MUTED_DARK)
    pdf.cell(CONTENT_W / 3, 4.5, f"médiane groupe : {_fmt_eur(cat['peer_median_par_habitant'])}/hab")
    pdf.set_font("Courier", "B", 8.5)
    pdf.set_text_color(*qs["color"])
    pdf.cell(CONTENT_W / 3, 4.5, f"cette commune : {_fmt_eur(cat['commune_par_habitant'])}/hab")
    pdf.set_font("Courier", "", 8.5)
    pdf.set_text_color(*MUTED_DARK)
    pdf.cell(CONTENT_W / 3, 4.5, f"{cat['peer_count']} communes comparées", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)

    histogram_h = 22
    _draw_histogram(pdf, MARGIN, pdf.get_y(), CONTENT_W, histogram_h, cat["peer_values"], cat["commune_par_habitant"], qs["bar"])
    pdf.set_y(pdf.get_y() + histogram_h + 3)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*BODY)
    pdf.multi_cell(
        CONTENT_W, 4.8,
        f"Écart de {_fmt_pct(cat['delta_pct'])} par rapport à la médiane de son groupe de pairs. "
        "Cet écart statistique n'est pas en lui-même la preuve d'un problème : c'est une piste à "
        "vérifier (marché surdimensionné, prestation exceptionnelle sur l'exercice, retard de "
        "publication des comptes...).",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )


def _draw_histogram(pdf: _ReportPDF, x: float, y: float, w: float, h: float, peer_values, commune_value, color, bins: int = 16) -> None:
    values = [v for v in (peer_values or []) if v is not None]
    pdf.set_fill_color(*BORDER_LIGHT)
    pdf.rect(x, y, w, h, style="F")
    if len(values) < 2:
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(x, y + h / 2 - 2)
        pdf.cell(w, 4, "Distribution indisponible.", align="C")
        return

    lo, hi = min(values), max(values)
    if commune_value is not None:
        lo, hi = min(lo, commune_value), max(hi, commune_value)
    span = (hi - lo) or 1.0
    lo -= span * 0.05
    hi += span * 0.05
    span = hi - lo

    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / span * bins))
        counts[idx] += 1
    max_count = max(counts) or 1

    bar_w = w / bins
    pdf.set_draw_color(*BORDER)
    for i, count in enumerate(counts):
        bar_h = (count / max_count) * (h - 4)
        bx = x + i * bar_w
        by = y + h - bar_h
        pdf.set_fill_color(216, 215, 210)
        pdf.rect(bx + 0.3, by, max(0.1, bar_w - 0.6), bar_h, style="F")

    if commune_value is not None:
        marker_x = x + (commune_value - lo) / span * w
        marker_x = max(x, min(x + w, marker_x))
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.8)
        pdf.line(marker_x, y, marker_x, y + h)


def _truncate_to_width(pdf: _ReportPDF, text: str, max_w: float) -> str:
    """Tronque `text` (police déjà sélectionnée) pour tenir dans `max_w` mm, avec '...'."""
    if pdf.get_string_width(text) <= max_w:
        return text
    ellipsis = "..."
    while text and pdf.get_string_width(text + ellipsis) > max_w:
        text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis


def _markets_page(pdf: _ReportPDF, marches: list[dict]) -> None:
    pdf.add_page()
    pdf.section_title(
        "Marchés publics notables",
        "Marchés les plus importants notifiés par la commune (source : DECP, data.economie.gouv.fr).",
    )
    for m in marches[:10]:
        outlier = bool(m.get("montant_exceptionnel"))
        card_h = 27 if outlier else 20
        if pdf.get_y() + card_h + 2 > 268:
            pdf.add_page()
        y = pdf.get_y()
        border_color = QUALIF_STYLE["alerte"]["bar"] if outlier else BORDER
        pdf.set_draw_color(*border_color)
        pdf.set_line_width(0.4 if outlier else 0.2)
        pdf.rect(MARGIN, y, CONTENT_W, card_h, style="D")

        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*INK)
        lots = f"  ({m['lot_count']} lots)" if (m.get("lot_count") or 1) > 1 else ""
        objet = _truncate_to_width(pdf, (m.get("objet") or "Marché sans objet renseigné") + lots, CONTENT_W - 6)
        pdf.set_xy(MARGIN + 3, y + 2.5)
        pdf.cell(CONTENT_W - 6, 4.5, objet)

        montant_w = 37
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*(QUALIF_STYLE["alerte"]["color"] if outlier else INK))
        pdf.set_xy(MARGIN + CONTENT_W - montant_w - 2, y + 8)
        pdf.cell(montant_w, 4.5, _fmt_eur(m.get("montant")), align="R")

        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*MUTED_DARK)
        titulaires_w = CONTENT_W - montant_w - 8
        titulaires = _truncate_to_width(
            pdf, ", ".join(m.get("titulaires") or []) or "Titulaire non renseigné", titulaires_w
        )
        pdf.set_xy(MARGIN + 3, y + 8.5)
        pdf.cell(titulaires_w, 4, titulaires)

        ref_line = " · ".join(
            filter(None, [f"Réf. {m['reference']}" if m.get("reference") else None, m.get("date_notification")])
        )
        pdf.set_font("Courier", "", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(MARGIN + 3, y + 13.5)
        pdf.cell(CONTENT_W - 6, 4, _truncate_to_width(pdf, ref_line, CONTENT_W - 6))

        if outlier:
            qs = QUALIF_STYLE["alerte"]
            pdf.set_fill_color(*qs["bg"])
            pdf.rect(MARGIN + 2, y + 18.5, CONTENT_W - 4, 6.5, style="F")
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*qs["color"])
            pdf.set_xy(MARGIN + 4, y + 19.7)
            pdf.cell(
                CONTENT_W - 8, 4,
                _truncate_to_width(
                    pdf,
                    "Montant exceptionnel - supérieur au budget de fonctionnement annuel de la commune, "
                    "probablement une anomalie de saisie de la source, à vérifier.",
                    CONTENT_W - 8,
                ),
            )

        pdf.set_y(y + card_h + 2)


def _demographie_page(pdf: _ReportPDF, demographie: dict) -> None:
    pdf.add_page()
    pdf.section_title(
        "Démographie (contexte, hors score)",
        f"Recensement {demographie.get('millesime', 'n/d')} - informatif uniquement : une population plus "
        "âgée ou plus jeune n'est ni un point fort ni un point de vigilance en soi, ça explique certains "
        "écarts de dépense (social, scolaire...).",
    )
    brackets = demographie.get("brackets") or []
    total = demographie.get("population_totale") or 1
    max_pop = max((b["population"] for b in brackets), default=1) or 1

    row_h = 9
    label_w = 42
    value_w = 46
    bar_w = CONTENT_W - label_w - value_w
    for b in brackets:
        y = pdf.get_y()
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*BODY)
        pdf.set_xy(MARGIN, y + 1.5)
        pdf.cell(label_w, 5, b["label"])

        pdf.set_fill_color(*BORDER_LIGHT)
        pdf.rect(MARGIN + label_w, y + 1, bar_w, 5.5, style="F")
        width = (b["population"] / max_pop) * bar_w
        pdf.set_fill_color(*NAVY)
        pdf.rect(MARGIN + label_w, y + 1, width, 5.5, style="F")

        pct = (b["population"] / total) * 100
        pdf.set_font("Courier", "", 8.5)
        pdf.set_text_color(*MUTED_DARK)
        pdf.set_xy(MARGIN + label_w + bar_w + 2, y + 1.5)
        pdf.cell(value_w - 2, 5, f"{_fmt_pop(b['population'])} ({pct:.0f}%)", align="R")

        pdf.set_y(y + row_h)


def _sources_page(pdf: _ReportPDF, audit: dict) -> None:
    pdf.add_page()
    pdf.section_title("Sources, limites et avertissement")
    pdf.body_text(
        "Ce rapport est généré automatiquement à partir de données publiques ouvertes (open data), "
        "sans intervention manuelle sur les valeurs. Aucun plafond ni filtre n'est appliqué aux montants "
        "publiés par les sources : les chiffres affichés sont ceux communiqués par les administrations."
    )
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Limites méthodologiques", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    limites = [
        "Le poste « Entretien » est reconstruit depuis les marchés publics notifiés (DECP) et "
        "n'est pas une dépense annuelle comme les 6 autres postes : c'est un cumul de marchés, comparable "
        "entre communes mais pas à lire comme un budget annuel.",
        "Un écart statistique par rapport au groupe de pairs n'est pas, en lui-même, la preuve d'une "
        "malversation ou d'une mauvaise gestion : c'est une piste de vérification (contexte local, "
        "investissement exceptionnel, retard de publication des comptes...).",
        "Dépenser moins que le groupe de comparaison est ici lu comme « efficient » : cette lecture "
        "ne distingue pas un sous-investissement (ex. dépenses d'équipement trop faibles) d'une réelle "
        "maîtrise budgétaire.",
        "Les comptes OFGL démarrent en général en 2014-2017 et s'arrêtent 1 à 2 ans avant l'année en cours "
        "(délai de publication des comptes administratifs).",
    ]
    if audit.get("decp_coverage_note"):
        limites.append(audit["decp_coverage_note"])
    for l in limites:
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*BODY)
        pdf.multi_cell(CONTENT_W, 4.8, f"- {l}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.5)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Sources", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.body_text(
        "Comptes individuels des communes (DGFiP/OFGL) - data.ofgl.fr\n"
        "Marchés publics (DECP) - data.economie.gouv.fr\n"
        "Référentiel administratif et démographie - geo.api.gouv.fr, api.insee.fr (INSEE)",
        size=9.5,
    )

    freshness_line = _format_freshness_line(audit.get("data_freshness"))
    if freshness_line:
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*MUTED_DARK)
        pdf.multi_cell(CONTENT_W, 4.4, freshness_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(6)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.3)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        CONTENT_W, 4.4,
        f"Généré par Balise IA - {audit['commune']['nom']} ({audit['commune']['code_insee']}) - "
        f"exercice {audit.get('exercice', 'n/d')}.",
    )
