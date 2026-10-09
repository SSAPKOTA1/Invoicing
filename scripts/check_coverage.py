"""Fail when coverage of an area is below its threshold (reads coverage.xml)."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

AREAS = {
    "services/ledger/": 90.0,
    "repositories/": 80.0,
    "database/": 80.0,
    "ai/": 80.0,
    "services/": 80.0,
}


def main(path: str) -> int:
    root = ET.parse(path).getroot()
    stats: dict[str, list[int]] = {a: [0, 0] for a in AREAS}
    for cls in root.iter("class"):
        filename = cls.get("filename", "").replace("\\", "/")
        lines = cls.find("lines")
        if lines is None:
            continue
        total = len(lines.findall("line"))
        hit = sum(1 for ln in lines.findall("line") if int(ln.get("hits", "0")) > 0)
        for area in AREAS:
            if f"/{area}" in f"/{filename}":
                stats[area][0] += hit
                stats[area][1] += total
    failed = False
    for area, minimum in AREAS.items():
        hit, total = stats[area]
        pct = 100.0 * hit / total if total else 0.0
        status = "ok" if pct >= minimum else "FAIL"
        print(f"{area:<18} {pct:6.1f} %  (min {minimum:.0f} %)  {status}")
        failed |= pct < minimum
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(Path("coverage.xml"))))
