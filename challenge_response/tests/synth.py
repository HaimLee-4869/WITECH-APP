"""합성 랜드마크 생성기 (실제 영상 없이 테스트하기 위함).

손 모델: 손목(0)이 원점, 손가락은 -y 방향(화면 위쪽)으로 뻗는다.
각 손가락은 (MCP, PIP, TIP)의 사잇각을 지정한 값으로 정확히 만들 수 있다.
"""
from __future__ import annotations

import numpy as np

from core.geometry import FINGER_JOINTS, FINGER_NAMES

# 손가락별 MCP 위치(손 크기 1 기준). 임계값이 아니라 손 구조 상수다.
_MCP_X = {"thumb": -0.7, "index": -0.35, "middle": 0.0, "ring": 0.3, "pinky": 0.6}
_MCP_Y = {"thumb": -0.5, "index": -1.0, "middle": -1.0, "ring": -0.95, "pinky": -0.85}
_SEG1 = 0.45   # MCP -> PIP 길이
_SEG2 = 0.55   # PIP -> TIP 길이
# MCP-PIP-TIP 사이에 낀 나머지 랜드마크(DIP 등)는 보간해서 채운다.
_EXTRA = {"thumb": 3, "index": 7, "middle": 11, "ring": 15, "pinky": 19}


def make_hand(angles=180.0, scale: float = 1.0,
              center: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> np.ndarray:
    """손가락별 관절 각도(도)를 지정해 (21,3) 랜드마크를 만든다.

    angles: 손가락 이름 -> 각도인 dict, 또는 전 손가락 공통 float.
    """
    if not isinstance(angles, dict):
        angles = {name: float(angles) for name in FINGER_NAMES}

    lm = np.zeros((21, 3), dtype=np.float64)
    for name in FINGER_NAMES:
        mcp_i, pip_i, tip_i = FINGER_JOINTS[name]
        mcp = np.array([_MCP_X[name], _MCP_Y[name], 0.0])
        pip = mcp + np.array([0.0, -_SEG1, 0.0])
        # PIP에서 MCP를 향하는 방향은 +y. 이를 지정 각도만큼 돌려 TIP 방향을 만든다.
        theta = np.radians(angles[name])
        direction = np.array([np.sin(theta), np.cos(theta), 0.0])
        tip = pip + direction * _SEG2
        lm[mcp_i], lm[pip_i], lm[tip_i] = mcp, pip, tip
        lm[_EXTRA[name]] = (pip + tip) / 2.0

    lm[0] = np.zeros(3)  # 손목. 엄지 관절(1,2,4)은 위 루프가 채우므로 덮어쓰지 않는다.
    return lm * scale + np.array(center, dtype=np.float64)


def make_pattern_hand(extended: dict, extended_angle: float,
                      curled_angle: float, **kwargs) -> np.ndarray:
    """손가락별 펴짐 여부로 손을 만든다."""
    angles = {name: (extended_angle if extended.get(name, False) else curled_angle)
              for name in FINGER_NAMES}
    return make_hand(angles, **kwargs)


def make_sequence(start: tuple[float, float, float],
                  end: tuple[float, float, float],
                  frames: int,
                  scale: float = 1.0,
                  angles=180.0) -> np.ndarray:
    """start에서 end로 선형 이동하는 (F,21,3) 시퀀스."""
    s, e = np.array(start, float), np.array(end, float)
    return np.stack([
        make_hand(angles, scale=scale,
                  center=tuple(s + (e - s) * (i / max(frames - 1, 1))))
        for i in range(frames)
    ])
