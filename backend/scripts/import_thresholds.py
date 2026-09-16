"""ai_release/thresholds.json → app/default_thresholds.json 변환 (명세 14장 5번).

    cd backend
    python scripts/import_thresholds.py                      # ai/thresholds.json 사용
    python scripts/import_thresholds.py --file <경로> --dry-run

AI팀 파일은 운영점 이름이 `far_1_percent`/`far_5_percent`/`eer`이고 값이 float64 풀 정밀도다.
백엔드는 `far1`/`far5`/`eer`로 쓰므로 여기서 이름만 바꾸고 값은 그대로 옮긴다.

변환 후 서버를 재시작하면 로드된 MODEL_VERSION에 threshold 행이 없을 때 이 파일로 채운다.
이미 그 버전 행이 있으면 건드리지 않는다 (운영 중 바꾼 활성 행을 덮어쓰지 않기 위함).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

BASIS_NAMES = {"far_1_percent": "far1", "eer": "eer", "far_5_percent": "far5"}
DEFAULT_SOURCE = BACKEND_DIR / "ai" / "thresholds.json"
TARGET = BACKEND_DIR / "app" / "default_thresholds.json"


def convert(source: dict) -> dict:
    points = []
    for release_name, basis in BASIS_NAMES.items():
        point = source["operating_points"].get(release_name)
        if point is None:
            raise SystemExit(f"운영점 '{release_name}'이 파일에 없습니다.")
        validation = point.get("validation", {})
        points.append(
            {
                "basis": basis,
                "value": float(point["threshold"]),
                "far": validation.get("far"),
                "frr": validation.get("frr"),
                "releaseName": release_name,
            }
        )
    selected = BASIS_NAMES.get(source.get("selected_operating_point"), "far1")
    return {
        "source": (
            f"ai_release/thresholds.json ({source.get('model_version')}), "
            f"scheme={source.get('scheme')}, 선택 운영점={source.get('selected_operating_point')}"
        ),
        "modelVersion": source.get("model_version"),
        "scheme": source.get("scheme", "global"),
        "defaultBasis": selected,
        "operatingPoints": points,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", default=str(TARGET))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    source = json.loads(Path(args.file).read_text(encoding="utf-8"))
    converted = convert(source)
    text = json.dumps(converted, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(text)
        return 0
    Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    print(f"{args.file} → {args.out}")
    for p in converted["operatingPoints"]:
        active = " (기본 활성)" if p["basis"] == converted["defaultBasis"] else ""
        print(f"  {p['basis']:5} {p['value']!r:22} FAR={p['far']} FRR={p['frr']}{active}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
