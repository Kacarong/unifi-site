#!/usr/bin/env python3
"""프론트엔드 빌드가 필요한 앱을 빌드한다.

    python scripts/build.py            # 빌드가 필요한 앱 전부
    python scripts/build.py geoglobe   # 특정 앱만
    python scripts/build.py --list     # 어떤 앱이 어떤 상태인지만 보기
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from server.registry import AppSpec, discover  # noqa: E402


def build_one(spec: AppSpec) -> bool:
    if not spec.build:
        print(f"· {spec.id}: 빌드 설정 없음 — 건너뜀")
        return True

    cwd = os.path.join(spec.dir, spec.build.cwd)
    for label, command in (("설치", spec.build.install), ("빌드", spec.build.command)):
        if not command:
            continue
        print(f"▶ {spec.id} {label}: {command}  (cwd={os.path.relpath(cwd, ROOT)})")
        result = subprocess.run(command, shell=True, cwd=cwd)
        if result.returncode != 0:
            print(f"✗ {spec.id} {label} 실패 (exit {result.returncode})")
            return False

    print(f"✓ {spec.id} 완료 → {os.path.relpath(spec.static_path or cwd, ROOT)}")
    return True


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    only_list = "--list" in sys.argv[1:]

    specs = discover()
    if args:
        specs = [s for s in specs if s.id in args]
        missing = set(args) - {s.id for s in specs}
        if missing:
            print(f"그런 앱이 없습니다: {', '.join(sorted(missing))}")
            return 1

    if only_list:
        for spec in specs:
            print(f"{spec.id:12s} {spec.status:12s} {'빌드필요' if spec.build else '정적'}")
        return 0

    buildable = [s for s in specs if s.build]
    if not buildable:
        print("빌드할 앱이 없습니다.")
        return 0

    failed = [s.id for s in buildable if not build_one(s)]
    if failed:
        print(f"\n실패: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
