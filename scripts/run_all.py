"""Full reproduction of every number in README.md / SUBMISSION.md.

    python scripts/run_all.py

Each step's output goes to logs/<step>.txt. The run stops at the first
failure, so later steps never score stale reports. logs/STATUS.txt records
progress and the final result.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
PY = sys.executable

STEPS = [
    ("tests", [PY, "-m", "pytest", "tests", "-q"]),
    ("cli_launch", [PY, "-m", "src.swarm.cli", "--data", "data/moltbook", "--out", "reports"]),
    ("planted", [PY, "scripts/evaluate_planted.py"]),
    ("precision", [PY, "scripts/score_precision.py"]),
    ("early_warning", [PY, "scripts/run_early_warning.py"]),
    ("contagion", [PY, "scripts/run_contagion.py"]),
    ("figures", [PY, "scripts/make_swarm_figures.py"]),
    ("headline", [PY, "scripts/headline_numbers.py"]),
]


def main() -> int:
    LOGS.mkdir(exist_ok=True)
    only = set(sys.argv[1:])  # e.g. `run_all.py contagion figures headline` reruns just those
    for f in LOGS.glob("*.txt"):
        if not only or f.stem in only or f.stem == "STATUS":
            f.unlink()
    status = LOGS / "STATUS.txt"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for name, cmd in STEPS:
        if only and name not in only:
            continue
        t0 = time.perf_counter()
        with open(status, "a", encoding="utf-8") as s:
            s.write(f"start {name}\n")
        with open(LOGS / f"{name}.txt", "w", encoding="utf-8") as out:
            rc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, env=env).returncode
        with open(status, "a", encoding="utf-8") as s:
            s.write(f"{'ok' if rc == 0 else 'FAILED'} {name} rc={rc} {time.perf_counter() - t0:.0f}s\n")
        if rc != 0:
            return rc
    with open(status, "a", encoding="utf-8") as s:
        s.write("DONE\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
