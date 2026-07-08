# Balise IA — Backend d'audit des dépenses publiques communales

Audite les dépenses publiques d'une commune française en la comparant à un
groupe de communes similaires, à partir de données ouvertes uniquement.

## État du projet

**Ingestion des 3 sources connectée (INSEE, OFGL, DECP), en attente de
validation réseau avant d'attaquer normalisation/scoring.** Les 3 modules
d'ingestion appellent des API JSON publiques sans clé, en requêtes
ciblées (pas de téléchargement de fichier complet) :

| Module | Source | Endpoint |
| --- | --- | --- |
| `balise/ingestion/insee.py` | geo.api.gouv.fr | `GET /communes?codePostal=...` puis `GET /communes/{code}?fields=...siren...` |
| `balise/ingestion/ofgl.py` | data.ofgl.fr (OpenDataSoft v2.1) | `GET /records?where=insee="..."` et `where=strate="..."` |
| `balise/ingestion/decp.py` | data.economie.gouv.fr (OpenDataSoft v2.1, `decp_augmente`) | `GET /records?where=acheteur_id like "..."` |

Un script de validation manuelle est fourni : `scripts/probe_apis.py`
(voir plus bas). **Il n'a pas pu être exécuté avec succès depuis
l'environnement où ce code a été écrit** (réseau sortant bloqué vers ces
trois domaines) — voir [Limitation réseau](#limitation-réseau-de-lenvironnement-de-développement).

Le rapport d'audit complet (normalisation €/habitant, scoring, génération
Markdown/PDF) n'est pas encore implémenté : la priorité est de confirmer que
les 3 sources renvoient bien des données exploitables avant de construire
dessus (`balise/normalization/`, `balise/scoring/` restent des squelettes).

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
audit.py                       # point d'entrée CLI
scripts/probe_apis.py          # sonde manuelle des 3 API, JSON brut, à lancer en premier
balise/
  config.py                    # tous les seuils/paramètres configurables (strates, scoring, cache, alias de champs)
  models.py                    # CommuneIdentity — couche "public benchmark"
  client_data/                 # couche future pour les données transmises par le client (non implémentée)
  storage/db.py                # cache local DuckDB (résolutions INSEE + cache générique par requête OFGL/DECP)
  ingestion/
    _opendatasoft.py           # client générique API OpenDataSoft v2.1 "records" (pagination limit/offset)
    _http.py                   # téléchargement HTTP en flux (inutilisé pour l'instant, gardé pour un futur besoin de fichier bulk)
    insee.py                   # résolution commune -> code INSEE/SIREN (implémenté)
    ofgl.py                    # agrégats financiers OFGL (implémenté, schéma à valider)
    decp.py                    # marchés publics DECP (implémenté, schéma à valider)
  normalization/
    strates.py                 # classement en strate démographique (seuils dans config.py)
  scoring/                     # z-score / percentile par poste de dépense (squelette, à construire)
  report/
    markdown.py                # fiche d'identité (implémenté) + rapport d'audit complet (squelette)
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

Le nom exact des champs renvoyés par OFGL (`data.ofgl.fr`) et par
`decp_augmente` (`data.economie.gouv.fr`) n'a pas pu être vérifié en direct
(voir limitation réseau ci-dessous). Seuls les champs utilisés dans les
clauses `where` fournies sont confirmés : `insee`, `strate` (OFGL) et
`acheteur_id` (DECP). Pour tout le reste (agrégats financiers, montants,
titulaires...), le code résout les noms de champs par correspondance
tolérante contre une liste d'alias configurable
(`OFGL_COLUMN_ALIASES`, `OFGL_AGGREGATE_ALIASES`, `DECP_COLUMN_ALIASES` dans
`balise/config.py`), et échoue explicitement avec la liste des champs
réellement reçus s'il ne trouve pas de correspondance — plutôt que de
produire silencieusement un résultat erroné.

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

## Limitation réseau de l'environnement de développement

Le sandbox utilisé pour écrire ce code bloque les appels sortants vers
`geo.api.gouv.fr`, `data.ofgl.fr` et `data.economie.gouv.fr` (politique
d'egress restreinte à quelques domaines : GitHub, registres de paquets,
services Anthropic). **Aucun des 3 endpoints n'a donc pu être testé en
conditions réelles** — uniquement via des tests unitaires mockés contre des
réponses construites à partir de la documentation et de schémas confirmés
quand possible (DECP "format tabulaire" via GitHub, pagination
OpenDataSoft).

Pour valider réellement le backend :
1. Lancer `python scripts/probe_apis.py --commune Vernon --code-postal 27200`
   depuis une machine (ou un environnement Claude Code) ayant accès à ces
   3 domaines.
2. Comparer les champs réellement reçus aux alias configurés dans
   `balise/config.py` (`OFGL_COLUMN_ALIASES`, `OFGL_AGGREGATE_ALIASES`,
   `DECP_COLUMN_ALIASES`) et corriger si nécessaire.
3. Relancer `pytest -q` puis `python audit.py --commune ... --code-postal ...`.

## Prochaines étapes (après validation des 3 API)

1. **Normalisation** : conversion des agrégats OFGL en €/habitant,
   construction du groupe de comparaison (strate + élargissement
   géographique si < 15-20 communes).
2. **Scoring** : z-score/percentile par poste de dépense, qualification
   configurable ("dans les clous" / "à surveiller" / "alerte").
3. **Rapport complet** : résumé exécutif, détail par poste de dépense,
   marchés DECP les plus anormaux, export Markdown → PDF, sans jamais
   affirmer de malversation — uniquement des écarts statistiques et des
   pistes de vérification.
