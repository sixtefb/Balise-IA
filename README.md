# Balise IA — Backend d'audit des dépenses publiques communales

Audite les dépenses publiques d'une commune française en la comparant à un
groupe de communes similaires, à partir de données ouvertes uniquement.

## État du projet

**Ingestion des 3 sources connectée et validée en conditions réelles**
(INSEE, OFGL, DECP) contre `--commune Vernon --code-postal 27200`. Les 3
modules d'ingestion appellent des API JSON publiques sans clé, en requêtes
ciblées (pas de téléchargement de fichier complet) :

| Module | Source | Endpoint |
| --- | --- | --- |
| `balise/ingestion/insee.py` | geo.api.gouv.fr | `GET /communes?codePostal=...` puis `GET /communes/{code}?fields=...siren...` |
| `balise/ingestion/ofgl.py` | data.ofgl.fr (OpenDataSoft v2.1) | `GET /records?where=insee="..."` et `where=tranche_population="..."` |
| `balise/ingestion/decp.py` | data.economie.gouv.fr (OpenDataSoft v2.1, `decp_augmente`) | `GET /records?where=startswith(idacheteur, "...")` |

Un script de validation manuelle est fourni : `scripts/probe_apis.py`
(voir plus bas). Exécuté avec succès (Status 200 sur les 4 requêtes) le
temps de corriger deux bugs de schéma découverts au premier appel réel : le
champ démographique OFGL s'appelle `tranche_population` (pas `strate`), et
le champ acheteur DECP s'appelle `idacheteur` et contient un SIRET, pas un
SIREN (filtrage par préfixe via `startswith()`, l'opérateur `like` ne
supportant pas les wildcards `%` façon SQL sur cette API). Les alias de
`balise/config.py` (`OFGL_COLUMN_ALIASES`, `OFGL_AGGREGATE_ALIASES`,
`DECP_COLUMN_ALIASES`) ont été recalés sur les vrais noms de champs et
libellés d'agrégats constatés.

**Normalisation et scoring implémentés** (`balise/normalization/spending.py`,
`balise/scoring/`) et validés en conditions réelles : conversion des
agrégats OFGL en €/habitant, groupe de comparaison (communes de même strate
démographique OFGL, échelle nationale), z-score par poste de dépense, score
global 0-100. Deux bugs supplémentaires trouvés et corrigés au passage
(voir `balise/ingestion/ofgl.py`) :
- le pivot par commune mélangeait budget principal et budgets annexes pour
  un même agrégat (la dernière ligne rencontrée écrasait les précédentes) —
  filtré désormais sur le budget principal uniquement ;
- une requête de groupe de comparaison par strate seule renvoie des
  centaines de milliers de lignes à l'échelle nationale, très au-delà de
  `max_records_per_query` — la requête est désormais restreinte côté
  serveur (budget principal + agrégats connus + exercice).

**Interface web connectée au backend** : `server.py` (Flask) expose
`GET /api/audit?commune=...&code_postal=...` et sert `static/` (page unique
en JS natif, sans framework) qui appelle cette API et affiche le rapport
réel — score, écarts par poste de dépense vs strate, marchés publics
notables (DECP), export XLSX. Voir [Interface web](#interface-web)
ci-dessous.

`audit.py` (CLI) ne produit encore que la fiche d'identité (étape 1/3) : le
rapport complet n'est aujourd'hui disponible que via l'interface web /
l'API — `balise/report/markdown.py::render_audit_report` reste à
implémenter pour un export Markdown équivalent en CLI.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # inclut requirements.txt + pytest
```

## Valider les 3 API avant tout (à faire en premier)

```bash
python scripts/probe_apis.py --commune Vernon --code-postal 27200
```

Ce script n'utilise aucun module `balise.*` (pas de cache, pas de
résolution de champs) : il affiche le JSON brut reçu de chaque endpoint,
pour vérifier "à l'œil" que les données arrivent et que les noms de champs
supposés dans le code (voir plus bas) sont corrects.

## Utilisation

```bash
python audit.py --commune "Vernon" --code-postal 27200
python audit.py --commune "Vernon" --code-postal 27200 --output rapport.md
python audit.py --commune "Vernon" --code-postal 27200 --no-cache  # force le rappel des API
```

## Interface web

```bash
python server.py                 # http://127.0.0.1:5000
FLASK_DEBUG=1 python server.py   # rechargement auto pendant le développement
```

Page unique (`static/index.html` + `static/app.js`, JS natif sans
framework/build step) : saisie commune/code postal → appel de
`GET /api/audit` → rapport → export XLSX (`static/vendor/exceljs.min.js`,
généré côté client, aucune donnée envoyée à un service tiers) ou export PDF
(généré côté serveur, voir ci-dessous). Le cache DuckDB local
(`data/cache/`) rend les analyses répétées quasi instantanées après le
premier appel (~30s la première fois, réseau national OFGL/DECP compris).

**Rapport PDF téléchargeable** (`balise/report/pdf.py`, endpoint
`GET /api/audit/pdf`). Choix : `fpdf2`, pur Python — pas de dépendance
système (contrairement à une conversion HTML→PDF via WeasyPrint, qui exige
Pango/Cairo, absents de l'environnement de déploiement Render actuel et qui
imposeraient de migrer vers un déploiement Docker). Les graphiques
(anneau de score, barres d'écart, histogrammes de distribution) sont
dessinés directement avec les primitives de dessin de `fpdf2`, en reprenant
la charte graphique et la logique des graphiques SVG de `static/app.js`.
Aucun calcul propre : le module met en forme le dict déjà produit par
`audit_to_dict()`, chiffres inchangés — le PDF réutilise `run_audit()`
(donc le cache DuckDB existant, pas de nouveau fetch réseau).
- 7 pages en pratique (limite visée : 10 max) : couverture (score, verdict,
  synthèse), méthodologie (calcul du z-score, seuils de qualification,
  sources), vue d'ensemble des 7 postes, analyse détaillée des points de
  vigilance (histogramme de distribution + position de la commune par
  poste en alerte/à surveiller), marchés publics notables, démographie,
  sources et limites méthodologiques.
- Polices de base (Helvetica/Courier, pas de fichier de police à
  embarquer) avec l'encodage `cp1252` plutôt que le `latin-1` par défaut de
  `fpdf2`, pour couvrir le symbole € (absent de latin-1) sans changer de
  police. Les caractères mal encodés en amont dans certains libellés DECP
  (source ouverte, non contrôlable) sont remplacés à l'affichage plutôt que
  de faire planter la génération (`_ReportPDF.normalize_text`) — aucune
  valeur numérique n'est concernée.
- Testé sur données réelles (Lorient : rapport complet 7 pages sans point
  de vigilance ; Paris : 2 postes en alerte avec histogrammes détaillés,
  8 marchés notables jusqu'à 144 M€, aucun plafond appliqué), et via
  Playwright de bout en bout (clic sur "PDF Rapport" → téléchargement
  réel du fichier depuis le navigateur).

**Écran d'accueil : recherche ou carte de France** (`static/map.js`). En plus
du formulaire commune/code postal (qui reste l'entrée principale), un second
chemin : cliquer une région sur une carte de France cliquable fait apparaître
la liste de ses communes de plus de 10 000 habitants (triée par population
décroissante), cliquer une commune remplit automatiquement le formulaire.
- `GET /api/communes` (`balise.ingestion.insee.list_communes_above_population`)
  liste les communes filtrées par population. `geo.api.gouv.fr` ne supporte
  pas de filtre serveur par population (paramètre silencieusement ignoré,
  constaté en direct) : le filtrage se fait donc côté client sur la liste
  complète (~35 000 communes en un seul appel, pas de pagination sur cette
  API), puis le résultat filtré (1067 communes ≥ 10 000 hab.) est mis en
  cache comme le reste.
- Le tracé des 13 régions métropolitaines (`static/data/regions.geojson`,
  99,5 Ko, coordonnées arrondies à 4 décimales soit ~11 m de précision,
  largement suffisant pour une carte cliquable) vient du dépôt public
  [gregoiredavid/france-geojson](https://github.com/gregoiredavid/france-geojson) :
  `geo.api.gouv.fr` expose bien le contour d'une commune (`fields=contour`)
  mais pas celui d'une région (champ silencieusement absent de la réponse).
- Projection et rendu SVG faits à la main en JS (pas de librairie de
  cartographie) : projection équirectangulaire corrigée par le cosinus de la
  latitude moyenne, tracé des polygones/multipolygones GeoJSON en chemins
  SVG.
- Testé en Playwright de bout en bout : Île-de-France → Paris (rapport
  généré, score 0/100 « Alerte », 41 communes du même groupe de pairs) et
  Bretagne → Lorient (rapport généré avec succès).

Contenu du rapport :
- **Score global + 7 postes de dépense** comparés à la strate démographique
  (z-score, écart en %), chacun avec un **histogramme de distribution du
  groupe de pairs** (pas juste une barre d'écart : la forme de la
  distribution — étalée, resserrée, avec valeurs extrêmes — est visible, et
  la position de la commune dedans aussi). 6 postes viennent des agrégats
  OFGL (`balise.config.DEFAULT_SPENDING_ITEMS` : fonctionnement, personnel,
  achats, équipement, dette, subventions aux associations) ; le 7e,
  **Entretien** (voirie, espaces verts, bâtiments, nettoyage), n'existe pas
  comme ligne séparée dans OFGL et est reconstruit depuis les marchés
  publics DECP (`balise.ingestion.decp.get_maintenance_spending_by_commune`,
  `balise.config.DEFAULT_MAINTENANCE_CPV_CODES`) — **attention, c'est un
  cumul de marchés notifiés, pas une dépense annuelle** comme les 6 autres
  postes ; le rapport le signale explicitement à côté de ce poste.
  Requête nationale unique (indépendante de la commune), lente au premier
  appel global (~2 min, un appel par code CPV, chacun sous la limite de
  pagination OpenDataSoft de 10 000 lignes), puis mise en cache 30 jours et
  réutilisée pour toutes les communes suivantes.
- **Contexte démographique** (répartition par tranche d'âge, recensement
  INSEE le plus récent) via `balise.ingestion.insee_demographie`
  (`api.insee.fr/melodi`, sans clé). Informatif, **hors score** : une
  population plus âgée ou plus jeune n'est ni un point fort ni un point de
  vigilance en soi, ça contextualise certains écarts de dépense (une
  commune avec plus de personnes âgées dépense normalement plus en social,
  ce n'est pas un signe d'inefficacité).
- **Liste des communes comparées** (nom + population), accessible en
  cliquant sur "Comparé à N communes".
- **Marchés publics DECP** regroupés par référence de marché détectée dans
  l'objet (`GET /api/audit`, champ `marches_notables[].lot_count`) : un
  marché alloti en plusieurs lots (un par corps de métier) apparaît comme
  une seule entrée avec son nombre de lots et la liste des titulaires,
  plutôt que de se répéter à l'identique dans la liste.
- **Évolution du score sur plusieurs exercices**, chargée à la demande
  (bouton "Voir l'évolution", 3/5/10 ans) via `GET /api/audit/history` :
  chaque année interrogée = un nouvel appel national à OFGL (~10-20s non
  caché), volontairement pas chargé automatiquement à chaque audit.
- **Année au choix** : champ optionnel à la saisie, ou bouton "Changer
  d'année" directement sur le rapport. Message d'erreur explicite si OFGL
  n'a pas de données pour l'année demandée (couverture réelle : environ
  2014/2017 à aujourd'hui -1/-2 ans, délai de publication).
- **Groupe de comparaison choisi manuellement** (`balise.scoring.score_commune_custom`,
  paramètres répétés `compare_commune`/`compare_code_postal` sur `GET
  /api/audit` et `GET /api/audit/pdf`). Sur l'écran de saisie, le lien
  "+ Comparer à des communes précises" remplace le groupe automatique (même
  strate démographique OFGL) par une liste de communes choisies à la main —
  utile pour comparer directement à une ville de référence plutôt qu'à un
  groupe statistique. Avec moins de deux communes exploitables, chaque poste
  retombe sur "donnée indisponible" (pas de z-score fiable à partir d'une
  seule comparaison) ; en dessous de `ScoringThresholds.min_peer_group_size`
  (15), un avertissement rappelle que l'écart-type est peu représentatif —
  à lire comme une comparaison directe plutôt qu'un signal statistique
  robuste (`custom_compare_note`, affiché web/XLSX/PDF). Les communes
  introuvables ou sans donnée OFGL pour l'exercice sont ignorées et listées
  explicitement plutôt que de faire échouer tout l'audit. Persiste au
  changement d'année (bouton "Changer d'année" réutilise la même sélection).

### Qualité et fiabilité des données

Cinq améliorations portant spécifiquement sur la fiabilité du score et la
transparence sur les données, sans jamais modifier/filtrer une valeur
source (uniquement des choix de méthodologie de comparaison, ou de
l'affichage d'avertissements) :

- **Groupe de comparaison affiné par population** (`balise.scoring._narrow_peer_group_by_population`).
  La strate OFGL la plus haute ("100 000 habitants et plus") est ouverte :
  elle mélangeait sans distinction une ville de 100 000 habitants et Paris
  (2,1M). Quand la commune s'écarte de plus d'un facteur 3
  (`ScoringThresholds.peer_population_ratio_window`) de la population
  médiane de son groupe de pairs, la comparaison est resserrée aux communes
  d'ordre de grandeur comparable — à condition qu'il en reste au moins
  `min_peer_group_size` (15), sinon le groupe complet est conservé mais
  signalé comme hétérogène (`peer_group_note` dans `GET /api/audit`,
  affiché sur le rapport web, l'export XLSX et le PDF). Constaté en direct :
  aucune ville française n'est dans l'ordre de grandeur de Paris (la
  suivante, Marseille, fait 2,5x moins) — le resserrement échoue donc pour
  Paris et se contente de prévenir l'utilisateur, plutôt que de produire une
  fausse précision.
- **Correction d'un bug de troncature OFGL sur les grandes villes**
  (`balise.ingestion.ofgl._agregats_and_budget_where_clause`). Avant
  correction, la requête `where=insee="..."` seule (tous exercices x tous
  agrégats x tous budgets, y compris les budgets annexes) dépassait le
  plafond de pagination OpenDataSoft pour les communes institutionnellement
  complexes (Paris : exactement 6000 enregistrements renvoyés, soit le
  plafond), tronquant la réponse et faisant afficher à tort "donnée
  indisponible" sur 4 des 6 postes OFGL de Paris. Corrigé en restreignant la
  requête aux seuls agrégats utilisés par le scoring (comme le fait déjà le
  groupe de pairs), ramenant le volume à quelques dizaines de lignes par
  commune.
- **Indicateur de complétude déclarative DECP** (`balise.pipeline.decp_coverage_note`).
  DECP est un système déclaratif : rien n'oblige une commune à publier tous
  ses marchés. Sous 3 marchés distincts trouvés (tous exercices confondus),
  un avertissement s'affiche pour signaler qu'une valeur basse au poste
  "Entretien" (ou peu de marchés notables) peut refléter une faible
  publication plutôt qu'une réelle sobriété — sans filtrer ni modifier les
  données.
- **Signalement des montants exceptionnels** (`balise.pipeline._flag_outlier_markets`).
  Un marché dont le montant dépasse le budget de fonctionnement annuel
  entier de la commune (`MARKET_OUTLIER_BUDGET_RATIO = 1.0`) est signalé
  (badge rouge, web comme PDF) comme probable anomalie de saisie de la
  source — **sans jamais plafonner ni modifier le montant affiché**, à la
  différence d'une tentative précédente (revenue en arrière sur demande
  explicite : la donnée reste toujours celle de la source, seulement
  annotée).
- **Fraîcheur des données affichée sur le rapport**
  (`ofgl.get_data_freshness`, `decp.get_markets_freshness`,
  `decp.get_maintenance_freshness`) : date de dernière récupération en
  cache de chaque source (OFGL, marchés DECP, poste "Entretien"), lue sans
  requête réseau supplémentaire, affichée en pied de rapport web, dans
  l'export XLSX et sur la page "Sources" du PDF.
- **Contexte de la commune (niveau de vie, rural/montagne/touristique, QPV)**
  (`balise.scoring.ContextInfo`, `balise.pipeline.context_note`). `data.ofgl.fr`
  renvoie, pour chaque commune, des champs déjà présents dans la réponse mais
  jusqu'ici jetés : `tranche_revenu_imposable_par_habitant` (revenu médian,
  0 à 5), `rural`, `montagne`, `touristique`, `qpv` (Oui/Non). Purement
  informatif — n'influence ni le groupe de comparaison ni le calcul du score
  (pas de resserrement supplémentaire, pour éviter de cumuler deux
  affinements et faire fondre le groupe sous `min_peer_group_size`) : un
  avertissement s'affiche quand la commune a un caractère (touristique,
  montagne, QPV) partagé par moins de 20% de son groupe de pairs, ou un
  niveau de vie éloigné d'au moins 2 tranches de la médiane du groupe.
  Constaté en direct : Vernon (commune touristique, contrairement à la
  quasi-totalité de sa strate) et Paris (revenu par habitant très supérieur
  à la médiane de son groupe) déclenchent chacun l'avertissement à bon
  escient.

## Déploiement (Render)

**Vercel n'est pas adapté à cette appli** : ses fonctions serverless ont un
timeout court (10-60s) et un système de fichiers éphémère, incompatible
avec le cache DuckDB local et le fetch national "Entretien" qui prend ~2
min à froid. Render (ou tout hébergeur supportant un process long-running
avec disque persistant — Fly.io, Railway...) convient, lui, nativement.

```bash
git push  # puis connecter le repo sur render.com, "New +" -> "Blueprint"
```

`render.yaml` est fourni (Blueprint) : détecté automatiquement si tu passes
par "New +" -> **Blueprint** (pas "Web Service", qui ignore ce fichier et
demande de tout configurer à la main — voir plus bas si c'est déjà fait).
Service web Python, `gunicorn` comme serveur de production, disque
persistant monté sur `BALISE_CACHE_DIR` pour le cache DuckDB.

Points d'attention :
- **1 seul worker gunicorn** (`--workers 1`) : DuckDB n'autorise qu'un seul
  processus en écriture à la fois sur le fichier de cache. Plusieurs
  workers en parallèle provoqueraient des erreurs de verrou. Suffisant pour
  un usage à faible trafic ; à revoir (ex. bascule vers une base supportant
  l'écriture concurrente) si le trafic augmente.
- **Disque persistant** : nécessite un plan payant Render (le plan gratuit
  n'inclut pas de disque persistant — `render.yaml` est réglé sur `starter`).
  Sans disque persistant, l'appli fonctionne quand même, mais perd son
  cache à chaque redémarrage/veille du service (le plan gratuit met le
  service en veille après 15 min d'inactivité), ce qui peut faire
  réapparaître le fetch "Entretien" de ~2 min à chaque réveil.
- **Pré-chauffage via `preDeployCommand`** (`scripts/warm_cache.py`) : le
  fetch national "Entretien" (~2 min) tourne **avant** que le service ne
  prenne du trafic, dans un process séparé. Ne surtout pas le lancer en
  tâche de fond dans le process qui sert les requêtes HTTP — une première
  version faisait ça, et avec un seul worker gunicorn en mode "sync", ce
  travail long empêchait le worker de répondre au signal de vie du maître,
  qui le tuait (`[CRITICAL] WORKER TIMEOUT` puis `SIGKILL`) après ~120s :
  le service plantait avant même sa première vraie requête (constaté en
  déploiement réel). Un appel OFGL non caché sur une nouvelle
  strate/exercice (~20-40s, marge réseau Render incluse) reste possible sur
  une requête individuelle — `--timeout 180` dans `startCommand` couvre ce
  cas.
- **Si le service a été créé via "New +" -> "Web Service"** (pas
  "Blueprint") : `render.yaml` n'est pas lu automatiquement, il faut
  configurer à la main dans Settings :
  - Build Command : `pip install -r requirements.txt`
  - Pre-Deploy Command : `python scripts/warm_cache.py` (si ce champ
    n'existe pas sur ton plan/UI, lance-le une fois manuellement via l'onglet
    "Shell" après le premier déploiement)
  - Start Command : `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --timeout 180`
  - Variable d'environnement `BALISE_CACHE_DIR` pointant vers le point de
    montage du disque persistant (ex. `/var/data`)

## Tests

```bash
pytest -q
```

Les tests mockent les appels HTTP (`requests.get` / `fetch_records`) :
aucun accès réseau n'est nécessaire pour les exécuter. 23 tests couvrent la
résolution INSEE, la pagination OpenDataSoft, et la résolution tolérante de
schéma OFGL/DECP contre des jeux de données simulés réalistes — mais aucun
n'a pu être exécuté contre les vraies API depuis cet environnement.

## Architecture

```
audit.py                       # point d'entrée CLI (fiche d'identité seule, étape 1/3)
server.py                      # serveur Flask : sert static/ + GET /api/audit, pré-chauffe le cache "Entretien" au démarrage
render.yaml                    # Blueprint de déploiement Render (voir section Déploiement)
static/                        # interface web (JS natif, sans framework) : index.html, app.js, vendor/exceljs.min.js
scripts/probe_apis.py          # sonde manuelle des 3 API, JSON brut, à lancer en premier
scripts/warm_cache.py          # pré-chauffage manuel/CI du cache national "Entretien" (voir server.py et Déploiement)
balise/
  config.py                    # tous les seuils/paramètres configurables (strates, scoring, cache, alias de champs)
  models.py                    # CommuneIdentity — couche "public benchmark"
  pipeline.py                  # orchestration complète : résolution commune + score + marchés notables (run_audit)
  client_data/                 # couche future pour les données transmises par le client (non implémentée)
  storage/db.py                # cache local DuckDB (résolutions INSEE + cache générique par requête OFGL/DECP)
  ingestion/
    _opendatasoft.py           # client générique API OpenDataSoft v2.1 "records" (pagination limit/offset)
    _http.py                   # téléchargement HTTP en flux (inutilisé pour l'instant, gardé pour un futur besoin de fichier bulk)
    insee.py                   # résolution commune -> code INSEE/SIREN (implémenté)
    ofgl.py                    # agrégats financiers OFGL (implémenté, validé en conditions réelles)
    decp.py                    # marchés publics DECP (implémenté, validé en conditions réelles)
    insee_demographie.py       # démographie détaillée par tranche d'âge, api.insee.fr/melodi (implémenté, contexte hors score)
  normalization/
    strates.py                 # classement en strate démographique (seuils dans config.py)
    spending.py                # conversion des agrégats OFGL en €/habitant (implémenté)
  scoring/                     # z-score par poste de dépense + score global 0-100 (implémenté, score_commune())
  report/
    markdown.py                # fiche d'identité (implémenté) + rapport d'audit complet en Markdown (squelette — le rapport complet existe aujourd'hui côté web/API, voir balise/pipeline.py)
tests/
data/cache/                    # fichier DuckDB local (ignoré par git), créé au premier lancement
```

### Séparation "données publiques" / "données client"

`balise/models.py` et `balise/ingestion/*` ne manipulent que des données
ouvertes (INSEE, OFGL, DECP) : c'est la couche "benchmark public" qui sert à
construire le groupe de comparaison. `balise/client_data/` est réservée à une
future couche de données transmises par la commune auditée (comptabilité
détaillée) ; elle se comparera au benchmark public sans jamais y contribuer,
ce qui évite une refonte quand cette couche sera implémentée.

### Résolution de schéma tolérante (OFGL, DECP)

Les champs utilisés dans les clauses `where` sont confirmés par appel réel :
`insee` et `tranche_population` (OFGL), `idacheteur` (DECP, filtré par
préfixe SIRET via `startswith()`). Pour le reste (agrégats financiers,
montants, titulaires...), le code résout les noms de champs par
correspondance tolérante contre une liste d'alias configurable
(`OFGL_COLUMN_ALIASES`, `OFGL_AGGREGATE_ALIASES`, `DECP_COLUMN_ALIASES` dans
`balise/config.py`), et échoue explicitement avec la liste des champs
réellement reçus s'il ne trouve pas de correspondance — plutôt que de
produire silencieusement un résultat erroné. Les libellés d'agrégats OFGL
(`OFGL_AGGREGATE_ALIASES`) sont comparés en égalité exacte (et non par
sous-chaîne) : le jeu réel contient des libellés qui se chevauchent (ex.
"Dépenses de fonctionnement" vs "Autres dépenses de fonctionnement"), une
correspondance par sous-chaîne aurait fait écraser silencieusement le total
par une sous-catégorie selon l'ordre d'arrivée des enregistrements.

Deux fonctions de diagnostic aident à corriger ces alias après un premier
appel réel :

```python
from balise.ingestion import ofgl, decp
print(ofgl.describe_schema("27681"))            # champs OFGL réels + valeurs d'agrégat pour Vernon
print(decp.describe_schema("<siren_vernon>"))    # champs DECP réels pour les marchés de Vernon
```

### Remarque sur le jeu DECP utilisé

`decp_augmente` (data.economie.gouv.fr) est signalé "obsolète" sur certaines
pages data.gouv.fr recensant les sources DECP — une alternative plus
récente existe (fichier consolidé "format tabulaire", régénéré
quotidiennement, schéma confirmé via
[ColinMaudry/decp-table-schema](https://github.com/ColinMaudry/decp-table-schema)).
`decp_augmente` est utilisé ici sur demande explicite ; à reconsidérer si le
premier appel réel montre des données absentes ou trop anciennes.

## Prochaines étapes

Normalisation, scoring, et interface web connectée sont faits (voir plus
haut). Reste :

1. **Rapport CLI/Markdown** : `render_audit_report` (`balise/report/markdown.py`)
   reste un squelette — le rapport complet n'existe aujourd'hui que côté
   web/API (`balise/pipeline.py::run_audit`). Le brancher sur `audit.py`
   pour un export Markdown → PDF en CLI, équivalent à l'interface web.
2. **Marchés DECP "anormaux"** : la section "Marchés publics notables" de
   l'interface liste toujours les plus gros marchés de la commune sans les
   comparer à ceux de communes similaires. Le poste "Entretien" (voir plus
   haut) applique déjà ce principe pour un sous-ensemble de codes CPV
   (`DEFAULT_MAINTENANCE_CPV_CODES`) ; l'étendre au reste de
   `DEFAULT_CPV_CODES` (restauration collective, gardiennage, eau/énergie...)
   donnerait une vraie comparaison montant/prestation entre communes sur
   plus de familles de marchés.
3. **Élargissement géographique du groupe de comparaison** : `score_commune`
   n'élargit pas automatiquement le groupe si la strate nationale était
   sous le seuil minimal configuré (`ScoringThresholds.min_peer_group_size`)
   — non implémenté car non nécessaire en pratique (groupes de plusieurs
   centaines de communes par strate), mais `peer_group_size` est exposé
   pour qu'un appelant puisse détecter le cas et agir.
