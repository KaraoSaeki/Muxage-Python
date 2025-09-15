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

    # Video from VOSTFR
    cmd += ["-map", "0:v:0"]

    # Audio VO from VOSTFR using relative audio index when possible
    try:
        vo_rel = vostfr_ms.audio_indices.index(vo_jpn_stream_index_in_vostfr)
        cmd += ["-map", f"0:a:{vo_rel}"]
    except Exception:
        cmd += ["-map", f"0:{vo_jpn_stream_index_in_vostfr}"]

    # Audio FR from VF input
    if use_temp_processed_audio:
        # Processed donor FLAC has single audio stream
        cmd += ["-map", "1:a:0"]
    else:
        # Prefer relative audio position in input 1 when we know the absolute index
        if fr_stream_index_in_vf is not None:
            try:
                fr_rel = vf_ms.audio_indices.index(fr_stream_index_in_vf)
                cmd += ["-map", f"1:a:{fr_rel}"]
            except Exception:
                cmd += ["-map", f"1:{fr_stream_index_in_vf}"]
        else:
            cmd += ["-map", "1:a:0"]

    # Subtitles and attachments from VOSTFR
    if vostfr_ms.subtitle_indices:
        cmd += ["-map", "0:s?"]
    cmd += ["-map", "0:t?"]

    # Codecs
    cmd += ["-c:v", "copy", "-c:s", "copy", "-c:a", "copy"]

    # Metadata and dispositions
    if default_vf:
        # VF default
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

    # Default FR subtitle (from VOSTFR)
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

    # VO from donor (VOSTFR) using relative audio index when possible
    if use_temp_processed_audio:
        cmd += ["-map", "1:a:0"]
    else:
        if vo_jpn_stream_index_in_vostfr is not None:
            try:
                vo_rel = vostfr_ms.audio_indices.index(vo_jpn_stream_index_in_vostfr)
                cmd += ["-map", f"1:a:{vo_rel}"]
            except Exception:
                cmd += ["-map", f"1:{vo_jpn_stream_index_in_vostfr}"]
        else:
            cmd += ["-map", "1:a:0"]

    # FR from base (VF) — we may only have absolute index; fallback to first audio
    if fr_stream_index_in_vf is not None:
        cmd += ["-map", f"0:{fr_stream_index_in_vf}"]
    else:
        cmd += ["-map", "0:a:0"]

    # Subtitles and attachments from donor (VOSTFR)
    if vostfr_ms.subtitle_indices:
        cmd += ["-map", "1:s?"]
    cmd += ["-map", "1:t?"]

    # Codecs copy
    cmd += ["-c:v", "copy", "-c:s", "copy", "-c:a", "copy"]

    # Metadata and dispositions
    if default_vf:
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

    # Default FR subtitle (from donor VOSTFR)
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
