"""좌우 반전 확인 (SPEC 4.2). 반드시 분석 전에 실행한다.

촬영 가이드상 전원 오른손·손바닥이 카메라를 향한다.
  handedness == "Right" → 원본 저장 폰 (mirror_flip = false)
  handedness == "Left"  → 좌우 반전 저장 폰 (mirror_flip = true)

판정 결과를 configs/paths.json의 mirror_flip에 기록한다.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401
from core.landmark_io import load_clip, load_paths, load_json, save_json

REFERENCE_ACTION = "OPEN_PALM"
REFERENCE_CONDITION = "near"


def main() -> int:
    paths = load_paths()
    cache_dir = Path(paths["landmark_cache"])
    files = sorted(cache_dir.glob("*.npz"))
    if not files:
        print("랜드마크 캐시가 없다. 먼저 01_extract_landmarks.py를 실행할 것.", file=sys.stderr)
        return 1

    per_participant: dict[str, Counter] = {}
    lines: list[str] = []

    for path in files:
        clip = load_clip(path)  # 반전 판정 전이므로 정렬하지 않은 원본을 본다
        if clip.meta.action != REFERENCE_ACTION or clip.meta.condition != REFERENCE_CONDITION:
            continue
        labels = clip.handedness[clip.valid_mask]
        counter = Counter(labels.tolist())
        per_participant.setdefault(clip.meta.participant, Counter()).update(counter)
        lines.append(f"  {clip.meta.stem}: {dict(counter)} "
                     f"(검출 {clip.valid_mask.sum()}/{clip.num_frames})")

    if not per_participant:
        print(f"{REFERENCE_ACTION}_{REFERENCE_CONDITION} 영상을 찾지 못했다.", file=sys.stderr)
        return 1

    print(f"기준 영상: {REFERENCE_ACTION}_{REFERENCE_CONDITION}")
    for line in lines:
        print(line)

    mirror_flip: dict[str, bool] = {}
    flicker: dict[str, float] = {}
    print("\n=== 참가자별 판정 ===")
    for participant, counter in sorted(per_participant.items()):
        total = sum(counter.values())
        majority, majority_n = counter.most_common(1)[0]
        minority_ratio = 1.0 - majority_n / total if total else 0.0
        flip = (majority == "Left")
        mirror_flip[participant] = flip
        flicker[participant] = round(minority_ratio, 4)
        print(f"  {participant}: 다수결 handedness={majority} "
              f"({majority_n}/{total}, 흔들림 {minority_ratio * 100:.2f}%) "
              f"→ mirror_flip={str(flip).lower()}")
        if minority_ratio > 0:
            print(f"    [주의] {participant}는 프레임마다 handedness가 흔들린다 "
                  f"({minority_ratio * 100:.2f}%). 리포트에 기록됨.")

    if len(set(mirror_flip.values())) > 1:
        print("\n" + "!" * 70, file=sys.stderr)
        print("!! 경고: 참가자별 좌우 반전 여부가 서로 다르다.", file=sys.stderr)
        print(f"!! {mirror_flip}", file=sys.stderr)
        print("!! 정렬하지 않으면 좌우 이동 판정이 통째로 뒤집힌다.", file=sys.stderr)
        print("!" * 70 + "\n", file=sys.stderr)
    else:
        print("\n두 참가자의 반전 여부가 동일하다.")

    cfg_path = paths["_config_path"]
    cfg = load_json(cfg_path)
    cfg["mirror_flip"] = mirror_flip
    cfg["mirror_flip_flicker_ratio"] = flicker
    cfg["mirror_flip_source"] = (
        f"{REFERENCE_ACTION}_{REFERENCE_CONDITION} 영상 handedness 다수결 "
        f"(오른손 촬영 가이드 기준, Left→반전 저장)"
    )
    save_json(cfg_path, cfg)
    print(f"configs/paths.json에 기록: mirror_flip={mirror_flip}")

    report_dir = Path(paths["report_out"])
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "mirror_check.txt", "w", encoding="utf-8") as f:
        f.write(f"기준 영상: {REFERENCE_ACTION}_{REFERENCE_CONDITION}\n")
        f.write("\n".join(lines) + "\n\n")
        for participant, counter in sorted(per_participant.items()):
            f.write(f"{participant}: {dict(counter)} → mirror_flip="
                    f"{str(mirror_flip[participant]).lower()}, "
                    f"handedness 흔들림 {flicker[participant] * 100:.2f}%\n")
    print(f"리포트: {report_dir / 'mirror_check.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
