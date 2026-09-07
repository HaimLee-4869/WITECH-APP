"""각도·거리·정규화 계산 (SPEC 4.3).

임계값은 하나도 들어있지 않다. 순수 기하 계산만 한다.
"""
from __future__ import annotations

import numpy as np

# 손가락별 (MCP, PIP, TIP) 랜드마크 인덱스. 임계값이 아니라 손 구조 상수다.
FINGER_JOINTS: dict[str, tuple[int, int, int]] = {
    "thumb": (1, 2, 4),
    "index": (5, 6, 8),
    "middle": (9, 10, 12),
    "ring": (13, 14, 16),
    "pinky": (17, 18, 20),
}
FINGER_NAMES = tuple(FINGER_JOINTS.keys())
NON_THUMB_FINGERS = tuple(n for n in FINGER_NAMES if n != "thumb")

WRIST = 0
MIDDLE_MCP = 9
PALM_POINTS = (0, 5, 9, 13, 17)


def to_isotropic(landmarks: np.ndarray, width: int, height: int) -> np.ndarray:
    """정규화 좌표([0,1])를 화면 종횡비가 반영된 등방 좌표(픽셀)로 바꾼다.

    x, y를 그대로 두면 16:9 영상에서 각도가 왜곡된다. MediaPipe의 z는
    x와 대략 같은 스케일이므로 width를 곱한다.
    """
    out = np.asarray(landmarks, dtype=np.float64).copy()
    out[..., 0] *= width
    out[..., 1] *= height
    out[..., 2] *= width
    return out


def angle_at(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """점 b를 꼭짓점으로 하는 a-b-c 사잇각(도). 계산 불가면 nan."""
    a, b, c = np.asarray(a, float), np.asarray(b, float), np.asarray(c, float)
    v1, v2 = a - b, c - b
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if not np.isfinite(n1) or not np.isfinite(n2) or n1 == 0 or n2 == 0:
        return float("nan")
    cos = float(np.dot(v1, v2) / (n1 * n2))
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def finger_angles(landmarks: np.ndarray) -> dict[str, float]:
    """손가락별 MCP-PIP-TIP 사잇각(도). 펴지면 180도에 가깝다."""
    lm = np.asarray(landmarks, dtype=np.float64)
    return {
        name: angle_at(lm[mcp], lm[pip], lm[tip])
        for name, (mcp, pip, tip) in FINGER_JOINTS.items()
    }


def finger_angle_array(landmarks: np.ndarray) -> np.ndarray:
    """finger_angles를 FINGER_NAMES 순서의 (5,) 배열로."""
    ang = finger_angles(landmarks)
    return np.array([ang[n] for n in FINGER_NAMES], dtype=np.float64)


def hand_scale(landmarks: np.ndarray) -> float:
    """손목(0)-중지 MCP(9) 거리. 카메라 거리 정규화 기준."""
    lm = np.asarray(landmarks, dtype=np.float64)
    return float(np.linalg.norm(lm[MIDDLE_MCP] - lm[WRIST]))


def palm_center(landmarks: np.ndarray) -> np.ndarray:
    """손바닥 뼈대(0,5,9,13,17)의 평균. 손끝은 흔들려서 제외한다."""
    lm = np.asarray(landmarks, dtype=np.float64)
    return lm[list(PALM_POINTS)].mean(axis=0)


def sequence_palm_centers(sequence: np.ndarray) -> np.ndarray:
    """(F,21,3) 시퀀스 → (F,3) 손바닥 중심."""
    seq = np.asarray(sequence, dtype=np.float64)
    return seq[:, list(PALM_POINTS), :].mean(axis=1)


def sequence_hand_scales(sequence: np.ndarray) -> np.ndarray:
    """(F,21,3) 시퀀스 → (F,) 손 크기."""
    seq = np.asarray(sequence, dtype=np.float64)
    return np.linalg.norm(seq[:, MIDDLE_MCP, :] - seq[:, WRIST, :], axis=1)


def extension_flags(angles: dict[str, float] | np.ndarray,
                    thumb_threshold: float,
                    other_threshold: float) -> tuple[list[bool], list[float]]:
    """각도 → (펴짐 bool 5개, 임계값과의 여유 5개). 순서는 FINGER_NAMES."""
    if isinstance(angles, dict):
        values = [angles[n] for n in FINGER_NAMES]
    else:
        values = list(np.asarray(angles, dtype=np.float64))

    flags: list[bool] = []
    margins: list[float] = []
    for name, value in zip(FINGER_NAMES, values):
        threshold = thumb_threshold if name == "thumb" else other_threshold
        margin = float(value - threshold)
        flags.append(bool(np.isfinite(value) and margin >= 0.0))
        margins.append(margin if np.isfinite(value) else float("nan"))
    return flags, margins
