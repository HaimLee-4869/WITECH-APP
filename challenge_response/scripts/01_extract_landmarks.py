"""영상 → MediaPipe 랜드마크 추출 (SPEC 4.1).

    python scripts/01_extract_landmarks.py [--force]

캐시가 이미 있으면 건너뛴다. --force로 재생성.
검출 실패 프레임은 버리지 않고 valid_mask=False로 남긴다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import _bootstrap  # noqa: F401
from core.landmark_io import (HERE, cache_path_for, discover_clips, extract_clip,
                              load_json, load_paths, save_cache)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="캐시가 있어도 다시 추출")
    ap.add_argument("--paths", default=None, help="paths.json 경로")
    args = ap.parse_args()

    paths = load_paths(args.paths)
    mp_settings = load_json(HERE / "configs" / "extraction.json")["mediapipe_hands"]

    clips, warnings = discover_clips(paths["video_root"])
    print(f"video_root = {paths['video_root']}")
    print(f"영상 {len(clips)}개 발견")
    for w in warnings:
        print(f"[경고] 파일명 규칙 불일치: {w}", file=sys.stderr)

    cache_dir = Path(paths["landmark_cache"])
    cache_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    skipped = 0
    for i, (video_path, meta) in enumerate(clips, 1):
        out = cache_path_for(cache_dir, meta.stem)
        if out.exists() and not args.force:
            skipped += 1
            continue
        t0 = time.time()
        try:
            payload = extract_clip(video_path, meta, mp_settings)
        except Exception as exc:  # noqa: BLE001 - 어떤 영상이 실패했는지 남기는 게 중요
            failures.append(f"{meta.stem}: {exc}")
            print(f"[{i}/{len(clips)}] {meta.stem} 실패: {exc}", file=sys.stderr)
            continue
        save_cache(out, payload)
        n = int(payload["valid_mask"].shape[0])
        valid = int(payload["valid_mask"].sum())
        print(f"[{i}/{len(clips)}] {meta.stem}: {n}프레임, 검출 {valid} "
              f"({valid / n * 100:.1f}%), {time.time() - t0:.1f}s")

    print(f"\n건너뜀(캐시 존재) {skipped}개")
    print(f"캐시 총 {len(list(cache_dir.glob('*.npz')))}개 / 영상 {len(clips)}개")
    if failures:
        print("\n=== 추출 실패 목록 ===", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    if warnings:
        print(f"\n파일명 규칙 불일치 {len(warnings)}건 (위 경고 참조)", file=sys.stderr)
    print("실패 파일 없음" if not failures else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
