"""
Run every offline test suite (each test_*.py is a standalone script) and print a summary.

    ./.venv/Scripts/python run_tests.py        (Windows)
    ./.venv/bin/python run_tests.py            (Linux / macOS)
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    suites = sorted(HERE.glob("test_*.py"))
    failed = []
    for suite in suites:
        proc = subprocess.run([sys.executable, "-W", "ignore", suite.name], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = proc.stdout + proc.stderr
        counts = re.findall(r"\((\d+)/(\d+)\)|(\d+)/(\d+) PASSED", out)
        summary = next((f"{a or c}/{b or d}" for a, b, c, d in reversed(counts)), "?")
        ok = proc.returncode == 0 and "[FAIL]" not in out
        print(f"{'PASS' if ok else 'FAIL'}  {suite.stem:<28} {summary}")
        if not ok:
            failed.append(suite.stem)
            print("\n".join(out.strip().splitlines()[-15:]))
    print(f"\n{len(suites) - len(failed)}/{len(suites)} suites passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
