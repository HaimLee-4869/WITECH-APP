"""영상 → 랜드마크 추출과 캐시 입출력.

- 손이 검출되지 않은 프레임도 버리지 않고 valid_mask=False로 남긴다. (SPEC 4.1)
- 읽을 때 paths.json의 mirror_flip을 보고 x -> 1-x로 정렬한다. (SPEC 4.2)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .naming import ClipMeta, ParseError, parse_stem

NUM_LANDMARKS = 21
COORDS = 3

HERE = Path(__file__).resolve().parent.parent


def load_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_paths(config_path: str | Path | None = None) -> dict:
    cfg_path = Path(config_path) if config_path else HERE / "configs" / "paths.json"
    cfg = load_json(cfg_path)
    cfg["_config_path"] = str(cfg_path)
    for key in ("landmark_cache", "session_out", "report_out"):
        if key in cfg:
            cfg[key] = str((HERE / cfg[key]).resolve())
    return cfg


def discover_clips(video_root: str | Path) -> tuple[list[tuple[Path, ClipMeta]], list[str]]:
    """영상을 찾아 (경로, 메타) 목록과 파싱 실패 경고 목록을 돌려준다."""
    root = Path(video_root)
    if not root.exists():
        raise FileNotFoundError(f"video_root가 없음: {root}")

    clips: list[tuple[Path, ClipMeta]] = []
    warnings: list[str] = []
    for path in sorted(root.rglob("*.mp4")):
        try:
            clips.append((path, parse_stem(path.stem)))
        except ParseError as exc:
            warnings.append(f"{path}: {exc}")
    return clips, warnings


@dataclass
class ClipLandmarks:
    """캐시에서 읽어온 한 영상의 랜드마크 (mirror 정렬 적용 여부 포함)."""
    meta: ClipMeta
    landmarks: np.ndarray        # (F, 21, 3) 정규화 좌표
    world_landmarks: np.ndarray  # (F, 21, 3) 미터 단위 3D
    valid_mask: np.ndarray       # (F,) bool
    handedness: np.ndarray       # (F,) "Left"/"Right"/""
    detection_score: np.ndarray  # (F,) float
    fps: float
    width: int
    height: int
    duration_ms: float
    mirrored: bool               # 정렬을 위해 x를 뒤집었는지

    @property
    def num_frames(self) -> int:
        return int(self.landmarks.shape[0])

    @property
    def valid_ratio(self) -> float:
        n = self.num_frames
        return float(self.valid_mask.sum()) / n if n else 0.0


def cache_path_for(cache_dir: str | Path, stem: str) -> Path:
    return Path(cache_dir) / f"{stem}.npz"


def extract_clip(video_path: Path, meta: ClipMeta, mp_settings: dict) -> dict:
    """MediaPipe Hands로 영상 1개를 추출해 npz에 저장할 dict를 만든다."""
    import cv2
    import mediapipe as mp

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없음: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    lms: list[np.ndarray] = []
    world: list[np.ndarray] = []
    valid: list[bool] = []
    hands_label: list[str] = []
    scores: list[float] = []

    empty = np.full((NUM_LANDMARKS, COORDS), np.nan, dtype=np.float32)

    with mp.solutions.hands.Hands(**mp_settings) as hands:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            result = hands.process(frame_rgb)

            if result.multi_hand_landmarks:
                hl = result.multi_hand_landmarks[0]
                lms.append(np.array([[p.x, p.y, p.z] for p in hl.landmark], dtype=np.float32))
                if result.multi_hand_world_landmarks:
                    wl = result.multi_hand_world_landmarks[0]
                    world.append(np.array([[p.x, p.y, p.z] for p in wl.landmark], dtype=np.float32))
                else:
                    world.append(empty.copy())
                cls = result.multi_handedness[0].classification[0]
                hands_label.append(cls.label)
                scores.append(float(cls.score))
                valid.append(True)
            else:
                lms.append(empty.copy())
                world.append(empty.copy())
                hands_label.append("")
                scores.append(float("nan"))
                valid.append(False)
    cap.release()

    n = len(lms)
    duration_ms = (n / fps * 1000.0) if fps > 0 else float("nan")
    return {
        "landmarks": np.stack(lms) if n else np.zeros((0, NUM_LANDMARKS, COORDS), np.float32),
        "world_landmarks": np.stack(world) if n else np.zeros((0, NUM_LANDMARKS, COORDS), np.float32),
        "valid_mask": np.array(valid, dtype=bool),
        "handedness": np.array(hands_label, dtype="<U8"),
        "detection_score": np.array(scores, dtype=np.float32),
        "fps": np.float32(fps),
        "width": np.int32(width),
        "height": np.int32(height),
        "duration_ms": np.float32(duration_ms),
        "participant": meta.participant,
        "action": meta.action,
        "condition": meta.condition if meta.condition is not None else "",
        "index": meta.index,
        "stem": meta.stem,
    }


def save_cache(path: str | Path, payload: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **payload)


def load_clip(path: str | Path, mirror_flip: dict[str, bool] | None = None) -> ClipLandmarks:
    """캐시를 읽는다. mirror_flip이 True인 참가자는 x -> 1-x로 정렬한다."""
    data = np.load(path, allow_pickle=False)
    meta = ClipMeta(
        stem=str(data["stem"]),
        participant=str(data["participant"]),
        action=str(data["action"]),
        condition=str(data["condition"]) or None,
        index=str(data["index"]),
    )
    lm = data["landmarks"].astype(np.float32).copy()
    wl = data["world_landmarks"].astype(np.float32).copy()

    mirrored = bool((mirror_flip or {}).get(meta.participant, False))
    if mirrored and lm.size:
        lm[..., 0] = 1.0 - lm[..., 0]
        wl[..., 0] = -wl[..., 0]

    return ClipLandmarks(
        meta=meta,
        landmarks=lm,
        world_landmarks=wl,
        valid_mask=data["valid_mask"].astype(bool),
        handedness=data["handedness"].astype(str),
        detection_score=data["detection_score"].astype(np.float32),
        fps=float(data["fps"]),
        width=int(data["width"]),
        height=int(data["height"]),
        duration_ms=float(data["duration_ms"]),
        mirrored=mirrored,
    )


def load_all_clips(cache_dir: str | Path,
                   mirror_flip: dict[str, bool] | None = None) -> list[ClipLandmarks]:
    return [load_clip(p, mirror_flip) for p in sorted(Path(cache_dir).glob("*.npz"))]
