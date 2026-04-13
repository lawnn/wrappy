#!/usr/bin/env python3
"""Single entrypoint for AI-agent repository verification."""

from __future__ import annotations

import compileall
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(shlex.quote(part) for part in cmd)}")
    completed = subprocess.run(cmd, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    print(f"[verify] repo={ROOT}")

    print("[verify] bytecode compilation")
    if not compileall.compile_dir(ROOT / "wrappy", quiet=1):
        return 1
    if not compileall.compile_dir(ROOT / "tests" / "agent", quiet=1):
        return 1

    print("[verify] unit tests")
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests/agent", "-v"])

    print("[verify] completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
