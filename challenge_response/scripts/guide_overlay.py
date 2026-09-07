"""요청 동작을 그림으로 보여주는 안내 패널.

그림은 판정 규칙에서 직접 만든다. 손 모양은 SHAPE_PATTERNS의 펴짐/굽힘 조합을,
방향은 config의 direction_map을 그대로 쓰므로 판정과 그림이 어긋날 수 없다.
손은 MediaPipe 21점 연결 구조로 그린다 (hand_sketch.py).
"""
from __future__ import annotations

import cv2
import numpy as np

import hand_sketch
from core.geometry import NON_THUMB_FINGERS
from core.hand_action_detector import SHAPE_PATTERNS
from core.movement_detector import MIRRORED

PANEL_BG = (40, 40, 40)
ARROW = (60, 200, 240)
TEXT = (235, 235, 235)
HIGHLIGHT = (60, 200, 240)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# 이동 안내에 쓰는 손 모양: 편 손 (SPEC의 MOVE_* 촬영과 같다)
MOVING_HAND = {name: True for name in NON_THUMB_FINGERS}


def extended_for(action: str) -> dict:
    """동작 이름 -> 손가락별 펴짐 여부. 판정 패턴 표에서 그대로 가져온다."""
    pattern = SHAPE_PATTERNS.get(action)
    if pattern is None:
        return dict(MOVING_HAND)
    extended = dict(zip(NON_THUMB_FINGERS, pattern))
    # 엄지는 판정에서 빼므로 그림에서도 회색이다. OPEN_PALM에서만 펴서 그린다.
    extended["thumb"] = (action == "OPEN_PALM")
    return extended


def screen_direction(action: str, config: dict) -> tuple[int, int]:
    """화면에서 손이 움직여야 하는 방향 (dx, dy). 오른쪽/아래가 +.

    coordinate_frame이 "mirrored"면 판정기가 좌우를 뒤집어 라벨을 돌려주므로,
    화면상 방향은 direction_map의 반대쪽 라벨에서 나온다. 이 함수가 그 계산을
    한 곳에서 처리해 화살표와 판정이 항상 같은 방향을 가리키게 한다.
    """
    movement = config["movement"]
    direction_map = movement["direction_map"]
    partner = {"MOVE_LEFT": "MOVE_RIGHT", "MOVE_RIGHT": "MOVE_LEFT"}
    mirrored = config.get("coordinate_frame") == MIRRORED
    key = partner.get(action, action) if mirrored else action
    entry = direction_map.get(key)
    if entry is None:
        return 0, 0
    axis, sign = entry[0], int(entry[1])
    screen_sign = -sign if (mirrored and axis == "x") else sign
    return (screen_sign, 0) if axis == "x" else (0, screen_sign)


def _panel(canvas, x, y, w, h) -> bool:
    region = canvas[y:y + h, x:x + w]
    if region.shape[0] != h or region.shape[1] != w:
        return False
    cv2.addWeighted(region, 0.25, np.full_like(region, PANEL_BG, np.uint8),
                    0.75, 0, region)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (90, 90, 90), 1)
    return True


def draw_arrow(canvas, box, dx, dy, thickness=0) -> None:
    """상자 안에 이동 방향 화살표를 그린다."""
    x, y, w, h = box
    cx, cy = x + w // 2, y + h // 2
    reach = int(min(w, h) * 0.42)
    start = (cx - dx * reach, cy - dy * reach)
    end = (cx + dx * reach, cy + dy * reach)
    thickness = thickness or max(int(min(w, h) * 0.09), 3)
    cv2.arrowedLine(canvas, start, end, ARROW, thickness, cv2.LINE_AA, tipLength=0.32)


def draw_guide(canvas, action: str, config: dict,
               origin=None, size: int = 150) -> None:
    """요청 동작 1개를 그림으로 그린다."""
    h, w = canvas.shape[:2]
    if origin is None:
        origin = (w - size - 14, 146)
    x, y = origin
    if not _panel(canvas, x, y, size, size):
        return

    if action in SHAPE_PATTERNS:
        hand_sketch.draw_hand(canvas, (x, y + int(size * 0.02),
                                       size, int(size * 0.82)),
                              extended_for(action))
        caption = "hold this shape"
    else:
        dx, dy = screen_direction(action, config)
        # 손은 화살표 반대쪽에 두어 '이쪽에서 저쪽으로' 가 읽히게 한다.
        hand_box = (x + int(size * 0.06) - dx * int(size * 0.16),
                    y + int(size * 0.04) - dy * int(size * 0.12),
                    int(size * 0.56), int(size * 0.56))
        hand_sketch.draw_hand(canvas, hand_box, MOVING_HAND)
        draw_arrow(canvas, (x, y + int(size * 0.06), size, int(size * 0.74)), dx, dy)
        caption = "move this way"

    cv2.putText(canvas, caption, (x + 8, y + size - 8), FONT, 0.42, TEXT, 1,
                cv2.LINE_AA)


def draw_next_actions(canvas, actions, current_index: int, config: dict,
                      size: int = 62) -> None:
    """남은 단계를 작은 아이콘으로 미리 보여준다."""
    h = canvas.shape[0]
    y = h - size - 30
    for offset, action in enumerate(actions):
        x = 14 + offset * (size + 10)
        region = canvas[y:y + size, x:x + size]
        if region.shape[0] != size or region.shape[1] != size:
            continue
        shade = 0.75 if offset == current_index else 0.45
        cv2.addWeighted(region, 1 - shade,
                        np.full_like(region, PANEL_BG, np.uint8), shade, 0, region)

        if action in SHAPE_PATTERNS:
            hand_sketch.draw_hand(canvas, (x + 3, y + 3, size - 6, size - 6),
                                  extended_for(action))
        else:
            dx, dy = screen_direction(action, config)
            hand_sketch.draw_hand(canvas, (x + 2, y + 2, int(size * 0.5),
                                           int(size * 0.5)), MOVING_HAND)
            draw_arrow(canvas, (x, y, size, size), dx, dy,
                       thickness=max(size // 16, 2))

        border = HIGHLIGHT if offset == current_index else (80, 80, 80)
        cv2.rectangle(canvas, (x, y), (x + size, y + size), border,
                      2 if offset == current_index else 1)
