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
généré côté client, aucune donnée envoyée à un service tiers). Le cache
DuckDB local (`data/cache/`) rend les analyses répétées quasi instantanées
après le premier appel (~30s la première fois, réseau national OFGL/DECP
compris).

Contenu du rapport :
- **Score global + 5 postes de dépense** comparés à la strate démographique
  (z-score, écart en %), chacun avec un **histogramme de distribution du
  groupe de pairs** (pas juste une barre d'écart : la forme de la
  distribution — étalée, resserrée, avec valeurs extrêmes — est visible, et
  la position de la commune dedans aussi).
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
server.py                      # serveur Flask : sert static/ + GET /api/audit
static/                        # interface web (JS natif, sans framework) : index.html, app.js, vendor/exceljs.min.js
scripts/probe_apis.py          # sonde manuelle des 3 API, JSON brut, à lancer en premier
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
   l'interface liste aujourd'hui les plus gros marchés de la commune, sans
   les comparer à ceux de communes similaires (contrairement aux postes de
   dépense OFGL, qui eux sont comparés à la strate). Croiser DECP avec les
   codes CPV de référence (`balise/config.py::DEFAULT_CPV_CODES`) pour une
   vraie comparaison montant/prestation entre communes.
3. **Élargissement géographique du groupe de comparaison** : `score_commune`
   n'élargit pas automatiquement le groupe si la strate nationale était
   sous le seuil minimal configuré (`ScoringThresholds.min_peer_group_size`)
   — non implémenté car non nécessaire en pratique (groupes de plusieurs
   centaines de communes par strate), mais `peer_group_size` est exposé
   pour qu'un appelant puisse détecter le cas et agir.
