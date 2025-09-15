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

    # Audio mapping order
    if default_vf:
        # Put VF first (a:0), VO second (a:1)
        # VF from input 1
        if use_temp_processed_audio:
            cmd += ["-map", "1:a:0"]
        else:
            if fr_stream_index_in_vf is not None:
                try:
                    fr_rel = vf_ms.audio_indices.index(fr_stream_index_in_vf)
                    cmd += ["-map", f"1:a:{fr_rel}"]
                except Exception:
                    cmd += ["-map", f"1:{fr_stream_index_in_vf}"]
            else:
                cmd += ["-map", "1:a:0"]
        # VO from input 0
        try:
            vo_rel = vostfr_ms.audio_indices.index(vo_jpn_stream_index_in_vostfr)
            cmd += ["-map", f"0:a:{vo_rel}"]
        except Exception:
            cmd += ["-map", f"0:{vo_jpn_stream_index_in_vostfr}"]
    else:
        # VO first (a:0), VF second (a:1)
        try:
            vo_rel = vostfr_ms.audio_indices.index(vo_jpn_stream_index_in_vostfr)
            cmd += ["-map", f"0:a:{vo_rel}"]
        except Exception:
            cmd += ["-map", f"0:{vo_jpn_stream_index_in_vostfr}"]
        if use_temp_processed_audio:
            cmd += ["-map", "1:a:0"]
        else:
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
    if use_temp_processed_audio:
        # If VF is first (default_vf), encode a:0 as flac; else encode a:1 as flac
        if default_vf:
            cmd += [
                "-c:v", "copy",
                "-c:s", "copy",
                "-c:a:0", "copy",
                "-c:a:1", "copy",
            ]
        else:
            cmd += [
                "-c:v", "copy",
                "-c:s", "copy",
                "-c:a:0", "copy",
                "-c:a:1", "copy",
            ]
    else:
        cmd += ["-c:v", "copy", "-c:s", "copy", "-c:a", "copy"]

    # Metadata and dispositions
    if default_vf:
        # a:0 = VF, a:1 = VO
        cmd += [
            "-metadata:s:a:0", "language=fra",
            "-metadata:s:a:0", "title=VF",
            "-disposition:a:0", "default",
            "-metadata:s:a:1", "language=jpn",
            "-metadata:s:a:1", "title=VO (Japonais)",
            "-disposition:a:1", "0",
        ]
    else:
        # a:0 = VO, a:1 = VF
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

    # Audio mapping order
    if default_vf:
        # Put VF first (a:0) from base (input 0), then VO (a:1) from donor (input 1)
        if fr_stream_index_in_vf is not None:
            cmd += ["-map", f"0:{fr_stream_index_in_vf}"]
        else:
            cmd += ["-map", "0:a:0"]
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
    else:
        # VO first (a:0) from donor, VF second (a:1) from base
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
        if fr_stream_index_in_vf is not None:
            cmd += ["-map", f"0:{fr_stream_index_in_vf}"]
        else:
            cmd += ["-map", "0:a:0"]

    # Subtitles and attachments from donor (VOSTFR)
    if vostfr_ms.subtitle_indices:
        cmd += ["-map", "1:s?"]
    cmd += ["-map", "1:t?"]

    # Codecs
    if use_temp_processed_audio:
        # If default_vf, a:0 = VF (copy), a:1 = VO (flac) OR vice-versa depending on which was preprocessed.
        if default_vf:
            # Here, donor VO is preprocessed; VF is from base
            cmd += [
                "-c:v", "copy",
                "-c:s", "copy",
                "-c:a:0", "copy",
                "-c:a:1", "copy",
            ]
        else:
            cmd += [
                "-c:v", "copy",
                "-c:s", "copy",
                "-c:a:0", "copy",
                "-c:a:1", "copy",
            ]
    else:
        cmd += ["-c:v", "copy", "-c:s", "copy", "-c:a", "copy"]

    # Metadata and dispositions
    if default_vf:
        # a:0 = VF, a:1 = VO
        cmd += [
            "-metadata:s:a:0", "language=fra",
            "-metadata:s:a:0", "title=VF",
            "-disposition:a:0", "default",
            "-metadata:s:a:1", "language=jpn",
            "-metadata:s:a:1", "title=VO (Japonais)",
            "-disposition:a:1", "0",
        ]
    else:
        # a:0 = VO, a:1 = VF
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
