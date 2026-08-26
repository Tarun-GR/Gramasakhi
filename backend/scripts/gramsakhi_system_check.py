#!/usr/bin/env python3
"""Run from backend/:  .venv/Scripts/python.exe scripts/gramsakhi_system_check.py"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.system_check import format_system_check_text, run_system_check  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    report = run_system_check()
    print(format_system_check_text(report))
    print()
    cfg = report.get("safe_config") or {}
    print("Safe config:")
    for k, v in cfg.items():
        print(f"  {k}: {v}")
    return 0 if report.get("overall") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
