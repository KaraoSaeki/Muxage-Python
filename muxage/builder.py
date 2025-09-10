from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .media import first_fr_subtitle_index
from .models import MediaStreams


def build_mux_command_vf_to_vostfr(
    vostfr_path: Path,
    vf_audio_path_or_input: Path,
    use_temp_processed_audio: bool,
    vo_jpn_stream_index_in_vostfr: int,
    fr_stream_index_in_vf: Optional[int],
    vostfr_ms: MediaStreams,
    vf_ms: MediaStreams,
    out_path: Path,
    default_vf: bool = False,
) -> List[str]:
    """Build mux command for VF -> VOSTFR (base = VOSTFR video, donor = VF audio FR)."""
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(vostfr_path),
        "-i", str(vf_audio_path_or_input),
        "-map_chapters", "0",
    ]

    # Video
    cmd += ["-map", "0:v:0"]
    # Audio VO from 0
    cmd += ["-map", f"0:{vo_jpn_stream_index_in_vostfr}"]
    # Audio FR from 1
    if use_temp_processed_audio:
        cmd += ["-map", "1:a:0"]
    else:
        if fr_stream_index_in_vf is None:
            cmd += ["-map", "1:a:0"]
        else:
            # Map by absolute index in input 1
            cmd += ["-map", f"1:{fr_stream_index_in_vf}"]
    # Subs all from 0
    if vostfr_ms.subtitle_indices:
        cmd += ["-map", "0:s?"]
    # Attachments
    cmd += ["-map", "0:t?"]

    # Codecs
    cmd += ["-c:v", "copy", "-c:s", "copy", "-c:a", "copy"]

    # Metadata and dispositions
    if default_vf:
        # Make VF default
        cmd += [
            "-metadata:s:a:0", "language=jpn",
            "-metadata:s:a:0", "title=VO (Japonais)",
            "-disposition:a:0", "0",
            "-metadata:s:a:1", "language=fra",
            "-metadata:s:a:1", "title=VF",
            "-disposition:a:1", "default",
        ]
    else:
        cmd += [
            "-metadata:s:a:0", "language=jpn",
            "-metadata:s:a:0", "title=VO (Japonais)",
            "-disposition:a:0", "default",
            "-metadata:s:a:1", "language=fra",
            "-metadata:s:a:1", "title=VF",
            "-disposition:a:1", "0",
        ]

    # Default FR subtitle
    fr_sub_idx = first_fr_subtitle_index(vostfr_ms)
    if fr_sub_idx is not None and vostfr_ms.subtitle_indices:
        ordered = [idx for idx in vostfr_ms.subtitle_indices]
        try:
            rel = ordered.index(fr_sub_idx)
            cmd += [f"-disposition:s:{rel}", "default"]
        except ValueError:
            pass

    cmd += [str(out_path)]
    return cmd


def build_mux_command_vostfr_to_vf(
    vf_path: Path,
    vostfr_audio_or_input: Path,
    use_temp_processed_audio: bool,
    vo_jpn_stream_index_in_vostfr: Optional[int],
    fr_stream_index_in_vf: Optional[int],
    vostfr_ms: MediaStreams,
    out_path: Path,
    default_vf: bool = False,
) -> List[str]:
    """Build mux command for VOSTFR -> VF (base = VF video+FR, donor = VOSTFR VO+subs)."""
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(vf_path),
        "-i", str(vostfr_audio_or_input),
        "-map_chapters", "0",
    ]

    # Video from VF
    cmd += ["-map", "0:v:0"]

    # We want audio order: a:0 VO (from donor), a:1 FR (from base)
    if use_temp_processed_audio:
        # processed donor audio at 1:a:0
        cmd += ["-map", "1:a:0"]
    else:
        # map VO by absolute index in input 1 (vostfr)
        if vo_jpn_stream_index_in_vostfr is None:
            # fallback to first audio
            cmd += ["-map", "1:a:0"]
        else:
            cmd += ["-map", f"1:{vo_jpn_stream_index_in_vostfr}"]

    # FR from base (VF)
    if fr_stream_index_in_vf is None:
        cmd += ["-map", "0:a:0"]
    else:
        cmd += ["-map", f"0:{fr_stream_index_in_vf}"]

    # Subtitles from donor (VOSTFR)
    if vostfr_ms.subtitle_indices:
        cmd += ["-map", "1:s?"]
    # Attachments from donor (fonts)
    cmd += ["-map", "1:t?"]

    # Codecs copy
    cmd += ["-c:v", "copy", "-c:s", "copy", "-c:a", "copy"]

    # Metadata: a:0 VO jpn default, a:1 FR
    cmd += [
        "-metadata:s:a:0", "language=jpn",
        "-metadata:s:a:0", "title=VO (Japonais)",
        "-disposition:a:0", "default",
        "-metadata:s:a:1", "language=fra",
        "-metadata:s:a:1", "title=VF",
        "-disposition:a:1", "0",
    ]

    # Default FR subtitle (now coming from input 1). Since we mapped all 1:s?, their order equals vostfr_ms.subtitle_indices order.
    fr_sub_idx = first_fr_subtitle_index(vostfr_ms)
    if fr_sub_idx is not None and vostfr_ms.subtitle_indices:
        ordered = [idx for idx in vostfr_ms.subtitle_indices]
        try:
            rel = ordered.index(fr_sub_idx)
            cmd += [f"-disposition:s:{rel}", "default"]
        except ValueError:
            pass

    cmd += [str(out_path)]
    return cmd
