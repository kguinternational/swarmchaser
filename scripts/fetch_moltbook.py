"""Download a slice of the public Moltbook Observatory Archive (MIT licence).

Source: https://huggingface.co/datasets/SimulaMet/moltbook-observatory-archive
Citation: Gautam, S. & Riegler, M. A. (2026). Moltbook Observatory Archive.

Files are date-partitioned Parquet. By default we pull the platform's launch
window (27 Jan - 02 Feb 2026), which is when the first large agent swarms
(token-mint spam, templated "check-in" posts) appeared.

Usage:
    python scripts/fetch_moltbook.py                      # launch window, posts + agents
    # second window with comments (well covered from 08 Feb), used by the
    # contagion analysis:
    python scripts/fetch_moltbook.py --start 2026-02-08 --end 2026-02-10 \
        --tables posts,comments,agents --out data/moltbook_feb
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date, timedelta
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

REPO = "SimulaMet/moltbook-observatory-archive"
OUT = Path(__file__).resolve().parent.parent / "data" / "moltbook"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-27")
    ap.add_argument("--end", default="2026-02-02")
    ap.add_argument("--tables", default="posts,agents")
    ap.add_argument("--out", default=str(OUT), help="destination directory")
    args = ap.parse_args()
    out_root = Path(args.out)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    available = {s.rfilename for s in HfApi().dataset_info(REPO).siblings}

    for table in args.tables.split(","):
        dest = out_root / table
        dest.mkdir(parents=True, exist_ok=True)
        for d in daterange(start, end):
            name = f"data/{table}/{d.isoformat()}.parquet"
            target = dest / f"{d.isoformat()}.parquet"
            if name not in available:
                continue
            if target.exists():
                print("cached ", name)
                continue
            p = hf_hub_download(REPO, name, repo_type="dataset")
            shutil.copyfile(p, target)
            print("fetched", name, target.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
