#!/usr/bin/env python3
"""Sonde manuelle des 3 API externes, appelées isolément, JSON brut affiché.

But : valider que les données arrivent bien depuis chaque source avant de
construire la normalisation/le scoring dessus. N'utilise aucun module
balise.* volontairement (aucune mise en cache, aucune résolution de champs)
pour observer exactement ce que chaque endpoint renvoie.

Usage :
    python scripts/probe_apis.py --commune Vernon --code-postal 27200
"""

from __future__ import annotations

import argparse
import json

import requests

GEO_BASE_URL = "https://geo.api.gouv.fr"
OFGL_BASE_URL = "https://data.ofgl.fr"
OFGL_DATASET = "ofgl-base-communes"
DECP_BASE_URL = "https://data.economie.gouv.fr"
DECP_DATASET = "decp_augmente"


def _print_header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _get(url: str, params: dict | None = None) -> tuple[int, object | None, str | None]:
    """Retourne (status_code, json_ou_None, erreur_ou_None)."""
    try:
        response = requests.get(url, params=params, timeout=30)
        print(f"GET {response.url}")
        print(f"Status: {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            print("Réponse non-JSON, corps brut (500 premiers caractères) :")
            print(response.text[:500])
            return response.status_code, None, "réponse non-JSON"
        return response.status_code, payload, None
    except requests.RequestException as exc:
        print(f"GET {url} -> ÉCHEC : {exc}")
        return -1, None, str(exc)


def probe_insee(commune: str, code_postal: str) -> tuple[str | None, str | None]:
    """Retourne (code_insee, siren) si trouvés."""
    _print_header(f"1. INSEE (geo.api.gouv.fr) — liste des communes du code postal {code_postal}")
    status, payload, error = _get(
        f"{GEO_BASE_URL}/communes",
        {"codePostal": code_postal, "fields": "nom,code,population,departement,region,surface"},
    )
    if error or status != 200:
        return None, None
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    matches = [c for c in payload if c.get("nom", "").strip().lower() == commune.strip().lower()]
    if not matches:
        print(f"\nAucune commune nommée exactement '{commune}' dans la liste ci-dessus.")
        if not payload:
            return None, None
        print("Utilisation de la première commune de la liste pour la suite de la sonde.")
        matches = [payload[0]]

    code_insee = matches[0]["code"]

    _print_header(f"1bis. INSEE (geo.api.gouv.fr) — détail de la commune {code_insee} (SIREN)")
    status, payload, error = _get(
        f"{GEO_BASE_URL}/communes/{code_insee}",
        {"fields": "nom,code,siren,population"},
    )
    if error or status != 200:
        return code_insee, None
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return code_insee, payload.get("siren")


def probe_ofgl(code_insee: str) -> str | None:
    """Retourne une valeur de champ 'strate' trouvée, si présente."""
    _print_header(f"2. OFGL (data.ofgl.fr) — records où insee=\"{code_insee}\"")
    status, payload, error = _get(
        f"{OFGL_BASE_URL}/api/explore/v2.1/catalog/datasets/{OFGL_DATASET}/records",
        {"where": f'insee="{code_insee}"', "limit": 20},
    )
    if error or status != 200:
        return None
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    results = payload.get("results", [])
    if not results:
        print("\nAucun enregistrement OFGL pour ce code INSEE.")
        return None

    strate_field = None
    strate_value = None
    for key in results[0].keys():
        if "strate" in key.lower() or key == "tranche_population":
            strate_field = key
            strate_value = results[0][key]
            print(f"\nChamp candidat pour la strate démographique : '{key}' = {strate_value!r}")
            break

    if strate_value is None:
        print("\nAucun champ contenant 'strate' trouvé dans l'enregistrement. Champs disponibles :")
        print(list(results[0].keys()))
        return None

    _print_header(f"2bis. OFGL (data.ofgl.fr) — records où {strate_field}=\"{strate_value}\" (limit=100)")
    status, payload, error = _get(
        f"{OFGL_BASE_URL}/api/explore/v2.1/catalog/datasets/{OFGL_DATASET}/records",
        {"where": f'{strate_field}="{strate_value}"', "limit": 100},
    )
    if not error and status == 200:
        print(f"total_count = {payload.get('total_count')}, results reçus = {len(payload.get('results', []))}")
        print(json.dumps(payload.get("results", [])[:3], ensure_ascii=False, indent=2))
        print("... (aperçu limité aux 3 premiers enregistrements)")

    return strate_value


def probe_decp(siren: str) -> None:
    _print_header(f"3. DECP (data.economie.gouv.fr) — records où idacheteur commence par \"{siren}\"")
    status, payload, error = _get(
        f"{DECP_BASE_URL}/api/explore/v2.1/catalog/datasets/{DECP_DATASET}/records",
        {"where": f'startswith(idacheteur, "{siren}")', "limit": 100},
    )
    if error or status != 200:
        return
    print(f"total_count = {payload.get('total_count')}, results reçus = {len(payload.get('results', []))}")
    print(json.dumps(payload.get("results", [])[:5], ensure_ascii=False, indent=2))
    print("... (aperçu limité aux 5 premiers enregistrements)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commune", default="Vernon")
    parser.add_argument("--code-postal", default="27200")
    args = parser.parse_args(argv)

    code_insee, siren = probe_insee(args.commune, args.code_postal)

    if code_insee is None:
        print("\nImpossible de continuer : résolution INSEE échouée.")
        return 1

    probe_ofgl(code_insee)

    if siren is None:
        print("\nSIREN introuvable : la sonde DECP ne peut pas être lancée.")
        return 1

    probe_decp(siren)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
