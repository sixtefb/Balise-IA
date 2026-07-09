#!/usr/bin/env python3
"""Serveur HTTP Balise IA : sert l'interface (static/) et l'API d'audit.

Usage :
    python server.py                 # http://127.0.0.1:5000
    PORT=8000 python server.py       # autre port (ex. macOS : AirPlay Receiver
                                      # occupe le 5000 par défaut depuis Monterey)
    FLASK_DEBUG=1 python server.py   # rechargement auto pendant le développement
"""

from __future__ import annotations

import os
import threading

from flask import Flask, jsonify, request, send_from_directory

from balise.ingestion import decp
from balise.pipeline import (
    AuditError,
    CommuneAmbiguousError,
    CommuneNotFoundError,
    InseeError,
    audit_to_dict,
    run_audit,
    run_history,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")


def _warm_maintenance_cache() -> None:
    """Pré-chauffe en tâche de fond le cache national "Entretien" (DECP, ~2 min).

    Sans ça, c'est la toute première requête /api/audit reçue par le
    service qui paierait ces ~2 min en plein milieu d'une requête HTTP
    (risque de timeout côté proxy/plateforme). Lancé une fois au démarrage
    du process ; sans effet si déjà en cache (TTL 30 jours) - dans ce cas la
    fonction retourne en quelques centaines de ms, la requête ne fait que
    lire le cache DuckDB local.

    Ne pas lancer ceci avec plusieurs workers gunicorn en parallèle : DuckDB
    n'autorise qu'un seul processus en écriture à la fois sur un même
    fichier - d'où --workers 1 dans render.yaml. Avec un seul worker,
    aucune concurrence possible sur ce fichier.
    """
    try:
        decp.get_maintenance_spending_by_commune()
    except decp.DecpError:
        pass  # la requête réelle réessaiera ; ne doit jamais faire planter le démarrage.


threading.Thread(target=_warm_maintenance_cache, daemon=True).start()


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/audit")
def api_audit():
    commune_nom = (request.args.get("commune") or "").strip()
    code_postal = (request.args.get("code_postal") or "").strip()
    exercice_raw = request.args.get("exercice")

    if not commune_nom or not code_postal:
        return jsonify({"error": "Paramètres 'commune' et 'code_postal' requis."}), 400

    exercice = None
    if exercice_raw:
        try:
            exercice = int(exercice_raw)
        except ValueError:
            return jsonify({"error": "'exercice' doit être un entier (ex. 2023)."}), 400

    try:
        result = run_audit(commune_nom, code_postal, exercice=exercice)
    except CommuneAmbiguousError as exc:
        return jsonify({"error": str(exc)}), 409
    except CommuneNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except InseeError as exc:
        return jsonify({"error": f"Erreur INSEE : {exc}"}), 502
    except AuditError as exc:
        return jsonify({"error": f"Erreur de calcul du score : {exc}"}), 502

    return jsonify(audit_to_dict(result))


@app.get("/api/audit/history")
def api_audit_history():
    commune_nom = (request.args.get("commune") or "").strip()
    code_postal = (request.args.get("code_postal") or "").strip()
    years_raw = request.args.get("years", "5")

    if not commune_nom or not code_postal:
        return jsonify({"error": "Paramètres 'commune' et 'code_postal' requis."}), 400

    try:
        years = int(years_raw)
    except ValueError:
        return jsonify({"error": "'years' doit être un entier."}), 400

    try:
        result = run_history(commune_nom, code_postal, years=years)
    except CommuneAmbiguousError as exc:
        return jsonify({"error": str(exc)}), 409
    except CommuneNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except InseeError as exc:
        return jsonify({"error": f"Erreur INSEE : {exc}"}), 502
    except AuditError as exc:
        return jsonify({"error": f"Erreur de calcul de l'historique : {exc}"}), 502

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=bool(os.environ.get("FLASK_DEBUG")))
