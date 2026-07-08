#!/usr/bin/env python3
"""Point d'entrée Balise IA.

Étape 1/3 : résolution de la commune (nom + code postal -> code INSEE,
SIREN, population, strate démographique...) et génération d'une fiche
d'identité Markdown. Les comparaisons financières (OFGL) et les marchés
publics (DECP) seront ajoutés aux étapes suivantes.

Usage :
    python audit.py --commune "Vernon" --code-postal 27200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from balise.ingestion.insee import (
    CommuneAmbiguousError,
    CommuneNotFoundError,
    InseeError,
    resolve_commune,
)
from balise.report.markdown import render_commune_identity_card


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="audit.py",
        description="Balise IA - audit des dépenses publiques d'une commune française (données ouvertes).",
    )
    parser.add_argument("--commune", required=True, help="Nom de la commune")
    parser.add_argument("--code-postal", required=True, help="Code postal de la commune")
    parser.add_argument("--no-cache", action="store_true", help="Ignore le cache local et réinterroge l'API")
    parser.add_argument("--output", type=Path, default=None, help="Fichier Markdown de sortie (sinon stdout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        commune = resolve_commune(args.commune, args.code_postal, use_cache=not args.no_cache)
    except CommuneAmbiguousError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    except CommuneNotFoundError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    except InseeError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    report = render_commune_identity_card(commune)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Fiche d'identité écrite dans {args.output}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
