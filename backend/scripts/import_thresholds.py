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

# dual-head는 운영점 이름을 그대로 쓴다 (default / demo_relaxed).
DEFAULT_SOURCE = BACKEND_DIR / "ai" / "thresholds.json"
TARGET = BACKEND_DIR / "app" / "default_thresholds.json"


def convert(source: dict) -> dict:
    """AI 릴리스 thresholds.json → 백엔드 시드 형식.

    dual-head는 운영점 하나가 user/gesture 두 임계값을 갖는다. 백엔드는 이를
    두 행(gate=user, gate=gesture)으로 저장하고 basis로 묶어 전환한다.
    """
    operating_points = source.get("operating_points")
    if not isinstance(operating_points, dict) or not operating_points:
        raise SystemExit("operating_points가 없습니다. 릴리스 형식을 확인하세요.")

    points = []
    for basis, point in operating_points.items():
        if "user_threshold" not in point or "gesture_threshold" not in point:
            raise SystemExit(f"운영점 '{basis}'에 user/gesture 임계값이 모두 있어야 합니다.")
        points.append(
            {
                "basis": basis,
                "userThreshold": float(point["user_threshold"]),
                "gestureThreshold": float(point["gesture_threshold"]),
                "userFar": point.get("user_validation_far"),
                "userFrr": point.get("user_validation_frr"),
                "gestureFar": point.get("gesture_validation_far"),
                "gestureFrr": point.get("gesture_validation_frr"),
                "source": point.get("source"),
            }
        )
    selected = source.get("selected_operating_point", points[0]["basis"])
    return {
        "source": (
            f"ai_release/thresholds.json ({source.get('release')}), "
            f"규칙={source.get('decision_rule')}"
        ),
        "modelVersion": source.get("release"),
        "scheme": "global",
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
        print(
            f"  {p['basis']:13} Tu={p['userThreshold']!r:22} Tg={p['gestureThreshold']!r:22}{active}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
