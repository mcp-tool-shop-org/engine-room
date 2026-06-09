#!/usr/bin/env python3
"""verify.py — engine-room's single-command verify (gate D1).

Stdlib-only, like the executor it verifies. Runs, in order:

  1. the full `unittest` suite under tests/,
  2. an import smoke of every module in the executor package,
  3. `python -m executor.cli --help` (the CLI entry point actually parses).

Exits non-zero on the first failure and prints a short PASS/FAIL summary.

    python verify.py
"""
from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _hr(title: str) -> None:
    print(f"\n=== {title} ===")


def run_tests() -> bool:
    """Discover and run the unittest suite under tests/."""
    _hr("1/3  unittest discover -s tests")
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT / "tests"), top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    return result.wasSuccessful()


def import_smoke() -> bool:
    """Import every module in the executor package; fail on any ImportError."""
    _hr("2/3  import smoke — every executor module")
    import executor  # noqa: F401  (package import is itself part of the smoke)

    ok = True
    pkg_path = str(ROOT / "executor")
    names = sorted(m.name for m in pkgutil.iter_modules([pkg_path]))
    for name in names:
        mod = f"executor.{name}"
        try:
            importlib.import_module(mod)
            print(f"  ok    {mod}")
        except Exception as ex:  # noqa: BLE001 — smoke wants every failure surfaced
            print(f"  FAIL  {mod}: {ex.__class__.__name__}: {ex}", file=sys.stderr)
            ok = False
    return ok


def cli_help() -> bool:
    """`python -m executor.cli --help` must exit 0 and print usage."""
    _hr("3/3  python -m executor.cli --help")
    proc = subprocess.run(
        [sys.executable, "-m", "executor.cli", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        print(f"  FAIL  --help exited {proc.returncode}", file=sys.stderr)
        return False
    if "usage" not in proc.stdout.lower():
        print(proc.stdout)
        print("  FAIL  --help output missing a usage line", file=sys.stderr)
        return False
    print("  ok    --help prints usage and exits 0")
    return True


def main() -> int:
    steps = [
        ("tests", run_tests),
        ("import-smoke", import_smoke),
        ("cli-help", cli_help),
    ]
    results: dict[str, bool] = {}
    for label, fn in steps:
        try:
            results[label] = fn()
        except Exception as ex:  # noqa: BLE001
            print(f"  FAIL  {label}: {ex.__class__.__name__}: {ex}", file=sys.stderr)
            results[label] = False
        if not results[label]:
            # Stop at the first failing stage — later stages assume earlier ones held.
            break

    _hr("verify summary")
    all_ok = True
    for label, _ in steps:
        if label in results:
            mark = "PASS" if results[label] else "FAIL"
            print(f"  {mark}  {label}")
            all_ok = all_ok and results[label]
        else:
            print(f"  SKIP  {label}  (earlier stage failed)")
            all_ok = False

    print()
    if all_ok:
        print("VERIFY PASS")
        return 0
    print("VERIFY FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
