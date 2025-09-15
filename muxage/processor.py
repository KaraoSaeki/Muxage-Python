from __future__ import annotations

import concurrent.futures
from pathlib import Path
import shutil
import re
from typing import List, Optional, Tuple

from .ffutils import check_dependencies, ffprobe_json, run_subprocess, shell_quote_cmd
from .media import (
    parse_media_streams,
    decide_speedfix,
    scan_dir_for_keys,
    find_first_jpn_audio_index,
    select_fr_audio_stream,
)
from .models import Direction, EpisodeJob, JobResult, MediaStreams
from .builder import build_mux_command_vf_to_vostfr, build_mux_command_vostfr_to_vf


def derive_export_audio_path(base_file: Path, export_dir: Path) -> Path:
    base = base_file.stem
    return export_dir / f"{base}.VF.flac"


def build_pairs(dir_a: Path, dir_b: Path, relax: bool = False) -> List[Tuple[str, Path, Path]]:
    a_map = scan_dir_for_keys(dir_a, relax=relax)
    b_map = scan_dir_for_keys(dir_b, relax=relax)
    keys = sorted(set(a_map.keys()) & set(b_map.keys()), key=lambda k: (len(k), k))
    pairs: List[Tuple[str, Path, Path]] = []
    for k in keys:
        pairs.append((k, a_map[k], b_map[k]))
    return pairs


def preproc_audio_to_temp_flac(
    input_path: Path,
    abs_stream_index: int,
    out_dir: Path,
    key: str,
    offset_ms: int,
    apply_speedfix: bool,
    channels: int,
    dry_run: bool,
) -> Tuple[int, Optional[Path], Optional[List[str]]]:
    """
    Extract and preprocess an audio stream to FLAC with optional delay/speedfix.
    Returns (exit_code, temp_path, command)
    """
    tmp_dir = out_dir / ".temp_mux"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_out = tmp_dir / f"{key}_preproc.flac"

    filters: List[str] = []
    if offset_ms < 0:
        start_sec = max(0.0, abs(offset_ms) / 1000.0)
        filters.append(f"atrim=start={start_sec}")
        filters.append("asetpts=PTS-STARTPTS")
    elif offset_ms > 0:
        # adelay requires per-channel delays
        if channels <= 0:
            channels = 2
        delays = "|".join(str(offset_ms) for _ in range(channels))
        filters.append("adelay=" + delays)
    if apply_speedfix:
        filters.append("atempo=0.95904")

    filter_arg = ",".join(filters) if filters else None

    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(input_path),
        "-map", f"0:{abs_stream_index}",
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


def process_episode_vf_to_vostfr(job: EpisodeJob) -> JobResult:
    key = job.key
    try:
        # base = VOSTFR, donor = VF
        vostfr_json = ffprobe_json(job.base_path)
        vf_json = ffprobe_json(job.donor_path)
        vostfr_ms = parse_media_streams(vostfr_json)
        vf_ms = parse_media_streams(vf_json)

        vo_jpn_idx = find_first_jpn_audio_index(vostfr_ms)
        if vo_jpn_idx is None:
            return JobResult(key=key, success=False, message=f"Aucune piste VO (JPN) dans VOSTFR: {job.base_path}")

        fr_idx = select_fr_audio_stream(vf_ms)
        if fr_idx is None:
            return JobResult(key=key, success=False, message=f"Aucune piste FR dans VF: {job.donor_path}")

        will_speedfix = decide_speedfix(vostfr_ms, vf_ms, job.no_speedfix)
        channels = vf_ms.audio_channels.get(fr_idx, 2)

        if job.out_path.exists() and not job.force:
            return JobResult(key=key, success=False, message=f"Sortie existe déjà (utilisez --force): {job.out_path}")

        use_preproc = will_speedfix or (job.offset_ms != 0) or bool(getattr(job, "force_audio_preproc", False))
        tmp_audio_path = None
        preproc_cmd = None
        if use_preproc:
            rc, tmp_audio_path, preproc_cmd = preproc_audio_to_temp_flac(
                input_path=job.donor_path,
                abs_stream_index=fr_idx,
                out_dir=job.out_path.parent,
                key=key,
                offset_ms=job.offset_ms,
                apply_speedfix=will_speedfix,
                channels=channels,
                dry_run=job.dry_run,
            )
            if rc != 0 or tmp_audio_path is None:
                return JobResult(key=key, success=False, message=f"Echec prétraitement audio FR pour {key}", ffmpeg_preproc_cmd=preproc_cmd)
            donor_audio = tmp_audio_path
        else:
            donor_audio = job.donor_path

        set_ms = vostfr_ms
        mux_cmd = build_mux_command_vf_to_vostfr(
            vostfr_path=job.base_path,
            vf_audio_path_or_input=donor_audio,
            use_temp_processed_audio=use_preproc,
            vo_jpn_stream_index_in_vostfr=vo_jpn_idx,
            fr_stream_index_in_vf=fr_idx if not use_preproc else None,
            vostfr_ms=set_ms,
            vf_ms=vf_ms,
            out_path=job.out_path,
            default_vf=False,
        )

        job.out_path.parent.mkdir(parents=True, exist_ok=True)
        rc = run_subprocess(mux_cmd, dry_run=job.dry_run)
        if rc != 0:
            return JobResult(
                key=key, success=False, message=f"Echec mux pour {key}", ffmpeg_mux_cmd=mux_cmd,
                ffmpeg_preproc_cmd=preproc_cmd, chosen_fr_stream_index=fr_idx, vo_jpn_stream_index=vo_jpn_idx,
                speedfix_applied=will_speedfix, offset_applied_ms=job.offset_ms,
            )

        # Optional: export VF audio standalone in FLAC
        export_audio_path = None
        export_cmd = None
        if job.export_vf_audio:
            export_dir = job.export_audio_dir if job.export_audio_dir is not None else job.out_path.parent
            export_dir.mkdir(parents=True, exist_ok=True)
            export_audio_path = derive_export_audio_path(job.base_path, export_dir)
            if export_audio_path.exists() and not job.force:
                print(f"[{key}] Audio VF standalone existe déjà (utiliser --force): {export_audio_path}")
            else:
                if use_preproc and tmp_audio_path is not None:
                    if not job.dry_run:
                        shutil.copy2(tmp_audio_path, export_audio_path)
                    else:
                        export_cmd = ["copy", str(tmp_audio_path), str(export_audio_path)]
                        print(f"[{key}] Copie audio VF: {shell_quote_cmd(export_cmd)}")
                else:
                    export_cmd = [
                        "ffmpeg", "-y", "-v", "error",
                        "-i", str(job.donor_path),
                        "-map", f"0:{fr_idx}",
                        "-vn", "-sn",
                        "-c:a", "flac",
                        str(export_audio_path)
                    ]
                    rc_exp = run_subprocess(export_cmd, dry_run=job.dry_run)
                    if rc_exp != 0:
                        print(f"[{key}] Échec export audio VF.")

        return JobResult(
            key=key, success=True, message=f"OK: {job.out_path.name}", ffmpeg_mux_cmd=mux_cmd,
            ffmpeg_preproc_cmd=preproc_cmd, chosen_fr_stream_index=fr_idx, vo_jpn_stream_index=vo_jpn_idx,
            speedfix_applied=will_speedfix, offset_applied_ms=job.offset_ms, output_path=job.out_path,
            export_audio_path=export_audio_path, ffmpeg_export_cmd=export_cmd,
        )

    except Exception as e:
        return JobResult(key=key, success=False, message=f"Erreur: {e}")


def process_episode_vostfr_to_vf(job: EpisodeJob) -> JobResult:
    key = job.key
    try:
        # base = VF, donor = VOSTFR
        vf_json = ffprobe_json(job.base_path)
        vostfr_json = ffprobe_json(job.donor_path)
        vf_ms = parse_media_streams(vf_json)
        vostfr_ms = parse_media_streams(vostfr_json)

        # From donor, get VO JPN
        vo_jpn_idx = find_first_jpn_audio_index(vostfr_ms)
        if vo_jpn_idx is None:
            return JobResult(key=key, success=False, message=f"Aucune piste VO (JPN) dans VOSTFR: {job.donor_path}")
        # From base, get FR
        fr_idx = select_fr_audio_stream(vf_ms)
        if fr_idx is None:
            return JobResult(key=key, success=False, message=f"Aucune piste FR dans VF: {job.base_path}")

        will_speedfix = decide_speedfix(vf_ms, vostfr_ms, job.no_speedfix)
        channels = vostfr_ms.audio_channels.get(vo_jpn_idx, 2)

        if job.out_path.exists() and not job.force:
            return JobResult(key=key, success=False, message=f"Sortie existe déjà (utilisez --force): {job.out_path}")

        use_preproc = will_speedfix or (job.offset_ms != 0)
        tmp_audio_path = None
        preproc_cmd = None
        if use_preproc:
            rc, tmp_audio_path, preproc_cmd = preproc_audio_to_temp_flac(
                input_path=job.donor_path,
                abs_stream_index=vo_jpn_idx,
                out_dir=job.out_path.parent,
                key=key,
                offset_ms=job.offset_ms,
                apply_speedfix=will_speedfix,
                channels=channels,
                dry_run=job.dry_run,
            )
            if rc != 0 or tmp_audio_path is None:
                return JobResult(key=key, success=False, message=f"Echec prétraitement audio VO pour {key}", ffmpeg_preproc_cmd=preproc_cmd)
            donor_audio = tmp_audio_path
        else:
            donor_audio = job.donor_path

        mux_cmd = build_mux_command_vostfr_to_vf(
            vf_path=job.base_path,
            vostfr_audio_or_input=donor_audio,
            use_temp_processed_audio=use_preproc,
            vo_jpn_stream_index_in_vostfr=vo_jpn_idx if not use_preproc else None,
            fr_stream_index_in_vf=fr_idx,
            vostfr_ms=vostfr_ms,
            out_path=job.out_path,
        )

        job.out_path.parent.mkdir(parents=True, exist_ok=True)
        rc = run_subprocess(mux_cmd, dry_run=job.dry_run)
        if rc != 0:
            return JobResult(
                key=key, success=False, message=f"Echec mux pour {key}", ffmpeg_mux_cmd=mux_cmd,
                ffmpeg_preproc_cmd=preproc_cmd, chosen_fr_stream_index=fr_idx, vo_jpn_stream_index=vo_jpn_idx,
                speedfix_applied=will_speedfix, offset_applied_ms=job.offset_ms,
            )

        return JobResult(
            key=key, success=True, message=f"OK: {job.out_path.name}", ffmpeg_mux_cmd=mux_cmd,
            ffmpeg_preproc_cmd=preproc_cmd, chosen_fr_stream_index=fr_idx, vo_jpn_stream_index=vo_jpn_idx,
            speedfix_applied=will_speedfix, offset_applied_ms=job.offset_ms, output_path=job.out_path,
        )

    except Exception as e:
        return JobResult(key=key, success=False, message=f"Erreur: {e}")


def run_batch(
    direction: str,
    dir_a: Path,
    dir_b: Path,
    out_dir: Path,
    offsets_map: dict[str, int],
    workers: int,
    force: bool,
    dry_run: bool,
    no_speedfix: bool,
    relax_extract: bool,
    export_vf_audio: bool = False,
    export_audio_dir: Path | None = None,
    default_vf: bool = False,
    force_audio_preproc: bool = False,
) -> int:
    """
    Run batch processing.
    direction: one of Direction.*
    For vf_to_vostfr: base = VOSTFR (dir_a), donor = VF (dir_b)
    For vostfr_to_vf: base = VF (dir_a), donor = VOSTFR (dir_b)
    Returns process exit code.
    """
    check_dependencies()

    pairs = build_pairs(dir_a, dir_b, relax=relax_extract)
    if not pairs:
        print("Aucun appariement trouvé via motif EXX.")
        return 1

    jobs: List[EpisodeJob] = []
    def _derive_out(stem: str) -> str:
        # Remplace VF/VOSTFR (insensible à la casse) par MULTi dans le nom
        s = re.sub(r"(?i)\bVOSTFR\b", "MULTi", stem)
        s = re.sub(r"(?i)\bVF\b", "MULTi", s)
        return s

    for key, a_path, b_path in pairs:
        offset_ms = offsets_map.get(key, 0)
        if direction == Direction.VF_TO_VOSTFR:
            base_path = a_path  # VOSTFR
            donor_path = b_path  # VF
            out_path = out_dir / f"{_derive_out(base_path.stem)}.mkv"
        else:
            base_path = a_path  # VF
            donor_path = b_path  # VOSTFR
            out_path = out_dir / f"{_derive_out(base_path.stem)}.mkv"
        jobs.append(EpisodeJob(
            key=key,
            base_path=base_path,
            donor_path=donor_path,
            out_path=out_path,
            offset_ms=offset_ms,
            dry_run=dry_run,
            force=force,
            no_speedfix=no_speedfix,
            export_vf_audio=export_vf_audio,
            export_audio_dir=export_audio_dir,
            force_audio_preproc=force_audio_preproc,
        ))

    print(f"Jobs: {len(jobs)} épisodes appariés.")
    for key, a_path, b_path in pairs:
        print(f"- {key}: A={a_path} | B={b_path}")

    results: List[JobResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        if direction == Direction.VF_TO_VOSTFR:
            futmap = {executor.submit(process_episode_vf_to_vostfr, job): job for job in jobs}
        else:
            futmap = {executor.submit(process_episode_vostfr_to_vf, job): job for job in jobs}
        for fut in concurrent.futures.as_completed(futmap):
            res = fut.result()
            print(f"[{res.key}] {'SUCCÈS' if res.success else 'ÉCHEC'} - {res.message}")
            if res.ffmpeg_preproc_cmd:
                print(f"[{res.key}] ffmpeg (prétraitement): {shell_quote_cmd(res.ffmpeg_preproc_cmd)}")
            if res.ffmpeg_mux_cmd:
                print(f"[{res.key}] ffmpeg (mux): {shell_quote_cmd(res.ffmpeg_mux_cmd)}")
            results.append(res)

    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    print(f"Terminé. Succès: {ok} | Échecs: {fail}")
    return 0 if fail == 0 else 1
