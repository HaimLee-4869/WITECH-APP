"""MediaPipe 21점 구조로 손 뼈대를 그린다.

블록 아이콘은 무엇을 하라는 건지 알아보기 어려웠다. 실제 랜드마크 연결 구조로
손을 그리고, 펴는 손가락은 초록, 접는 손가락은 회색으로 칠한다.

여기 있는 숫자는 전부 **그림용 손 모형**이다. 판정 임계값이 아니다.
판정은 core/hand_action_detector.py가 config의 각도로만 한다.
"""
from __future__ import annotations

import cv2
import numpy as np

from core.geometry import FINGER_NAMES

# MediaPipe 손 랜드마크 연결 (mp.solutions.hands.HAND_CONNECTIONS와 동일).
# mediapipe를 import하지 않고도 그릴 수 있도록 여기 적어둔다.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),            # 엄지
    (0, 5), (5, 6), (6, 7), (7, 8),            # 검지
    (5, 9), (9, 10), (10, 11), (11, 12),       # 중지
    (9, 13), (13, 14), (14, 15), (15, 16),     # 약지
    (13, 17), (17, 18), (18, 19), (19, 20),    # 소지
    (0, 17),                                   # 손바닥 아래쪽
)

# 손가락별 랜드마크 사슬 (MCP -> PIP -> DIP -> TIP)
FINGER_CHAINS = {
    "thumb": (1, 2, 3, 4),
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}
PALM_EDGES = ((0, 5), (5, 9), (9, 13), (13, 17), (0, 17), (0, 1))

# --- 그림용 손 모형 (단위: 손 크기 1 기준, y가 위쪽이 +) ---
_WRIST = (0.0, 0.0)
_MCP = {
    "thumb": (-0.28, 0.20),
    "index": (-0.33, 0.76),
    "middle": (-0.02, 0.83),
    "ring": (0.26, 0.78),
    "pinky": (0.49, 0.66),
}
# 손가락이 뻗는 방향(도). 90이 위쪽. 살짝 벌어지게 부채꼴로 둔다.
_BASE_ANGLE = {"thumb": 143.0, "index": 97.0, "middle": 90.0,
               "ring": 83.0, "pinky": 72.0}
# 마디 길이 (MCP->PIP, PIP->DIP, DIP->TIP)
_SEGMENTS = {
    "thumb": (0.25, 0.19, 0.16),
    "index": (0.29, 0.20, 0.15),
    "middle": (0.32, 0.22, 0.16),
    "ring": (0.29, 0.20, 0.15),
    "pinky": (0.23, 0.16, 0.13),
}
# 접었을 때 각 관절이 손바닥 쪽으로 꺾이는 각도(도).
_CURL_BEND = {
    "thumb": (40.0, 32.0),
    "index": (92.0, 82.0),
    "middle": (92.0, 82.0),
    "ring": (92.0, 82.0),
    "pinky": (92.0, 82.0),
}

PALM_COLOUR = (150, 190, 235)
EXTENDED_COLOUR = (120, 235, 170)
CURLED_COLOUR = (105, 105, 115)
THUMB_COLOUR = (140, 140, 150)
JOINT_COLOUR = (245, 245, 245)
# 이보다 작게 그릴 때는 관절 원을 생략한다. 작은 아이콘에서 뭉개지기 때문이다.
_JOINT_DOT_MIN_PX = 72


def build_hand(extended: dict) -> np.ndarray:
    """손가락별 펴짐 여부로 (21,2) 랜드마크를 만든다. y는 위쪽이 +."""
    points = np.zeros((21, 2), dtype=np.float64)
    points[0] = _WRIST
    for name in FINGER_NAMES:
        chain = FINGER_CHAINS[name]
        position = np.array(_MCP[name], dtype=np.float64)
        points[chain[0]] = position
        angle = _BASE_ANGLE[name]
        bends = (0.0, 0.0) if extended.get(name, False) else _CURL_BEND[name]
        for i, length in enumerate(_SEGMENTS[name]):
            if i > 0:
                angle -= bends[i - 1]
            radians = np.radians(angle)
            position = position + np.array([np.cos(radians), np.sin(radians)]) * length
            points[chain[i + 1]] = position
    return points


def to_pixels(points: np.ndarray, box, margin_ratio: float = 0.10) -> np.ndarray:
    """손 좌표를 (x, y, w, h) 사각형 안에 맞춰 픽셀로 옮긴다. y축을 뒤집는다."""
    x, y, w, h = box
    margin = margin_ratio * min(w, h)
    low, high = points.min(axis=0), points.max(axis=0)
    span = np.maximum(high - low, 1e-6)
    scale = min((w - 2 * margin) / span[0], (h - 2 * margin) / span[1])

    centred = (points - (low + high) / 2.0) * scale
    centre = np.array([x + w / 2.0, y + h / 2.0])
    pixels = np.empty_like(centred)
    pixels[:, 0] = centre[0] + centred[:, 0]
    pixels[:, 1] = centre[1] - centred[:, 1]   # 화면은 아래가 +
    return pixels.astype(np.int32)


def draw_hand(canvas, box, extended: dict, thickness: int = 0,
              joint_radius: int = 0) -> None:
    """손 뼈대를 그린다. extended가 True인 손가락만 초록."""
    points = to_pixels(build_hand(extended), box)
    size = min(box[2], box[3])
    thickness = thickness or max(int(size * (0.035 if size >= _JOINT_DOT_MIN_PX else 0.06)), 2)
    joint_radius = joint_radius or max(int(size * 0.028), 2)

    finger_of = {}
    for name, chain in FINGER_CHAINS.items():
        for index in chain:
            finger_of[index] = name

    def colour_for(a: int, b: int):
        name = finger_of.get(a) or finger_of.get(b)
        if name is None or (a, b) in PALM_EDGES or (b, a) in PALM_EDGES:
            return PALM_COLOUR
        if name == "thumb":
            return THUMB_COLOUR      # 엄지는 판정에서 빠진다 (SPEC 4.6)
        return EXTENDED_COLOUR if extended.get(name, False) else CURLED_COLOUR

    for a, b in HAND_CONNECTIONS:
        cv2.line(canvas, tuple(points[a]), tuple(points[b]), colour_for(a, b),
                 thickness, cv2.LINE_AA)
    if size >= _JOINT_DOT_MIN_PX:
        for index in range(len(points)):
            name = finger_of.get(index)
            if name is None:
                colour = PALM_COLOUR
            elif name == "thumb":
                colour = THUMB_COLOUR
            else:
                colour = EXTENDED_COLOUR if extended.get(name, False) else CURLED_COLOUR
            cv2.circle(canvas, tuple(points[index]), joint_radius, colour, -1, cv2.LINE_AA)
    # 손끝만 밝게 찍어 방향을 알아보기 쉽게 한다.
    for name, chain in FINGER_CHAINS.items():
        if extended.get(name, False) and name != "thumb":
            cv2.circle(canvas, tuple(points[chain[-1]]), joint_radius,
                       JOINT_COLOUR, -1, cv2.LINE_AA)
