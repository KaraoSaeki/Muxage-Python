from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


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
            if re.search(r'\s|"', token):
                token = token.replace('"', '\\"')
                return f'"{token}"'
            return token
        else:
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
