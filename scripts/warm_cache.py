#!/usr/bin/env python3
"""Pré-chauffe le cache national "Entretien" (DECP) avant mise en service.

Le poste de dépense "Entretien" (voir balise.ingestion.decp) est reconstruit
depuis une requête DECP nationale indépendante de toute commune : ~2 min au
premier appel (4 requêtes, une par code CPV), puis mis en cache 30 jours et
réutilisé pour absolument toutes les communes. Sans pré-chauffage, c'est la
toute première requête /api/audit reçue par le service en production qui
paierait ces ~2 min en plein milieu d'une requête HTTP (risque de dépasser
le timeout du proxy). Ce script fait ce travail pendant le build/déploiement
plutôt que pendant une requête utilisateur.

Utilisé comme preDeployCommand par render.yaml. Volontairement silencieux
sur les erreurs réseau : un échec ici ne doit pas bloquer le déploiement —
le cache sera simplement reconstruit (plus lentement) à la première
requête réelle si ce script n'a pas pu le pré-remplir.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# `python scripts/warm_cache.py` place scripts/ (pas la racine du projet)
# en tête de sys.path : sans ceci, "from balise.ingestion import decp"
# échoue avec ModuleNotFoundError dès que le script est lancé depuis un
# autre répertoire de travail que la racine (constaté en direct en testant
# la commande exacte utilisée par render.yaml).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from balise.ingestion import decp  # noqa: E402


def main() -> int:
    print("[warm_cache] Pré-chauffage du cache national 'Entretien' (DECP)...")
    started = time.time()
    try:
        totals = decp.get_maintenance_spending_by_commune()
    except decp.DecpError as exc:
        print(f"[warm_cache] Échec (non bloquant, le cache se remplira à la première requête réelle) : {exc}")
        return 0

    elapsed = time.time() - started
    print(f"[warm_cache] OK : {len(totals)} communes en cache en {elapsed:.0f}s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
