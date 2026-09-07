"""요청 동작을 그림으로 보여주는 안내 패널.

그림은 판정 규칙에서 직접 만든다. 손 모양은 SHAPE_PATTERNS의 펴짐/굽힘 조합을,
방향은 config의 direction_map을 그대로 쓰므로 판정과 그림이 어긋날 수 없다.
"""
from __future__ import annotations

import cv2
import numpy as np

from core.hand_action_detector import SHAPE_PATTERNS
from core.movement_detector import MIRRORED

PANEL_BG = (40, 40, 40)
PALM = (150, 190, 235)
FINGER_ON = (120, 235, 170)
FINGER_OFF = (90, 90, 100)
THUMB = (120, 120, 130)
ARROW = (60, 200, 240)
TEXT = (235, 235, 235)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# 판정에 쓰는 4손가락 순서 (엄지 제외)
FINGER_ORDER = ("index", "middle", "ring", "pinky")


def screen_direction(action: str, config: dict) -> tuple[int, int]:
    """화면에서 손이 움직여야 하는 방향 (dx, dy). 오른쪽/아래가 +.

    coordinate_frame이 "mirrored"면 판정기가 좌우를 뒤집어 라벨을 돌려주므로,
    화면상 방향은 direction_map의 반대쪽 라벨에서 나온다. 이 함수가 그 계산을
    한 곳에서 처리해 화살표와 판정이 항상 같은 방향을 가리키게 한다.
    """
    movement = config["movement"]
    direction_map = movement["direction_map"]
    partner = {"MOVE_LEFT": "MOVE_RIGHT", "MOVE_RIGHT": "MOVE_LEFT"}
    key = action
    if config.get("coordinate_frame") == MIRRORED:
        key = partner.get(action, action)
    entry = direction_map.get(key)
    if entry is None:
        return 0, 0
    axis, sign = entry[0], int(entry[1])
    screen_sign = -sign if (config.get("coordinate_frame") == MIRRORED
                            and axis == "x") else sign
    return (screen_sign, 0) if axis == "x" else (0, screen_sign)


def draw_hand_icon(canvas, origin, size, extended, thumb_extended=True) -> None:
    """손 모양 아이콘. extended는 [index, middle, ring, pinky] 불리언."""
    x, y = origin
    palm_w, palm_h = int(size * 0.52), int(size * 0.34)
    palm_x = x + (size - palm_w) // 2
    palm_y = y + size - palm_h - int(size * 0.08)
    cv2.rectangle(canvas, (palm_x, palm_y), (palm_x + palm_w, palm_y + palm_h),
                  PALM, -1, cv2.LINE_AA)

    width = max(int(size * 0.075), 3)
    gap = (palm_w - width * len(FINGER_ORDER)) // (len(FINGER_ORDER) + 1)
    long_len, short_len = int(size * 0.40), int(size * 0.12)
    for i, is_up in enumerate(extended):
        fx = palm_x + gap + i * (width + gap)
        length = long_len if is_up else short_len
        colour = FINGER_ON if is_up else FINGER_OFF
        cv2.rectangle(canvas, (fx, palm_y - length), (fx + width, palm_y),
                      colour, -1, cv2.LINE_AA)

    # 엄지는 판정에서 빼므로 회색으로만 그린다 (SPEC 4.6).
    thumb_len = int(size * 0.22) if thumb_extended else int(size * 0.10)
    ty = palm_y + int(palm_h * 0.25)
    cv2.rectangle(canvas, (palm_x - thumb_len, ty), (palm_x, ty + width),
                  THUMB, -1, cv2.LINE_AA)


def draw_arrow(canvas, origin, size, dx, dy) -> None:
    cx, cy = origin[0] + size // 2, origin[1] + size // 2
    reach = int(size * 0.34)
    start = (cx - dx * reach, cy - dy * reach)
    end = (cx + dx * reach, cy + dy * reach)
    cv2.arrowedLine(canvas, start, end, ARROW, max(size // 22, 3),
                    cv2.LINE_AA, tipLength=0.35)


def draw_guide(canvas, action: str, config: dict,
               origin=None, size: int = 150) -> None:
    """요청 동작 1개를 그림으로 그린다."""
    h, w = canvas.shape[:2]
    if origin is None:
        origin = (w - size - 14, 146)
    x, y = origin

    panel = canvas[y:y + size, x:x + size]
    if panel.shape[0] != size or panel.shape[1] != size:
        return
    cv2.addWeighted(panel, 0.25, np.full_like(panel, PANEL_BG, np.uint8),
                    0.75, 0, panel)
    cv2.rectangle(canvas, (x, y), (x + size, y + size), (90, 90, 90), 1)

    if action in SHAPE_PATTERNS:
        draw_hand_icon(canvas, (x, y + int(size * 0.05)), int(size * 0.84),
                       list(SHAPE_PATTERNS[action]))
        caption = "hold this shape"
    else:
        dx, dy = screen_direction(action, config)
        draw_hand_icon(canvas, (x + int(size * 0.16), y + int(size * 0.12)),
                       int(size * 0.62), [True, True, True, True])
        draw_arrow(canvas, (x, y), size, dx, dy)
        caption = "move this way"

    cv2.putText(canvas, caption, (x + 8, y + size - 8), FONT, 0.42, TEXT, 1,
                cv2.LINE_AA)


def draw_next_actions(canvas, actions, current_index: int, config: dict,
                      size: int = 54) -> None:
    """남은 단계를 작은 아이콘으로 미리 보여준다."""
    h, w = canvas.shape[:2]
    y = h - size - 30
    for offset, action in enumerate(actions):
        x = 14 + offset * (size + 10)
        panel = canvas[y:y + size, x:x + size]
        if panel.shape[0] != size or panel.shape[1] != size:
            continue
        shade = 0.75 if offset == current_index else 0.4
        cv2.addWeighted(panel, 1 - shade,
                        np.full_like(panel, PANEL_BG, np.uint8), shade, 0, panel)
        if action in SHAPE_PATTERNS:
            draw_hand_icon(canvas, (x + 6, y + 4), size - 12,
                           list(SHAPE_PATTERNS[action]))
        else:
            dx, dy = screen_direction(action, config)
            draw_arrow(canvas, (x, y), size, dx, dy)
        border = (60, 200, 240) if offset == current_index else (80, 80, 80)
        cv2.rectangle(canvas, (x, y), (x + size, y + size), border,
                      2 if offset == current_index else 1)
