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
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

from muxage.cli import main as muxage_main


@dataclass
class EpisodeJob:
    key: str  # like E07, E123
    vostfr_path: Path
    vf_path: Path
    out_path: Path
    offset_ms: int = 0
    apply_speedfix: bool = False
    dry_run: bool = False
    force: bool = False
    no_speedfix: bool = False
    export_vf_audio: bool = False
    export_audio_dir: Optional[Path] = None


@dataclass
class JobResult:
    key: str
    success: bool
    message: str
    ffmpeg_mux_cmd: Optional[List[str]] = None
    ffmpeg_preproc_cmd: Optional[List[str]] = None
    chosen_fr_stream_index: Optional[int] = None
    vo_jpn_stream_index: Optional[int] = None
    speedfix_applied: bool = False
    offset_applied_ms: int = 0
    output_path: Optional[Path] = None
    export_audio_path: Optional[Path] = None
    ffmpeg_export_cmd: Optional[List[str]] = None


def main() -> None:
    # Délègue à la nouvelle CLI. Les options historiques sont préservées, et
    # une nouvelle option --direction est disponible.
    exit_code = muxage_main(sys.argv[1:])
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
