"""Groupe de comparaison et calcul des écarts par poste de dépense.

Non implémenté à ce stade - dépend de balise.ingestion.ofgl (agrégats
financiers) et de balise.normalization (regroupement strate + €/habitant).
Prévu :
- build_peer_group(commune, thresholds) -> communes comparables (même
  strate, élargissement géographique si groupe sous le seuil minimal défini
  dans balise.config.ScoringThresholds)
- score_spending_item(valeur_commune, valeurs_pairs) -> z-score + percentile
- qualify_score(z_score, thresholds) -> "dans les clous" | "à surveiller" | "alerte"
"""

from __future__ import annotations
