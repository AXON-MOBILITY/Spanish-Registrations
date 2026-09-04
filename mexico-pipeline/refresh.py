"""Refresh the Mexico (RAIAVL / INEGI) dashboard data served at /mx.

Runs the full pipeline (ported from the standalone Mexico-Registrations repo)
and copies the generated JSON into ../public/mx/data/, which the gated
/mx/index.html reads directly. No build step on Vercel -- commit + push and the
static page picks it up.

    python mexico-pipeline/refresh.py

INEGI publishes new RAIAVL figures ~mid-to-late each month (for the previous
month) and revises preliminary numbers in later releases, so a re-run always
re-downloads everything.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PIPE = Path(__file__).resolve().parent
SCRIPTS = PIPE / "scripts"
GENERATED = PIPE / "public" / "data"
DEST = PIPE.parent / "public" / "mx" / "data"

STEPS = [
    "download_inegi.py",
    "process_data.py",
    "process_export_data.py",
    "process_production_data.py",
    "build_dashboard_data.py",
]
ARTIFACTS = [
    "records.json", "meta.json",
    "records_export.json", "meta_export.json",
    "records_production.json", "meta_production.json",
]


def main() -> int:
    for step in STEPS:
        print(f"\n=== {step} ===", flush=True)
        rc = subprocess.run([sys.executable, "-u", str(SCRIPTS / step)], cwd=str(PIPE)).returncode
        if rc != 0:
            print(f"FAILED at {step} (exit {rc})", file=sys.stderr)
            return rc

    DEST.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACTS:
        src = GENERATED / name
        if not src.exists():
            print(f"missing generated artifact: {src}", file=sys.stderr)
            return 1
        shutil.copy2(src, DEST / name)
        print(f"  copied {name} -> {DEST / name}")

    print("\nMexico data refreshed. Review, then commit public/mx/data/ and push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
