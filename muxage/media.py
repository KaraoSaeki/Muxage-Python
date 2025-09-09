from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    MediaStreams,
    EP_REGEX,
    RELAX_EP_REGEX,
    EPSILON_FPS,
    FPS_VFR_TARGET,
    FPS_PAL,
    LANG_FR_SET,
    LANG_JP_SET,
)


def parse_media_streams(ffjson: Dict[str, Any]) -> MediaStreams:
    streams = ffjson.get("streams", []) or []
    video_indices: List[int] = []
    audio_indices: List[int] = []
    subtitle_indices: List[int] = []
    attachment_indices: List[int] = []
    audio_langs: Dict[int, str] = {}
    subtitle_langs: Dict[int, str] = {}
    audio_channels: Dict[int, int] = {}
    fps: Optional[float] = None

    for st in streams:
        idx = st.get("index")
        if idx is None:
            continue
        codec_type = st.get("codec_type")
        tags = st.get("tags", {}) or {}
        lang = (tags.get("language") or "").lower().strip()
        if codec_type == "video":
            video_indices.append(idx)
            if fps is None:
                fps = _extract_fps(st)
        elif codec_type == "audio":
            audio_indices.append(idx)
            if lang:
                audio_langs[idx] = lang
            ch = st.get("channels")
            if isinstance(ch, int):
                audio_channels[idx] = ch
        elif codec_type == "subtitle":
            subtitle_indices.append(idx)
            if lang:
                subtitle_langs[idx] = lang
        elif codec_type == "attachment":
            attachment_indices.append(idx)

    return MediaStreams(
        video_indices=video_indices,
        audio_indices=audio_indices,
        subtitle_indices=subtitle_indices,
        attachment_indices=attachment_indices,
        audio_langs=audio_langs,
        subtitle_langs=subtitle_langs,
        audio_channels=audio_channels,
        fps=fps,
    )


def _extract_fps(video_stream: Dict[str, Any]) -> Optional[float]:
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = video_stream.get(key)
        if not val or val == "0/0":
            continue
        num, _, den = val.partition("/")
        try:
            num_i = float(num)
            den_i = float(den) if den else 1.0
            if den_i != 0:
                return num_i / den_i
        except ValueError:
            continue
    tb = video_stream.get("time_base")
    if tb and "/" in tb:
        try:
            n, d = tb.split("/", 1)
            n = float(n); d = float(d)
            if n != 0:
                return d / n
        except Exception:
            pass
    return None


def approx_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def decide_speedfix(base_ms: MediaStreams, donor_ms: MediaStreams, no_speedfix: bool) -> bool:
    if no_speedfix:
        return False
    if base_ms.fps is None or donor_ms.fps is None:
        return False
    if approx_equal(base_ms.fps, FPS_VFR_TARGET, EPSILON_FPS) and approx_equal(donor_ms.fps, FPS_PAL, EPSILON_FPS):
        return True
    return False


def extract_episode_key(name: str, relax: bool = False) -> Optional[str]:
    m = EP_REGEX.search(name)
    if not m:
        if relax:
            m2 = RELAX_EP_REGEX.search(name)
            if not m2:
                return None
            digits = m2.group(1)
            return f"E{digits}"
        return None
    digits = m.group(1)
    return f"E{digits}"


def scan_dir_for_keys(directory: Path, relax: bool = False) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if not any(fnmatch.fnmatch(f.lower(), pat) for pat in (
                "*.mkv", "*.mp4", "*.m4v", "*.mov", "*.avi", "*.mpg", "*.ts",
                "*.mka", "*.flac", "*.aac", "*.ac3", "*.dts", "*.opus", "*.mp3", "*.wav", "*.m4a"
            )):
                continue
            key = extract_episode_key(f, relax=relax)
            if key:
                p = Path(root) / f
                if key not in mapping:
                    mapping[key] = p
                else:
                    existing = mapping[key]
                    try:
                        if len(existing.parts) > len(p.parts):
                            mapping[key] = p
                        else:
                            if p.stat().st_mtime > existing.stat().st_mtime:
                                mapping[key] = p
                    except Exception:
                        pass
    return mapping


def find_first_jpn_audio_index(ms: MediaStreams) -> Optional[int]:
    for idx in ms.audio_indices:
        lang = ms.audio_langs.get(idx, "").lower()
        if lang in LANG_JP_SET or lang.startswith("jp"):
            return idx
    return None


def select_fr_audio_stream(ms: MediaStreams) -> Optional[int]:
    for idx in ms.audio_indices:
        lang = ms.audio_langs.get(idx, "").lower()
        if lang in LANG_FR_SET:
            return idx
    return None


def first_fr_subtitle_index(ms: MediaStreams) -> Optional[int]:
    for idx in ms.subtitle_indices:
        lang = ms.subtitle_langs.get(idx, "").lower()
        if lang in LANG_FR_SET:
            return idx
    return None
