#!/usr/bin/env python3
"""Single entrypoint for AI-agent repository verification."""

from __future__ import annotations

import compileall
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(shlex.quote(part) for part in cmd)}")
    completed = subprocess.run(cmd, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def run_in_env(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print(f"$ {' '.join(shlex.quote(part) for part in cmd)}")
    completed = subprocess.run(cmd, cwd=cwd, env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def verify_installed_package() -> None:
    with tempfile.TemporaryDirectory(prefix="wrappy-agent-verify-") as tmp:
        tmp_path = Path(tmp)
        source_copy = tmp_path / "source"
        install_target = tmp_path / "site"
        shutil.copytree(
            ROOT,
            source_copy,
            ignore=shutil.ignore_patterns(
                ".git",
                ".idea",
                ".pytest_cache",
                ".mypy_cache",
                "__pycache__",
                "*.pyc",
                "venv",
                "build",
                "dist",
                "*.egg-info",
            ),
        )
        install_target.mkdir(parents=True, exist_ok=True)

        print("[verify] local package install smoke")
        run_in_env(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-build-isolation",
                "--no-deps",
                "--target",
                str(install_target),
                ".",
            ],
            cwd=source_copy,
            env=dict(os.environ),
        )

        env = dict(os.environ)
        env["PYTHONPATH"] = str(install_target)
        smoke = (
            "import wrappy\n"
            "ns = {}\n"
            "exec('from wrappy import *', ns, ns)\n"
            "assert ns['BitFlyer'] is not None\n"
            "from wrappy.lighter import markets\n"
            "assert markets.index_of('ETH') == 0\n"
            "print('installed-import-ok', wrappy.__version__)\n"
        )
        run_in_env([sys.executable, "-c", smoke], cwd=tmp_path, env=env)


def main() -> int:
    print(f"[verify] repo={ROOT}")

    print("[verify] bytecode compilation")
    if not compileall.compile_dir(ROOT / "wrappy", quiet=1):
        return 1
    if not compileall.compile_dir(ROOT / "tests" / "agent", quiet=1):
        return 1

    print("[verify] unit tests")
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests/agent", "-v"])

    verify_installed_package()

    print("[verify] completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
