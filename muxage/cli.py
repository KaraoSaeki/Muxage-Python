from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .models import Direction
from .processor import run_batch
from .util import parse_offsets_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-mux VOSTFR <-> VF pour produire des MKV MULTi.\n"
            "Direction vf_to_vostfr: base = VOSTFR (vidéo+subs), donneur = VF (audio FR).\n"
            "Direction vostfr_to_vf: base = VF (vidéo+FR), donneur = VOSTFR (VO+subs)."
        )
    )
    parser.add_argument("--vostfr-dir", required=True, type=Path, help="Répertoire contenant les fichiers VOSTFR.")
    parser.add_argument("--vf-dir", required=True, type=Path, help="Répertoire contenant les fichiers VF (audio ou vidéo).")
    parser.add_argument("--out-dir", required=True, type=Path, help="Répertoire de sortie pour les MKV MULTi.")
    parser.add_argument("--direction", choices=Direction.choices(), default=Direction.VF_TO_VOSTFR,
                        help="Sens du muxage: vf_to_vostfr (par défaut) ou vostfr_to_vf.")
    parser.add_argument("--offsets-csv", type=Path, default=None, help="CSV des offsets par épisode: key,offset_ms (ex: E07,250)")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1, help="Nombre de workers en parallèle.")
    parser.add_argument("--force", action="store_true", help="Ecraser les fichiers de sortie existants.")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les commandes sans exécuter.")
    parser.add_argument("--no-speedfix", action="store_true", help="Désactiver la détection et l'application auto du PAL speedfix.")
    parser.add_argument("--relax-extract", action="store_true", help="Assouplir l'extraction du motif EXX (ex: S01E01)")

    args = parser.parse_args(argv)

    # Interprétation des répertoires selon la direction
    if args.direction == Direction.VF_TO_VOSTFR:
        dir_a = args.vostfr_dir
        dir_b = args.vf_dir
    else:
        # Direction inverse: on traite VF comme base (dir_a) et VOSTFR comme donneur (dir_b)
        dir_a = args.vf_dir
        dir_b = args.vostfr_dir

    dir_a = dir_a.resolve()
    dir_b = dir_b.resolve()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    offsets_map = parse_offsets_csv(args.offsets_csv)

    return run_batch(
        direction=args.direction,
        dir_a=dir_a,
        dir_b=dir_b,
        out_dir=out_dir,
        offsets_map=offsets_map,
        workers=int(args.workers),
        force=bool(args.force),
        dry_run=bool(args.dry_run),
        no_speedfix=bool(args.no_speedfix),
        relax_extract=bool(args.relax_extract),
    )


if __name__ == "__main__":
    sys.exit(main())
