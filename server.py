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
import re
import unicodedata

from flask import Flask, Response, jsonify, request, send_from_directory

from balise.ingestion.insee import list_communes_above_population
from balise.pipeline import (
    AuditError,
    CommuneAmbiguousError,
    CommuneNotFoundError,
    InseeError,
    audit_to_dict,
    run_audit,
    run_history,
)
from balise.report.pdf import generate_pdf

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# Le pré-chauffage du cache national "Entretien" (DECP, ~2 min) ne se fait
# PAS ici. Une tentative précédente le lançait en tâche de fond au démarrage
# du process : avec gunicorn en mode "sync" (un seul thread traite les
# requêtes), ce travail long a fini par empêcher le worker de répondre au
# signal de vie du maître, qui l'a tué (WORKER TIMEOUT -> SIGKILL) après
# ~120s, plantant le service. Le pré-chauffage doit tourner en dehors du
# process qui sert les requêtes HTTP — voir scripts/warm_cache.py, lancé en
# pre-deploy (render.yaml) avant que le service ne prenne du trafic.


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


def _pdf_filename(commune_nom: str) -> str:
    slug = unicodedata.normalize("NFKD", commune_nom)
    slug = "".join(c for c in slug if not unicodedata.combining(c))
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower() or "commune"
    return f"balise-ia-{slug}.pdf"


@app.get("/api/audit/pdf")
def api_audit_pdf():
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

    audit = audit_to_dict(result)
    pdf_bytes = generate_pdf(audit)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(result.commune.nom)}"'},
    )


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


@app.get("/api/communes")
def api_communes():
    """Communes de plus de 10 000 habitants (par défaut), pour la sélection par carte."""
    min_population_raw = request.args.get("min_population", "10000")
    try:
        min_population = int(min_population_raw)
    except ValueError:
        return jsonify({"error": "'min_population' doit être un entier."}), 400

    try:
        communes = list_communes_above_population(min_population)
    except InseeError as exc:
        return jsonify({"error": f"Erreur INSEE : {exc}"}), 502

    return jsonify(
        [
            {
                "code_insee": c.get("code"),
                "nom": c.get("nom"),
                "code_postal": (c.get("codesPostaux") or [None])[0],
                "population": c.get("population"),
                "code_region": c.get("codeRegion"),
                "lon": (c.get("centre") or {}).get("coordinates", [None, None])[0],
                "lat": (c.get("centre") or {}).get("coordinates", [None, None])[1],
            }
            for c in communes
        ]
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=bool(os.environ.get("FLASK_DEBUG")))
