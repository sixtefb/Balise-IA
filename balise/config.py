"""Paramètres configurables de Balise IA.

Toutes les valeurs susceptibles d'influencer un résultat métier (seuils de
score, bornes de strates démographiques, tailles minimales de groupe de
comparaison, TTL de cache...) sont centralisées ici plutôt que codées en dur
dans les modules d'ingestion, de scoring ou de rapport.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Surchargeable via la variable d'environnement BALISE_CACHE_DIR (utile en
# déploiement, ex. Render, pour pointer vers un disque persistant monté à un
# chemin qui ne correspond pas forcément à PROJECT_ROOT/data/cache).
_cache_dir_override = os.environ.get("BALISE_CACHE_DIR")
DEFAULT_CACHE_DB_PATH = (
    Path(_cache_dir_override) / "balise.duckdb"
    if _cache_dir_override
    else PROJECT_ROOT / "data" / "cache" / "balise.duckdb"
)


@dataclass(frozen=True)
class StrateThreshold:
    """Une tranche de strate démographique (bornes inclusives, max=None = pas de plafond)."""

    label: str
    population_min: int
    population_max: int | None


# Bornes usuelles des strates démographiques utilisées pour les comparaisons
# de finances locales (DGCL/OFGL). À aligner/recaler une fois le jeu de
# données OFGL intégré, si ses libellés de strates diffèrent.
DEFAULT_STRATES: tuple[StrateThreshold, ...] = (
    StrateThreshold("0 à 249 habitants", 0, 249),
    StrateThreshold("250 à 499 habitants", 250, 499),
    StrateThreshold("500 à 999 habitants", 500, 999),
    StrateThreshold("1 000 à 1 999 habitants", 1_000, 1_999),
    StrateThreshold("2 000 à 3 499 habitants", 2_000, 3_499),
    StrateThreshold("3 500 à 4 999 habitants", 3_500, 4_999),
    StrateThreshold("5 000 à 9 999 habitants", 5_000, 9_999),
    StrateThreshold("10 000 à 19 999 habitants", 10_000, 19_999),
    StrateThreshold("20 000 à 49 999 habitants", 20_000, 49_999),
    StrateThreshold("50 000 à 99 999 habitants", 50_000, 99_999),
    StrateThreshold("100 000 à 199 999 habitants", 100_000, 199_999),
    StrateThreshold("200 000 habitants et plus", 200_000, None),
)


@dataclass(frozen=True)
class ScoringThresholds:
    """Seuils utilisés pour qualifier un écart (module de scoring, étapes suivantes)."""

    watch_abs_zscore: float = 1.0
    alert_abs_zscore: float = 2.0
    min_peer_group_size: int = 15
    target_peer_group_size: int = 20
    # La strate OFGL la plus haute ("100 000 habitants et plus") est ouverte :
    # elle mélange une ville de 100 000 habitants et Paris (2,1M). Si la
    # commune auditée s'écarte de plus de ce facteur de la population
    # médiane de son groupe de pairs, on resserre la comparaison aux
    # communes d'ordre de grandeur comparable (voir
    # balise.scoring._narrow_peer_group_by_population).
    peer_population_ratio_window: float = 3.0


@dataclass(frozen=True)
class InseeApiSettings:
    """Paramètres d'accès à l'API Découpage administratif (geo.api.gouv.fr)."""

    base_url: str = "https://geo.api.gouv.fr"
    request_timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0


@dataclass(frozen=True)
class SpendingItem:
    """Un poste de dépense comparé entre communes (couche normalisation/scoring)."""

    key: str
    label: str


# Postes de dépense comparés, dérivés des agrégats OFGL. `key` est le nom
# canonique utilisé dans tout le code ; `label` est le libellé affiché dans
# le rapport. Modifier cette liste ne nécessite aucun changement de code
# ailleurs (scoring et rapport itèrent dessus).
DEFAULT_SPENDING_ITEMS: tuple[SpendingItem, ...] = (
    SpendingItem("charges_de_fonctionnement", "Charges de fonctionnement"),
    SpendingItem("charges_de_personnel", "Charges de personnel"),
    SpendingItem("achats_et_charges_externes", "Achats et charges externes"),
    SpendingItem("depenses_d_equipement", "Dépenses d'équipement"),
    SpendingItem("encours_de_dette", "Encours de la dette"),
    SpendingItem("subventions_associations", "Subventions aux associations"),
)


@dataclass(frozen=True)
class OfglApiSettings:
    """Paramètres d'accès aux jeux OFGL (data.ofgl.fr, API OpenDataSoft v2.1, endpoint "records").

    GET {base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records?where=...
    """

    base_url: str = "https://data.ofgl.fr"
    dataset_communes: str = "ofgl-base-communes"
    dataset_communes_consolidee: str = "ofgl-base-communes-consolidee"
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    # Doit rester nettement au-dessus de (nb de communes de la strate la
    # plus peuplée x nb d'agrégats dans settings.spending_items) : un
    # plafond trop juste tronque silencieusement le groupe de comparaison
    # de façon inégale selon les postes (constaté en direct en passant de 5
    # à 6 postes : 2000 suffisait tout juste à 5, une requête à 6 agrégats
    # dépassait déjà 2000 lignes et coupait le groupe de façon incohérente
    # d'un poste à l'autre - 245 à 360 communes selon le poste au lieu de
    # 360 partout). Ajouter un poste OFGL doit rester une simple entrée de
    # config, jamais un ajustement manuel de ce plafond.
    max_records_per_query: int = 6_000


# Alias candidats (en minuscules, sans accents) pour identifier les champs
# significatifs dans les enregistrements OFGL reçus, quel que soit leur nom
# exact. "insee" et "tranche_population" (le champ démographique, appelé
# "strate" dans le code/la doc mais "tranche_population" dans l'API) sont
# confirmés par appel réel (utilisés dans les clauses `where` des requêtes) ;
# le reste du schéma doit être complété avec les vrais noms de champs
# constatés au premier appel réel (voir balise.ingestion.ofgl.describe_schema).
OFGL_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "code_insee": ("insee", "code_insee", "codeinsee", "code_geographique"),
    "siren": ("siren", "siren_collectivite"),
    "exercice": ("exer", "exercice", "annee"),
    "population": ("ptot", "population", "population_totale", "pop_totale"),
    "strate": ("tranche_population", "strate", "categorie"),
    "code_departement": ("dep_code", "code_dep", "departement_code", "code_departement"),
    "code_region": ("reg_code", "code_reg", "region_code", "code_region"),
    "agregat": ("agregat", "agregat_name", "libelle_agregat", "nomenclature"),
    "montant": ("montant", "valeur", "montant_euros"),
    "type_de_budget": ("type_de_budget", "typebudget", "budget_type"),
    "commune_nom": ("com_name", "commune_nom", "nom_commune"),
}

# Valeur attendue (comparaison exacte, normalisée) du champ "type_de_budget"
# identifiant le budget principal d'une commune, par opposition à ses
# budgets annexes (services distincts : régie de l'eau, portage de repas...).
# Seul le budget principal est retenu pour les agrégats financiers de la
# commune : mélanger les deux ferait écraser silencieusement un agrégat du
# budget principal par la même ligne d'un budget annexe (souvent à 0).
OFGL_BUDGET_PRINCIPAL_VALUE = "budget principal"
# Même valeur, avec la casse exacte constatée dans l'API (utilisée pour
# construire une clause `where=type_de_budget="..."` côté serveur).
OFGL_BUDGET_PRINCIPAL_LABEL = "Budget principal"

# Alias candidats (comparaison EXACTE, insensible à la casse/accents) pour
# repérer, dans un jeu au format long (colonne "agregat" + "montant"), la
# ligne correspondant à chaque poste de dépense canonique. Les premiers
# candidats de chaque tuple sont les libellés confirmés par appel réel sur
# le dataset ofgl-base-communes (voir scripts/probe_apis.py) ; les suivants
# sont d'anciennes suppositions conservées pour compatibilité avec d'autres
# jeux OFGL (ex. ofgl-base-communes-consolidee) non encore vérifiés.
OFGL_AGGREGATE_ALIASES: dict[str, tuple[str, ...]] = {
    "charges_de_fonctionnement": (
        "depenses de fonctionnement",
        "charges de fonctionnement",
        "charges courantes de fonctionnement",
    ),
    "charges_de_personnel": (
        "frais de personnel",
        "charges de personnel",
        "charges de personnel et frais assimiles",
    ),
    "achats_et_charges_externes": ("achats et charges externes",),
    "depenses_d_equipement": ("depenses d'equipement", "depenses d equipement"),
    "encours_de_dette": ("encours de dette", "encours de la dette", "encours de dette au 31/12"),
    "subventions_associations": ("subventions aux personnes de droit prive",),
}

# Libellés exacts (accents/casse d'origine) des agrégats OFGL, confirmés par
# appel réel, utilisés pour restreindre côté serveur (clause `where=agregat
# in (...)`) le volume récupéré lors de la construction d'un groupe de
# comparaison national. Sans ce filtre, une requête par strate seule renvoie
# des centaines de milliers de lignes (tous agrégats x tous exercices x tous
# budgets confondus) et dépasse largement `max_records_per_query`.
OFGL_AGGREGATE_QUERY_LABELS: dict[str, str] = {
    "charges_de_fonctionnement": "Dépenses de fonctionnement",
    "charges_de_personnel": "Frais de personnel",
    "achats_et_charges_externes": "Achats et charges externes",
    "depenses_d_equipement": "Dépenses d'équipement",
    "encours_de_dette": "Encours de dette",
    "subventions_associations": "Subventions aux personnes de droit privé",
}

# Signification des codes "tranche_population" (champ `strate` résolu) du
# dataset OFGL, confirmée via la description du champ à l'API (appel réel) :
# libellé humain de chaque strate démographique officielle DGCL/OFGL.
OFGL_STRATE_LABELS: dict[str, str] = {
    "0": "moins de 100 habitants",
    "1": "100 à 199 habitants",
    "2": "200 à 499 habitants",
    "3": "500 à 1 999 habitants",
    "4": "2 000 à 3 499 habitants",
    "5": "3 500 à 4 999 habitants",
    "6": "5 000 à 9 999 habitants",
    "7": "10 000 à 19 999 habitants",
    "8": "20 000 à 49 999 habitants",
    "9": "50 000 à 99 999 habitants",
    "10": "100 000 habitants et plus",
}


@dataclass(frozen=True)
class DecpApiSettings:
    """Paramètres d'accès aux marchés publics DECP (API OpenDataSoft v2.1, endpoint "records").

    GET {base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records
        ?where=startswith(idacheteur, "{siren}")

    Le jeu `decp_augmente` de data.economie.gouv.fr est signalé "obsolète"
    sur certaines pages data.gouv.fr recensant les sources DECP ; il est
    utilisé ici sur demande explicite, à défaut d'accès réseau pour vérifier
    en direct une alternative (le jeu consolidé "format tabulaire" plus
    récent, cf. balise.ingestion.decp docstring).
    """

    base_url: str = "https://data.economie.gouv.fr"
    dataset_marches: str = "decp_augmente"
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    max_records_per_query: int = 1_000
    montant_minimum_pertinent: float = 40_000.0
    # L'API OpenDataSoft refuse toute pagination au-delà de offset+limit =
    # 10 000 (constaté en direct : une requête au-delà échoue en 400, quel
    # que soit max_records demandé). Les requêtes "entretien" doivent donc
    # rester sous ce plafond dataset par dataset (voir maintenance_cpv_codes
    # : chaque code CPV est interrogé séparément plutôt qu'en un seul OR).
    entretien_max_records: int = 10_000


# Alias candidats pour identifier les champs significatifs dans les
# enregistrements `decp_augmente` reçus. Seul "acheteur_id" est confirmé
# (utilisé dans la clause `where` fournie) ; le reste doit être validé au
# premier appel réel (voir balise.ingestion.decp.describe_schema).
DECP_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "identifiant", "uid"),
    "acheteur_id": ("idacheteur", "acheteur_id", "id_acheteur", "siret_acheteur"),
    "acheteur_nom": ("nomacheteur", "acheteur_nom", "nom_acheteur"),
    "objet": ("objetmarche", "objet"),
    "code_cpv": ("codecpv", "code_cpv", "cpv"),
    "montant": ("montant",),
    "date_notification": ("datenotification", "date_notification"),
    "titulaire_id": ("siretetablissement", "titulaire_id", "titulaire_id_1", "id_titulaire"),
    "titulaire_denomination": (
        "denominationsocialeetablissement",
        "titulaire_denominationsociale",
        "titulaire_denominationsociale_1",
        "denominationsociale",
        "nom_titulaire",
    ),
    "commune_acheteur": ("codecommuneacheteur", "code_commune_acheteur", "codecommune"),
}


@dataclass(frozen=True)
class CpvCode:
    """Un préfixe de code CPV pertinent pour l'audit de dépenses communales."""

    prefix: str
    label: str


# Liste de départ, non exhaustive, des familles de marchés les plus
# pertinentes pour un audit de dépenses communales (prestations récurrentes,
# comparables d'une commune à l'autre). Configurable : ajouter/retirer des
# entrées ne nécessite aucun changement de code.
DEFAULT_CPV_CODES: tuple[CpvCode, ...] = (
    CpvCode("77300000", "Services d'entretien des espaces verts"),
    CpvCode("90600000", "Services de nettoyage et de balayage des voies publiques"),
    CpvCode("90500000", "Services liés aux déchets (collecte, traitement)"),
    CpvCode("55520000", "Services de restauration collective"),
    CpvCode("79713000", "Services de gardiennage et de sécurité"),
    CpvCode("45233140", "Travaux d'entretien de voirie"),
    CpvCode("50000000", "Services de réparation et d'entretien"),
    CpvCode("65000000", "Services publics (eau, énergie)"),
    CpvCode("71000000", "Services d'architecture, d'ingénierie et de contrôle"),
    CpvCode("92000000", "Services récréatifs, culturels et sportifs"),
)


# Sous-ensemble de DEFAULT_CPV_CODES considéré comme "entretien" (voirie,
# espaces verts, bâtiments, nettoyage) : sert à construire un 6e poste de
# dépense comparé à la strate, en complément des 5 agrégats OFGL (qui n'ont
# pas de ligne "entretien" séparée — voir balise.ingestion.decp).
# Chaque code est interrogé séparément (voir entretien_max_records) : leurs
# volumes individuels sont chacun < 10 000, contrairement à une requête OR
# combinée qui dépasserait le plafond de pagination OpenDataSoft.
DEFAULT_MAINTENANCE_CPV_CODES: tuple[CpvCode, ...] = (
    CpvCode("77300000", "Espaces verts"),
    CpvCode("90600000", "Nettoyage et balayage de la voirie"),
    CpvCode("45233140", "Travaux d'entretien de voirie"),
    CpvCode("50000000", "Réparation et entretien (bâtiments, équipements)"),
)


@dataclass(frozen=True)
class Settings:
    cache_db_path: Path = DEFAULT_CACHE_DB_PATH
    cache_ttl_days: int = 30
    insee: InseeApiSettings = field(default_factory=InseeApiSettings)
    ofgl: OfglApiSettings = field(default_factory=OfglApiSettings)
    decp: DecpApiSettings = field(default_factory=DecpApiSettings)
    strates: tuple[StrateThreshold, ...] = DEFAULT_STRATES
    scoring: ScoringThresholds = field(default_factory=ScoringThresholds)
    spending_items: tuple[SpendingItem, ...] = DEFAULT_SPENDING_ITEMS
    cpv_codes: tuple[CpvCode, ...] = DEFAULT_CPV_CODES
    maintenance_cpv_codes: tuple[CpvCode, ...] = DEFAULT_MAINTENANCE_CPV_CODES


SETTINGS = Settings()
