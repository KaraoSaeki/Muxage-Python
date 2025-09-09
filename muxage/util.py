from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, Optional


def parse_offsets_csv(csv_path: Optional[Path]) -> Dict[str, int]:
    """Parse offsets CSV in format key,offset_ms where key is E07/E123 etc."""
    offsets: Dict[str, int] = {}
    if not csv_path:
        return offsets
    if not csv_path.exists():
        print(f"Avertissement: offsets CSV introuvable: {csv_path}")
        return offsets
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
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
