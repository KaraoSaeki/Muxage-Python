from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import re

# ----------------------------
# Constants and settings
# ----------------------------

EP_REGEX = re.compile(r"\b[Ee](\d{2,3})\b")
RELAX_EP_REGEX = re.compile(r"(?i)E(\d{2,3})\b")
LANG_FR_SET = {"fra", "fre", "fr"}
LANG_JP_SET = {"jpn", "ja", "japanese"}
EPSILON_FPS = 0.02

FPS_VFR_TARGET = 24000 / 1001.0  # ~23.976
FPS_PAL = 25.0
SPEEDFIX_ATEMPO = 0.95904  # factor 25.0 -> 23.976


@dataclass
class MediaStreams:
    video_indices: List[int]
    audio_indices: List[int]
    subtitle_indices: List[int]
    attachment_indices: List[int]
    audio_langs: Dict[int, str]
    subtitle_langs: Dict[int, str]
    audio_channels: Dict[int, int]
    fps: Optional[float]


@dataclass
class EpisodeJob:
    key: str
    base_path: Path  # source that provides video
    donor_path: Path  # source that provides the extra audio/subs
    out_path: Path
    # stream selection
    base_vo_jpn_idx: Optional[int] = None  # jpn index in base (used in VF->VOSTFR mode)
    donor_vo_jpn_idx: Optional[int] = None  # jpn index in donor (used in VOSTFR->VF mode)
    base_fr_idx: Optional[int] = None
    donor_fr_idx: Optional[int] = None

    offset_ms: int = 0
    apply_speedfix: bool = False
    dry_run: bool = False
    force: bool = False
    no_speedfix: bool = False
    # export options
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
    # optional export outputs/logs
    export_audio_path: Optional[Path] = None
    ffmpeg_export_cmd: Optional[List[str]] = None


class Direction:
    VF_TO_VOSTFR = "vf_to_vostfr"       # current behavior: base = VOSTFR, donor = VF (provides FR)
    VOSTFR_TO_VF = "vostfr_to_vf"       # reverse: base = VF, donor = VOSTFR (provides JPN+subs)

    @staticmethod
    def choices() -> List[str]:
        return [Direction.VF_TO_VOSTFR, Direction.VOSTFR_TO_VF]
