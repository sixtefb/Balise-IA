# Balise IA — Backend d'audit des dépenses publiques communales

Audite les dépenses publiques d'une commune française en la comparant à un
groupe de communes similaires, à partir de données ouvertes uniquement.

## État du projet

**Étape 1/3 : résolution INSEE.** Le point d'entrée résout une commune
(nom + code postal) vers son code INSEE, son SIREN et ses métadonnées, et
génère une fiche d'identité Markdown. Les modules OFGL (finances) et DECP
(marchés publics) — nécessaires au calcul des scores d'écart et au rapport
d'audit complet — sont présents sous forme de squelette (`balise/ingestion/ofgl.py`,
`balise/ingestion/decp.py`) mais lèvent `NotImplementedError` : ils seront
implémentés aux étapes suivantes, après validation.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # inclut requirements.txt + pytest
```

## Utilisation

```bash
python audit.py --commune "Vernon" --code-postal 27200
python audit.py --commune "Vernon" --code-postal 27200 --output rapport.md
python audit.py --commune "Vernon" --code-postal 27200 --no-cache  # force le rappel de l'API
```

## Tests

```bash
pytest -q
```

Les tests mockent les appels HTTP (`requests.get`) : aucun accès réseau n'est
nécessaire pour les exécuter.

## Architecture

```
audit.py                       # point d'entrée CLI
balise/
  config.py                    # tous les seuils/paramètres configurables (strates, scoring, cache, timeouts)
  models.py                    # CommuneIdentity — couche "public benchmark"
  client_data/                 # couche future pour les données transmises par le client (non implémentée)
  storage/db.py                # cache local DuckDB (une table par source)
  ingestion/
    insee.py                   # résolution commune -> code INSEE/SIREN (implémenté)
    ofgl.py                    # agrégats financiers OFGL (squelette, étape 2)
    decp.py                    # marchés publics DECP (squelette, étape 3)
  normalization/
    strates.py                 # classement en strate démographique (seuils dans config.py)
  scoring/                     # z-score / percentile par poste de dépense (squelette, étape 3)
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

## Source de données (étape 1)

**geo.api.gouv.fr** (API Découpage administratif, Etalab/DINUM, construite à
partir du Code Officiel Géographique de l'INSEE) : résolution nom + code
postal → code INSEE, SIREN, population, superficie, département, région,
EPCI. Pas de clé d'API requise.

## Limitation connue de cet environnement

Le sandbox d'exécution utilisé pour développer cette étape bloque les appels
sortants vers `geo.api.gouv.fr` (politique d'egress). Le module `insee.py` a
donc été validé par des tests unitaires avec appels HTTP mockés (schéma de
réponse documenté par l'API) plutôt que par un appel réel. À exécuter en
conditions réelles (poste local, CI, environnement avec egress ouvert) pour
confirmer l'appel réseau live avant mise en production.

## Prochaines étapes (à valider avant démarrage)

1. **OFGL** (`ofgl.py`) : téléchargement et indexation DuckDB des jeux
   `ofgl-base-communes` / `ofgl-base-communes-consolidee`, construction du
   groupe de comparaison (strate + département/région), normalisation en
   €/habitant.
2. **DECP** (`decp.py`) : téléchargement du fichier consolidé, filtrage par
   codes CPV pertinents (espaces verts, nettoyage, collecte des déchets...),
   comparaison des prix payés entre communes pour une même prestation.
3. **Scoring + rapport complet** : z-score/percentile par poste de dépense,
   qualification configurable ("dans les clous" / "à surveiller" / "alerte"),
   rapport Markdown → export PDF, sans jamais affirmer de malversation —
   uniquement des écarts statistiques et des pistes de vérification.
