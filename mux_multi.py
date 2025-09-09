#!/usr/bin/env python3
"""
Wrapper CLI pour rétrocompatibilité.

Ce fichier délègue désormais toute la logique au paquet modulaire `muxage`.
Utilisez l'option --direction pour choisir le sens du muxage:
  - vf_to_vostfr (par défaut): base = VOSTFR (vidéo+subs), donneur = VF (audio FR)
  - vostfr_to_vf: base = VF (vidéo+FR), donneur = VOSTFR (VO+subs)
"""

from __future__ import annotations

import sys

from muxage.cli import main as muxage_main


def main() -> None:
    # Délègue à la nouvelle CLI. Les options historiques sont préservées, et
    # une nouvelle option --direction est disponible.
    exit_code = muxage_main(sys.argv[1:])
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
