#!/usr/bin/env python3
"""
Batch-mux VOSTFR sources with FR audio from VF sources to produce MKV MULTi.

Requirements:
- ffmpeg and ffprobe must be available in PATH.
- Python 3.8+ (standard library only).

Author: Cascade
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import fnmatch
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ----------------------------
# Constants and utilities
# ----------------------------

EP_REGEX = re.compile(r"\b[Ee](\d{2,3})\b")  # strict EXX/EXXX key
# Relaxed pattern to allow matching 'E01' even when preceded by season tokens like 'S01E01'
# (drops the leading word-boundary requirement). Enabled via --relax-extract.
RELAX_EP_REGEX = re.compile(r"(?i)E(\d{2,3})\b")
LANG_FR_SET = {"fra", "fre", "fr"}
LANG_JP_SET = {"jpn", "ja", "japanese"}  # heuristics limited to jpn for VO but accept common tags
EPSILON_FPS = 0.02  # tolerance for fps detection

# Target fps checks
FPS_VFR_TARGET = 24000 / 1001.0  # ~23.976
FPS_PAL = 25.0

SPEEDFIX_ATEMPO = 0.95904  # Speed conversion factor from 25.0 -> 23.976

# ----------------------------
# Data classes
# ----------------------------

@dataclass
class MediaStreams:
    video_indices: List[int]
    audio_indices: List[int]
    subtitle_indices: List[int]
    attachment_indices: List[int]
    audio_langs: Dict[int, str]  # map index -> language (lowercased)
    subtitle_langs: Dict[int, str]  # map index -> language (lowercased)
    audio_channels: Dict[int, int]  # map index -> channels
    fps: Optional[float]  # fps of first video stream if any, else None


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


# ----------------------------
# ffmpeg/ffprobe helpers
# ----------------------------

def check_dependencies() -> None:
    """Ensure ffmpeg and ffprobe are available."""
    missing = []
    for tool in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([tool, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            missing.append(tool)
    if missing:
        print(f"Erreur: Outils requis manquants dans PATH: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)


def run_subprocess(cmd: List[str], dry_run: bool = False) -> int:
    """Run a subprocess command. Return exit code. In dry-run, just log and return 0."""
    print("Commande:", shell_quote_cmd(cmd))
    if dry_run:
        return 0
    proc = subprocess.run(cmd)
    return proc.returncode


def shell_quote_cmd(cmd: List[str]) -> str:
    """Return a display-friendly shell-quoted command for logging."""
    def q(token: str) -> str:
        if os.name == "nt":
            # On Windows, wrap in double quotes if spaces
            if re.search(r'\s|"', token):
                token = token.replace('"', '\\"')
                return f'"{token}"'
            return token
        else:
            # POSIX
            if re.search(r"[^\w@%+=:,./-]", token):
                return "'" + token.replace("'", "'\"'\"'") + "'"
            return token
    return " ".join(q(t) for t in cmd)


def ffprobe_json(path: Path) -> Dict[str, Any]:
    """Return ffprobe json for a given file."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe a échoué pour {path}: {e.stderr.strip()}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe JSON invalide pour {path}: {e}")


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
            # Determine fps if not set
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
    # Try avg_frame_rate then r_frame_rate
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
    # Try for time_base inversed (not ideal)
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


# ----------------------------
# Business logic
# ----------------------------

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
            # Consider common media files only to reduce noise
            if not any(fnmatch.fnmatch(f.lower(), pat) for pat in ("*.mkv", "*.mp4", "*.m4v", "*.mov", "*.avi", "*.mpg", "*.ts", "*.mka", "*.flac", "*.aac", "*.ac3", "*.dts", "*.opus", "*.mp3", "*.wav", "*.m4a")):
                continue
            key = extract_episode_key(f, relax=relax)
            if key:
                # Prefer the first occurrence; warn on duplicates by choosing the shortest path depth
                p = Path(root) / f
                if key not in mapping:
                    mapping[key] = p
                else:
                    # If duplicate, pick one closer (shorter path) or newer (mtime)
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


def parse_offsets_csv(csv_path: Optional[Path]) -> Dict[str, int]:
    """Parse offsets CSV in format key,offset_ms where key is E07/E123 etc."""
    offsets: Dict[str, int] = {}
    if not csv_path:
        return offsets
    if not csv_path.exists():
        print(f"Avertissement: offsets CSV introuvable: {csv_path}", file=sys.stderr)
        return offsets
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                # Could be header or blank
                continue
            key = (row[0] or "").strip()
            if not key or not re.fullmatch(r"[Ee]\d{2,3}", key):
                continue
            key = f"E{key[1:]}"
            off_str = (row[1] or "").strip()
            try:
                offset_ms = int(off_str)
            except ValueError:
                continue
            offsets[key] = offset_ms
    return offsets


def decide_speedfix(vostfr_ms: MediaStreams, vf_ms: MediaStreams, no_speedfix: bool) -> bool:
    if no_speedfix:
        return False
    if vostfr_ms.fps is None or vf_ms.fps is None:
        return False
    if approx_equal(vostfr_ms.fps, FPS_VFR_TARGET, EPSILON_FPS) and approx_equal(vf_ms.fps, FPS_PAL, EPSILON_FPS):
        return True
    return False


def find_first_jpn_audio_index(ms: MediaStreams) -> Optional[int]:
    # Prefer exact 'jpn', but accept heuristics for safety
    for idx in ms.audio_indices:
        lang = ms.audio_langs.get(idx, "").lower()
        if lang in LANG_JP_SET or lang.startswith("jp"):
            return idx
    # If no language tags, cannot be certain. As per requirement, heuristics limited to jpn for VO.
    return None


def select_fr_audio_stream(vf_ms: MediaStreams) -> Optional[int]:
    # Detect audio where language in fra|fre|fr
    for idx in vf_ms.audio_indices:
        lang = vf_ms.audio_langs.get(idx, "").lower()
        if lang in LANG_FR_SET:
            return idx
    return None


def first_fr_subtitle_index(vostfr_ms: MediaStreams) -> Optional[int]:
    for idx in vostfr_ms.subtitle_indices:
        lang = vostfr_ms.subtitle_langs.get(idx, "").lower()
        if lang in LANG_FR_SET:
            return idx
    return None


def build_adelay_filter(ms_delay: int, channels: int) -> str:
    # adelay needs one delay per channel separated by '|'
    if channels <= 0:
        channels = 2  # assume stereo if unknown
    return "adelay=" + "|".join(str(ms_delay) for _ in range(channels))


def preproc_vf_audio_to_temp_flac(
    vf_path: Path,
    fr_stream_index: int,
    out_dir: Path,
    key: str,
    offset_ms: int,
    apply_speedfix: bool,
    channels: int,
    dry_run: bool,
) -> Tuple[int, Optional[Path], Optional[List[str]]]:
    """
    Extract and preprocess the FR audio stream:
    - Select stream index
    - Apply offset (positive -> delay; negative -> trim)
    - Apply optional PAL speedfix atempo
    - Output to temporary FLAC file
    Returns (exit_code, temp_path, command)
    """
    tmp_dir = out_dir / ".temp_mux"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_out = tmp_dir / f"{key}_vf_preproc.flac"

    filters: List[str] = []

    # Select the chosen FR stream as input
    # Build filter chain
    if offset_ms < 0:
        # Negative: trim start
        start_sec = max(0.0, abs(offset_ms) / 1000.0)
        filters.append(f"atrim=start={start_sec}")
        filters.append("asetpts=PTS-STARTPTS")
    elif offset_ms > 0:
        # Positive: add silence at head
        filters.append(build_adelay_filter(offset_ms, channels))

    if apply_speedfix:
        filters.append(f"atempo={SPEEDFIX_ATEMPO}")

    # Combine filters
    filter_arg = ",".join(filters) if filters else None

    cmd = [
        "ffmpeg",
        "-y",  # overwrite temp
        "-v", "error",
        "-i", str(vf_path),
        "-map", f"0:{fr_stream_index}",
        "-vn",
        "-sn",
    ]
    if filter_arg:
        cmd += ["-af", filter_arg]
    cmd += [
        "-c:a", "flac",
        str(temp_out)
    ]

    rc = run_subprocess(cmd, dry_run=dry_run)
    if rc != 0:
        return rc, None, cmd
    return 0, temp_out, cmd


def build_mux_command(
    vostfr_path: Path,
    vf_audio_path_or_input: Path,
    use_temp_processed_audio: bool,
    vo_jpn_stream_index: int,
    fr_stream_index_in_vf: Optional[int],
    vostfr_ms: MediaStreams,
    out_path: Path,
    set_default_fr_sub_idx: Optional[int],
) -> List[str]:
    """
    Build ffmpeg muxing command:
    - Input 0: VOSTFR
    - Input 1: VF processed FLAC (if use_temp_processed_audio) or raw VF file
    - Map video from 0
    - Map VO JPN audio from 0 explicitly
    - Map FR audio from 1 (if preprocessed) or from 1:fr_stream_index_in_vf
    - Map subtitles from 0
    - Map attachments from 0
    - Copy streams except VF audio (already flac if preprocessed; else copy)
    - Set metadata and dispositions
    """
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(vostfr_path),
        "-i", str(vf_audio_path_or_input),
        "-map_chapters", "0",  # preserve chapters from VOSTFR if present
    ]

    # Map streams
    # Video: take the first video from input 0
    cmd += ["-map", "0:v:0"]

    # VO JPN audio from input 0 by absolute index: need relative mapping. Find the position of vo_jpn_stream_index among 0:a streams.
    # Easiest: map directly by absolute stream spec "0:<index>"
    cmd += ["-map", f"0:{vo_jpn_stream_index}"]

    # VF FR audio from input 1
    if use_temp_processed_audio:
        # The processed file should have single audio stream at index 0
        cmd += ["-map", "1:a:0"]
    else:
        # Directly map the FR stream index from input 1
        if fr_stream_index_in_vf is None:
            # Should not happen if checked earlier, fallback to 1:a:0
            cmd += ["-map", "1:a:0"]
        else:
            cmd += ["-map", f"1:{fr_stream_index_in_vf}"]

    # Subtitles from input 0 (all)
    if vostfr_ms.subtitle_indices:
        cmd += ["-map", "0:s?"]  # map all subs if present

    # Attachments from input 0
    cmd += ["-map", "0:t?"]

    # Codecs: copy for video and subs and original VO audio; for VF audio if preprocessed it's already flac; else copy
    cmd += ["-c:v", "copy"]
    cmd += ["-c:s", "copy"]
    # For audio streams, we can specify per stream with -c:a:0 and -c:a:1, but simpler: copy by default, then override if needed.
    if use_temp_processed_audio:
        # Both audios might be copy-able; the processed VF is flac; leave default -c copy and ffmpeg will auto keep formats
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "copy"]

    # Metadata and dispositions
    # After mapping, audio stream order:
    #   a:0 -> VO (from 0)
    #   a:1 -> VF (from 1)
    # Set languages and titles accordingly.
    cmd += [
        "-metadata:s:a:0", "language=jpn",
        "-metadata:s:a:0", "title=VO (Japonais)",
        "-disposition:a:0", "default",
        "-metadata:s:a:1", "language=fra",
        "-metadata:s:a:1", "title=VF",
        "-disposition:a:1", "0",
    ]

    # Default FR subtitle if present; Need to find relative index among mapped subtitles.
    # We don't know the relative 's' index after mapping without probing, but we can attempt to set default based on original index if mapping all.
    # Approach: compute the ordinal position of the target subtitle within 0:s streams.
    if set_default_fr_sub_idx is not None and vostfr_ms.subtitle_indices:
        # Build mapping from original subtitle stream index to relative subtitle order after mapping (0-based)
        ordered_subs = [idx for idx in vostfr_ms.subtitle_indices]
        try:
            rel_sub_pos = ordered_subs.index(set_default_fr_sub_idx)
            cmd += ["-disposition:s:{}".format(rel_sub_pos), "default"]
        except ValueError:
            # Ignore if not found
            pass

    cmd += [str(out_path)]
    return cmd


def process_episode(job: EpisodeJob) -> JobResult:
    key = job.key
    try:
        # Probe VOSTFR
        vostfr_json = ffprobe_json(job.vostfr_path)
        vostfr_ms = parse_media_streams(vostfr_json)
        # Probe VF
        vf_json = ffprobe_json(job.vf_path)
        vf_ms = parse_media_streams(vf_json)

        # Select required streams
        vo_jpn_idx = find_first_jpn_audio_index(vostfr_ms)
        if vo_jpn_idx is None:
            return JobResult(
                key=key, success=False,
                message=f"Aucune piste audio VO (JPN) détectée dans VOSTFR: {job.vostfr_path}"
            )

        fr_idx = select_fr_audio_stream(vf_ms)
        if fr_idx is None:
            return JobResult(
                key=key, success=False,
                message=f"Aucune piste audio FR détectée dans VF: {job.vf_path}"
            )

        # Decide speedfix
        will_speedfix = decide_speedfix(vostfr_ms, vf_ms, job.no_speedfix)

        # Resolve offset and channels
        offset_ms = job.offset_ms
        channels = vf_ms.audio_channels.get(fr_idx, 2)

        # Prepare output path
        out_path = job.out_path
        if out_path.exists() and not job.force:
            return JobResult(
                key=key, success=False,
                message=f"Sortie existe déjà (utiliser --force): {out_path}"
            )

        # Preprocess VF audio if needed (speedfix or any offset)
        use_preproc = will_speedfix or (offset_ms != 0)
        preproc_cmd = None
        tmp_audio_path: Optional[Path] = None
        preproc_rc = 0

        if use_preproc:
            preproc_rc, tmp_audio_path, preproc_cmd = preproc_vf_audio_to_temp_flac(
                vf_path=job.vf_path,
                fr_stream_index=fr_idx,
                out_dir=out_path.parent,
                key=key,
                offset_ms=offset_ms,
                apply_speedfix=will_speedfix,
                channels=channels,
                dry_run=job.dry_run,
            )
            if preproc_rc != 0 or tmp_audio_path is None:
                return JobResult(
                    key=key, success=False,
                    message=f"Echec prétraitement audio VF pour {key}.",
                    ffmpeg_preproc_cmd=preproc_cmd,
                )
            vf_audio_input = tmp_audio_path
        else:
            vf_audio_input = job.vf_path

        # Build mux command
        set_default_fr_sub_idx = first_fr_subtitle_index(vostfr_ms)
        mux_cmd = build_mux_command(
            vostfr_path=job.vostfr_path,
            vf_audio_path_or_input=vf_audio_input,
            use_temp_processed_audio=use_preproc,
            vo_jpn_stream_index=vo_jpn_idx,
            fr_stream_index_in_vf=fr_idx if not use_preproc else None,
            vostfr_ms=vostfr_ms,
            out_path=out_path,
            set_default_fr_sub_idx=set_default_fr_sub_idx,
        )

        # Ensure output directory exists
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Run mux
        rc = run_subprocess(mux_cmd, dry_run=job.dry_run)
        if rc != 0:
            # Cleanup temp if existed
            if use_preproc and tmp_audio_path and tmp_audio_path.exists() and not job.dry_run:
                try:
                    tmp_audio_path.unlink()
                except Exception:
                    pass
            return JobResult(
                key=key, success=False,
                message=f"Echec mux pour {key}.",
                ffmpeg_mux_cmd=mux_cmd,
                ffmpeg_preproc_cmd=preproc_cmd,
                chosen_fr_stream_index=fr_idx,
                vo_jpn_stream_index=vo_jpn_idx,
                speedfix_applied=will_speedfix,
                offset_applied_ms=offset_ms,
            )

        # Success: cleanup temp
        if use_preproc and tmp_audio_path and tmp_audio_path.exists() and not job.dry_run:
            try:
                tmp_audio_path.unlink()
            except Exception:
                pass

        return JobResult(
            key=key, success=True,
            message=f"OK: {out_path.name}",
            ffmpeg_mux_cmd=mux_cmd,
            ffmpeg_preproc_cmd=preproc_cmd,
            chosen_fr_stream_index=fr_idx,
            vo_jpn_stream_index=vo_jpn_idx,
            speedfix_applied=will_speedfix,
            offset_applied_ms=offset_ms,
            output_path=out_path,
        )

    except Exception as e:
        return JobResult(key=key, success=False, message=f"Erreur: {e}")


# ----------------------------
# CLI and orchestration
# ----------------------------

def list_pairs(vostfr_dir: Path, vf_dir: Path, relax: bool = False) -> List[Tuple[str, Path, Path]]:
    vostfr_map = scan_dir_for_keys(vostfr_dir, relax=relax)
    vf_map = scan_dir_for_keys(vf_dir, relax=relax)
    keys = sorted(set(vostfr_map.keys()) & set(vf_map.keys()), key=lambda k: (len(k), k))
    pairs: List[Tuple[str, Path, Path]] = []
    for k in keys:
        pairs.append((k, vostfr_map[k], vf_map[k]))
    # Report ignored files (missing key) implicitly by not listing them
    return pairs


def derive_out_path(vostfr_file: Path, out_dir: Path) -> Path:
    base = vostfr_file.stem  # remove extension
    return out_dir / f"{base}.MULTi.mkv"


def main():
    parser = argparse.ArgumentParser(
        description="Batch-mux VOSTFR (vidéo+VO+subs+polices) avec piste audio FR issue d'une source VF pour produire des MKV MULTi."
    )
    parser.add_argument("--vostfr-dir", required=True, type=Path, help="Répertoire contenant les fichiers VOSTFR.")
    parser.add_argument("--vf-dir", required=True, type=Path, help="Répertoire contenant les fichiers VF (audio ou vidéo).")
    parser.add_argument("--out-dir", required=True, type=Path, help="Répertoire de sortie pour les MKV MULTi.")
    parser.add_argument("--offsets-csv", type=Path, default=None, help="CSV des offsets par épisode: key,offset_ms (ex: E07,250)")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1, help="Nombre de workers en parallèle.")
    parser.add_argument("--force", action="store_true", help="Ecraser les fichiers de sortie existants.")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les commandes sans exécuter.")
    parser.add_argument("--no-speedfix", action="store_true", help="Désactiver la détection et l'application auto du PAL speedfix.")
    parser.add_argument("--relax-extract", action="store_true", help="Assouplir l'extraction du motif d'épisode pour matcher EXX même dans des noms comme S01EXX.")
    args = parser.parse_args()

    # Check dependencies
    check_dependencies()

    vostfr_dir: Path = args.vostfr_dir
    vf_dir: Path = args.vf_dir
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build pairs
    pairs = list_pairs(vostfr_dir, vf_dir, relax=bool(args.relax_extract))
    if not pairs:
        print("Aucun appariement trouvé via motif EXX entre VOSTFR et VF.", file=sys.stderr)
        sys.exit(1)

    offsets_map = parse_offsets_csv(args.offsets_csv)

    # Prepare jobs
    jobs: List[EpisodeJob] = []
    for key, vostfr_path, vf_path in pairs:
        offset_ms = offsets_map.get(key, 0)
        out_path = derive_out_path(vostfr_path, out_dir)
        job = EpisodeJob(
            key=key,
            vostfr_path=vostfr_path,
            vf_path=vf_path,
            out_path=out_path,
            offset_ms=offset_ms,
            apply_speedfix=False,  # computed per-job
            dry_run=args.dry_run,
            force=args.force,
            no_speedfix=args.no_speedfix,
        )
        jobs.append(job)

    # Process in parallel
    results: List[JobResult] = []
    # Log header
    print(f"Jobs: {len(jobs)} épisodes appariés.")
    for key, vp, vfp in pairs:
        print(f"- {key}: VOSTFR={vp} | VF={vfp}")

    # Worker function wrapper to include speedfix decision inside processing (already handled there)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        future_to_job = {executor.submit(process_episode, job): job for job in jobs}
        for future in concurrent.futures.as_completed(future_to_job):
            res = future.result()
            # Per-job logging
            print(f"[{res.key}] {'SUCCÈS' if res.success else 'ÉCHEC'} - {res.message}")
            if res.chosen_fr_stream_index is not None:
                print(f"[{res.key}] Piste FR choisie (index VF): {res.chosen_fr_stream_index}")
            if res.vo_jpn_stream_index is not None:
                print(f"[{res.key}] Piste VO JPN (index VOSTFR): {res.vo_jpn_stream_index}")
            print(f"[{res.key}] Speedfix appliqué: {'oui' if res.speedfix_applied else 'non'}")
            print(f"[{res.key}] Offset appliqué: {res.offset_applied_ms} ms")
            if res.ffmpeg_preproc_cmd:
                print(f"[{res.key}] ffmpeg (prétraitement): {shell_quote_cmd(res.ffmpeg_preproc_cmd)}")
            if res.ffmpeg_mux_cmd:
                print(f"[{res.key}] ffmpeg (mux): {shell_quote_cmd(res.ffmpeg_mux_cmd)}")
            results.append(res)

    # Summary and exit code
    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    print(f"Terminé. Succès: {ok} | Échecs: {fail}")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
