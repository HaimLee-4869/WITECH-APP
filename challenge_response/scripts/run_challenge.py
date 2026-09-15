"""실시간 Challenge 프로토타입 (SPEC 4.10).

    python scripts/run_challenge.py [--participant P01] [--camera 0]
                                    [--capture 1280x720] [--window-height 900]

키 조작:  q 종료   r 재시작   s 참가자 ID 입력

화면은 거울처럼 좌우 반전해 보여주고, 판정도 config의 coordinate_frame에 따라
화면 기준으로 한다. 성공·실패 영상을 모두 저장한다.

화면은 [상단 띠 | 카메라 영상 + 오른쪽 패널 | 하단 띠]로 나눈다. 안내·계측 패널이
카메라 영상을 가리지 않는다. 손이 영상 가장자리에 붙으면 그쪽에 경고를 띄운다.

콘솔에는 결과 요약만 띄우고, 프레임별 판정·단계 이벤트·시도별 상세는
data/sessions/run_YYYYMMDD_HHMMSS.log에 남긴다.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

import _bootstrap  # noqa: F401

from core import features as F  # noqa: E402
from core import geometry as g  # noqa: E402
from core.challenge_generator import generate_challenge, is_shape_action  # noqa: E402
from core.challenge_logger import (RunStats, SessionRecorder,  # noqa: E402
                                   append_result, attempt_report_lines,
                                   threshold_report_lines)
from core.challenge_state_machine import (ChallengeStateMachine,  # noqa: E402
                                          Observation, State)
from core.hand_action_detector import HandActionDetector  # noqa: E402
from core.landmark_io import HERE, load_json, load_paths  # noqa: E402
from core.movement_detector import MovementDetector  # noqa: E402
import guide_overlay  # noqa: E402
import korean_text  # noqa: E402

WHITE, GREEN, RED, YELLOW, GREY = ((255, 255, 255), (80, 220, 120),
                                   (70, 70, 235), (60, 200, 240), (170, 170, 170))
ORANGE = (60, 165, 245)
FONT = cv2.FONT_HERSHEY_SIMPLEX
WINDOW = "Challenge-Response"
# 화면 구성(픽셀). 판정과 무관한 배치 값이다.
TOP_BAND = 132
BOTTOM_BAND = 112
SIDE_PANEL = 344
# 동작 이름은 화면에 크게 띄워야 해서 한글 대신 기호로 표시한다 (OpenCV는 한글 미지원).
ACTION_CAPTION = {
    "OPEN_PALM": "OPEN PALM", "FIST": "FIST", "INDEX": "INDEX (1 finger)",
    "TWO_FINGERS": "TWO FINGERS", "MOVE_LEFT": "MOVE <<< LEFT",
    "MOVE_RIGHT": "MOVE RIGHT >>>", "MOVE_UP": "MOVE UP ^^^",
    "MOVE_DOWN": "MOVE DOWN vvv",
}


def draw_landmarks(frame, landmarks, width, height) -> None:
    """원본 좌표 랜드마크를 거울 화면 위에 그린다 (x -> 1-x)."""
    import mediapipe as mp
    connections = mp.solutions.hands.HAND_CONNECTIONS
    pts = [(int((1.0 - p[0]) * width), int(p[1] * height)) for p in landmarks]
    for a, b in connections:
        cv2.line(frame, pts[a], pts[b], GREY, 2)
    for x, y in pts:
        cv2.circle(frame, (x, y), 3, GREEN, -1)


def draw_move_debug(frame, probe, config, origin=(14, 150)) -> None:
    """이동 판정의 두 관문이 지금 어떤 값인지 그대로 보여준다.

    임계값을 짐작해서 바꾸기 전에, 무엇이 막고 있는지부터 눈으로 본다.
    """
    movement = config["movement"]
    min_disp = movement.get("min_displacement_ratio")
    axis_min = movement.get("axis_dominance_ratio")

    lines = []
    # 윈도우는 프레임 수가 아니라 시간으로 찬다(기준 fps 환산). 담긴 시간/필요 시간.
    # 윈도우가 아직 안 찼는 건 실패가 아니므로 X를 붙이지 않는다.
    lines.append(("window", f"{probe.span_ms:.0f}/{probe.span_needed_ms:.0f}ms "
                            f"({probe.frames_filled}f)",
                  True if probe.window_ready else None))

    if not probe.window_ready:
        lines.append(("gate1 disp", "waiting", None))
        lines.append(("gate2 axis", "waiting", None))
        lines.append(("axis", "-", None))
    else:
        disp = probe.displacement_ratio
        disp_text = ("--" if not np.isfinite(disp)
                     else f"{disp:.2f} / {min_disp:.3f}  x{disp / min_disp:.2f}")
        lines.append(("gate1 disp", disp_text, probe.displacement_ok))

        axis_ratio = probe.axis_ratio
        if not np.isfinite(axis_ratio):
            axis_text = "inf (pure axis)"
        else:
            axis_text = f"{axis_ratio:.2f} / {axis_min:.2f}  x{axis_ratio / axis_min:.2f}"
        lines.append(("gate2 axis", axis_text, probe.axis_ok))

        sign = "+" if probe.sign > 0 else ("-" if probe.sign < 0 else "?")
        lines.append(("axis", f"{probe.axis}{sign}   -> {probe.label}", None))

    pad, line_h, box_w = 10, 20, 300
    box_h = pad * 2 + line_h * len(lines)
    x, y = origin

    panel = frame[y:y + box_h, x:x + box_w]
    if panel.shape[0] != box_h or panel.shape[1] != box_w:
        return
    cv2.addWeighted(panel, 0.2, np.full_like(panel, (30, 30, 30), np.uint8), 0.8, 0, panel)
    cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), (90, 90, 90), 1)

    for i, (label, text, ok) in enumerate(lines):
        base = y + pad + line_h * (i + 1) - 6
        cv2.putText(frame, label, (x + pad, base), FONT, 0.44, GREY, 1, cv2.LINE_AA)
        colour = WHITE if ok is None else (GREEN if ok else RED)
        cv2.putText(frame, text, (x + pad + 92, base), FONT, 0.44, colour, 1, cv2.LINE_AA)
        if ok is not None:
            cv2.putText(frame, "O" if ok else "X", (x + box_w - 24, base),
                        FONT, 0.5, colour, 2, cv2.LINE_AA)


def draw_stats(frame, stats, origin=None) -> None:
    """이번 실행의 사유별 통계. 결과 화면에서만 띄운다."""
    if stats.attempts == 0:
        return
    lines = stats.summary_lines()
    pad, line_h = 10, 19
    box_w = 268
    box_h = pad * 2 + line_h * len(lines)
    x, y = origin if origin is not None else (14, frame.shape[0] - box_h - 96)

    panel = frame[y:y + box_h, x:x + box_w]
    if panel.shape[0] != box_h or panel.shape[1] != box_w:
        return
    cv2.addWeighted(panel, 0.2, np.full_like(panel, (30, 30, 30), np.uint8), 0.8, 0, panel)
    cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), (90, 90, 90), 1)

    for i, text in enumerate(lines):
        colour = WHITE if i == 0 else GREY
        cv2.putText(frame, text, (x + pad, y + pad + line_h * (i + 1) - 6),
                    FONT, 0.42, colour, 1, cv2.LINE_AA)


def compose_canvas(video):
    """[상단 띠 | 영상 + 오른쪽 패널 | 하단 띠] 캔버스와 영상 위치(x, y, w, h)."""
    vh, vw = video.shape[:2]
    canvas = np.full((TOP_BAND + vh + BOTTOM_BAND, vw + SIDE_PANEL, 3), 18, np.uint8)
    canvas[TOP_BAND:TOP_BAND + vh, :vw] = video
    return canvas, (0, TOP_BAND, vw, vh)


def draw_edge_warning(canvas, video_rect, sides, exited: bool) -> None:
    """손이 붙은 가장자리에 빨간 띠, 하단 띠에 문구. sides는 화면 기준."""
    x, y, w, h = video_rect
    thick = 10
    bars = {"top": (x, y, x + w, y + thick), "bottom": (x, y + h - thick, x + w, y + h),
            "left": (x, y, x + thick, y + h), "right": (x + w - thick, y, x + w, y + h)}
    for side in sides:
        x0, y0, x1, y1 = bars[side]
        cv2.rectangle(canvas, (x0, y0), (x1, y1), RED, -1)
    names = "·".join(guide_overlay.EDGE_NAMES_KO[s] for s in sides)
    if exited:
        text, fallback = f"손이 화면 {names} 밖으로 나갔습니다", f"hand left the frame ({'/'.join(sides)})"
    else:
        text, fallback = f"손이 화면 {names} 끝에 가깝습니다 — 가운데로", f"hand near {'/'.join(sides)} edge"
    # 한글은 PIL로 그려 비싸므로 하단 띠 영역만 넘긴다.
    band_top = y + h
    region = canvas[band_top:band_top + BOTTOM_BAND, 240:canvas.shape[1]]
    korean_text.put_text(region, text, (8, 14), size=24, colour=RED, fallback=fallback)


def draw_hud(canvas, video_rect, status, challenge, detected_shape, detected_move, config,
             stats=None) -> None:
    ch, cw = canvas.shape[:2]
    vx, vy, vw, vh = video_rect
    side_x = vx + vw
    cv2.rectangle(canvas, (0, 0), (cw, TOP_BAND), (25, 25, 25), -1)

    step = min(status.step_index + 1, len(challenge.actions))
    cv2.putText(canvas, f"{step}/{len(challenge.actions)}", (16, 44), FONT, 1.1, WHITE, 2)

    mid_x, mid_y = vx + vw // 2, vy + vh // 2
    if status.state is State.PASS:
        cv2.putText(canvas, "PASS", (mid_x - 90, mid_y - 35), FONT, 3.0, GREEN, 6)
        cv2.putText(canvas, "press r for next", (mid_x - 130, mid_y + 12),
                    FONT, 0.7, GREY, 2)
    elif status.state is State.FAIL:
        cv2.putText(canvas, "FAIL", (mid_x - 90, mid_y - 35), FONT, 3.0, RED, 6)
        reason = status.fail_reason.value if status.fail_reason else ""
        cv2.putText(canvas, reason, (mid_x - 200, mid_y - 2), FONT, 0.9, RED, 2)
        cv2.putText(canvas, "press r to retry", (mid_x - 130, mid_y + 22),
                    FONT, 0.7, GREY, 2)
    if status.finished and stats is not None:
        draw_stats(canvas, stats, origin=(side_x + 14, vy + 14))
    else:
        caption = ACTION_CAPTION.get(status.current_action or "", "")
        cv2.putText(canvas, caption, (110, 46), FONT, 1.2, YELLOW, 3)

        total = float(config["timing"]["per_action_timeout_ms"])
        ratio = max(min(status.remaining_ms / total, 1.0), 0.0) if total else 0.0
        cv2.rectangle(canvas, (16, 66), (cw - 16, 84), (60, 60, 60), -1)
        colour = GREEN if ratio > 0.3 else RED
        cv2.rectangle(canvas, (16, 66), (16 + int((cw - 32) * ratio), 84), colour, -1)

        if status.awaiting_escape:
            # 관문이 닫혀 있는 동안은 제한 시간이 흐르지 않는다. 시간 막대를
            # 회색으로 덮어 '아직 시작 전'임을 보인다.
            cv2.rectangle(canvas, (16, 66), (cw - 16, 84), (80, 80, 80), -1)
            escape_w = int((cw - 32) * status.escape_progress)
            cv2.rectangle(canvas, (16, 66), (16 + escape_w, 84), ORANGE, -1)
        elif is_shape_action(status.current_action or ""):
            hold_w = int((cw - 32) * status.hold_progress)
            cv2.rectangle(canvas, (16, 90), (16 + hold_w, 100), YELLOW, -1)

    cv2.putText(canvas, f"shape={detected_shape}  move={detected_move}",
                (16, 122), FONT, 0.6, GREY, 1)

    if status.current_action and not status.finished:
        guide_overlay.draw_guide(canvas, status.current_action, config,
                                 origin=(side_x + 14, vy + 14))
        if status.move_probe is not None:
            draw_move_debug(canvas, status.move_probe, config,
                            origin=(side_x + 14, vy + 14 + 150 + 14))

    if status.awaiting_escape and not status.finished:
        korean_text.put_text_centred(
            canvas, "손을 한 번 바꿨다가 다시 해주세요", mid_x, mid_y + 68,
            size=26, colour=ORANGE, fallback="change your hand, then do it again")
        korean_text.put_text_centred(
            canvas, f"직전 손 모양({status.escape_from})에서 벗어나야 시작됩니다",
            mid_x, mid_y + 104, size=16, colour=GREY,
            fallback=f"leave {status.escape_from} first")
    guide_overlay.draw_next_actions(canvas, challenge.actions,
                                    status.step_index, config)
    cv2.putText(canvas, "  ".join(challenge.actions), (16, ch - 10), FONT, 0.45, GREY, 1)


def screen_height() -> int | None:
    """주 모니터 세로 해상도 (Windows). 못 구하면 None."""
    try:
        import ctypes
        return int(ctypes.windll.user32.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001 - 창 크기만 정하는 용도라 실패해도 기본값으로 간다
        return None


def open_run_log(session_dir: Path, prefix: str = "run") -> tuple[logging.Logger, Path]:
    """실행 1회당 로그 파일 1개. 콘솔 핸들러는 달지 않는다(콘솔은 print로 요약만)."""
    path = session_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger(prefix)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-5s %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)

    previous_hook = sys.excepthook

    def log_uncaught(exc_type, exc, tb):
        logger.critical("처리되지 않은 예외로 종료", exc_info=(exc_type, exc, tb))
        previous_hook(exc_type, exc, tb)

    sys.excepthook = log_uncaught
    return logger, path


def log_frame(log: logging.Logger, now_ms: float, status, shape_result, score: float,
              edges: str = "") -> None:
    """프레임 1개의 판정. DEBUG로 전부 남긴다."""
    probe = status.move_probe
    move = "-"
    if probe is not None:
        move = (f"{probe.label}/{probe.reason} disp={probe.displacement_ratio:.3f} "
                f"axis={probe.axis_ratio:.2f} {probe.axis}{probe.sign:+d} "
                f"win={probe.span_ms:.0f}/{probe.span_needed_ms:.0f}ms({probe.frames_filled}f)")
    shape = "-"
    if shape_result is not None:
        shape = (f"{shape_result.label} conf={shape_result.confidence:.2f} "
                 f"tipw={shape_result.tip_wrist_ratio:.3f}")
    escape = (f" escape={status.escape_from}:{status.escape_progress:.2f}"
              if status.awaiting_escape else "")
    log.debug(f"t={now_ms:7.0f} {status.state.name:<6} "
              f"step={status.step_index + 1} {status.current_action or '-':<11} "
              f"score={score:.3f} shape=[{shape}] hold={status.hold_progress:.2f} "
              f"move=[{move}] remain={status.remaining_ms:.0f}{escape}"
              f"{' edge=' + edges if edges else ''}")


def log_events(log: logging.Logger, now_ms: float, previous, status) -> None:
    """이전 프레임 상태와 비교해 단계 이벤트를 INFO로 남긴다."""
    if previous is None:
        return
    for index, step in enumerate(status.steps):
        if step.retries_used > previous["retries"][index]:
            log.info(f"t={now_ms:.0f} {index + 1}단계 {step.action} 재시도 사용 "
                     f"({step.retries_used}회째)")
    if status.step_index > previous["step_index"]:
        done = status.steps[previous["step_index"]]
        log.info(f"t={now_ms:.0f} {previous['step_index'] + 1}단계 {done.action} 통과 "
                 f"({done.elapsed_ms:.0f}ms)")
        if status.current_action:
            log.info(f"t={now_ms:.0f} {status.step_index + 1}단계 "
                     f"{status.current_action} 시작")
    if status.awaiting_escape and not previous["awaiting_escape"]:
        log.info(f"t={now_ms:.0f} 이탈 관문 닫힘: 직전 모양 {status.escape_from}에서 "
                 "벗어나야 판정 시작")
    if previous["awaiting_escape"] and not status.awaiting_escape and not status.finished:
        log.info(f"t={now_ms:.0f} 이탈 관문 열림 -> {status.current_action} 판정 시작")


def snapshot(status) -> dict:
    return {"step_index": status.step_index,
            "retries": [s.retries_used for s in status.steps],
            "awaiting_escape": status.awaiting_escape}


def new_session(config, participant, session_dir, fps):
    challenge = generate_challenge()
    machine = ChallengeStateMachine(config, challenge, HandActionDetector(config),
                                    MovementDetector(config), fps)
    recorder = SessionRecorder(challenge=challenge, participant=participant,
                               started_at=datetime.now(timezone.utc).isoformat(),
                               session_dir=session_dir)
    print(f"\n새 Challenge {challenge.challenge_id}: "
          f"{' -> '.join(challenge.actions)}", flush=True)
    return challenge, machine, recorder


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--participant", default="UNKNOWN")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--capture", default=None,
                    help="카메라에 요청할 해상도 WxH (예: 1280x720). 기본은 카메라 기본값")
    ap.add_argument("--window-height", type=int, default=None,
                    help="창 세로 크기(px). 기본은 모니터 세로의 90%%")
    args = ap.parse_args()

    import mediapipe as mp

    paths = load_paths()
    config = load_json(HERE / "configs" / "challenge_config.json")
    mp_settings = load_json(HERE / "configs" / "extraction.json")["mediapipe_hands"]

    missing = [k for k in ("finger_extended_angle", "movement", "timing", "tracking")
               if config.get(k) is None]
    if missing or config["finger_extended_angle"].get("others") is None:
        print("challenge_config.json이 완성되지 않았다. 04를 먼저 실행할 것.", file=sys.stderr)
        return 1
    if config.get("_unresolved"):
        print(f"[주의] 도출하지 못한 임계값이 있다: {list(config['_unresolved'])}")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"카메라 {args.camera}번을 열 수 없다.", file=sys.stderr)
        return 1
    if args.capture:
        want_w, want_h = (int(v) for v in args.capture.lower().split("x"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, want_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, want_h)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    session_dir = Path(paths.get("session_out", "./data/sessions"))
    session_dir.mkdir(parents=True, exist_ok=True)
    csv_path = session_dir / "results.csv"

    log, log_path = open_run_log(session_dir)
    log.info(f"실행 시작 participant={args.participant} camera={args.camera} "
             f"{width}x{height} @ {fps:.1f}fps (요청 해상도 {args.capture or '기본'})")

    # 창은 사용자가 끌어서 크기를 바꿀 수 있다. 처음에는 모니터 세로에 맞춰 키운다.
    canvas_w, canvas_h = width + SIDE_PANEL, TOP_BAND + height + BOTTOM_BAND
    target_h = args.window_height or int((screen_height() or canvas_h) * 0.9)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, int(canvas_w * target_h / canvas_h), target_h)
    log.info(f"창 {canvas_w}x{canvas_h} 캔버스를 세로 {target_h}px로 표시. "
             f"가장자리 경고 여유 = 손 크기 x {guide_overlay.EDGE_MARGIN_HAND_SCALES} (안내용)")

    stats = RunStats()
    participant = args.participant
    challenge, machine, recorder = new_session(config, participant, session_dir, fps)

    print("\n=== 적용된 임계값 (판정기 객체에서 읽음) ===", flush=True)
    for line in threshold_report_lines(config, machine.shape_detector,
                                       machine.movement_detector, machine):
        print(f"  {line}", flush=True)
        log.info(f"임계값 {line}")
    print(f"\n카메라 {width}x{height}, 창 세로 {target_h}px (끌어서 크기 조절 가능)", flush=True)
    print(f"상세 로그: {log_path}", flush=True)
    print("키: r 다음 시도(진행 중이면 중단)  q 종료  s 참가자 ID", flush=True)
    print("화면은 거울처럼 좌우가 뒤집혀 보인다. 화면에 보이는 방향으로 움직이면 된다.",
          flush=True)
    log.info(f"새 Challenge {challenge.challenge_id}: {' -> '.join(challenge.actions)}")
    log.info(f"t=0 1단계 {challenge.actions[0]} 시작")
    previous = None
    last_edges: list[str] = []
    writer = cv2.VideoWriter(str(recorder.video_path),
                             cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    started = time.time()
    saved = False

    with mp.solutions.hands.Hands(**mp_settings) as hands:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            # MediaPipe에는 원본 프레임을 준다. 뒤집은 프레임을 넣으면
            #   (1) handedness가 반대로 나오고,
            #   (2) config의 coordinate_frame="mirrored"가 좌우를 한 번 더
            #       뒤집어 MOVE_LEFT/RIGHT 판정이 통째로 반대가 된다.
            # 저장도 원본으로 한다. 파일럿 영상과 같은 좌표계여야 나중에 함께
            # 분석할 수 있다. 화면 표시만 거울처럼 뒤집는다.
            writer.write(frame_bgr)

            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            result = hands.process(rgb)
            now_ms = (time.time() - started) * 1000.0

            landmarks = world = None
            score, hand_label = float("nan"), ""
            if result.multi_hand_landmarks:
                hl = result.multi_hand_landmarks[0]
                landmarks = np.array([[p.x, p.y, p.z] for p in hl.landmark], np.float32)
                if result.multi_hand_world_landmarks:
                    wl = result.multi_hand_world_landmarks[0]
                    world = np.array([[p.x, p.y, p.z] for p in wl.landmark], np.float32)
                cls = result.multi_handedness[0].classification[0]
                score, hand_label = float(cls.score), cls.label

            recorder.add_frame(landmarks, landmarks is not None, score, hand_label, now_ms)

            if landmarks is not None:
                angle_coords = (world if config["angle_space"] == "world" and world is not None
                                else g.to_isotropic(landmarks, width, height))
                observation = Observation(now_ms, True, score, angle_coords,
                                          g.to_isotropic(landmarks, width, height))
            else:
                observation = Observation(now_ms, False)

            status = machine.update(observation)

            shape_label, move_label = "-", "-"
            shape_result = None
            if landmarks is not None:
                shape_result = machine.shape_detector.detect(observation.angle_coords)
                shape_label = shape_result.label
                move_label = status.detected_move
            if landmarks is not None:
                edges = guide_overlay.edge_sides(landmarks, width, height)
                exited = False
                last_edges = edges
            else:
                # 가장자리에 붙어 있다가 사라졌으면 화면 밖으로 나간 것으로 본다.
                edges, exited = last_edges, bool(last_edges)
            edge_text = ("exited:" if exited else "") + ",".join(edges)
            if not saved:
                log_frame(log, now_ms, status, shape_result, score, edge_text)
                log_events(log, now_ms, previous, status)
                previous = snapshot(status)

            display = cv2.flip(frame_bgr, 1)
            if landmarks is not None:
                draw_landmarks(display, landmarks, width, height)
            canvas, video_rect = compose_canvas(display)
            draw_hud(canvas, video_rect, status, challenge, shape_label, move_label, config, stats)
            if edges and not status.finished:
                draw_edge_warning(canvas, video_rect, edges, exited)
            cv2.imshow(WINDOW, canvas)

            if status.finished and not saved:
                writer.release()
                recorder.save_landmarks(fps, width, height)
                append_result(csv_path, recorder, status, now_ms, config)
                stats.record(status, now_ms)
                for line in attempt_report_lines(recorder, status, now_ms, stats.attempts):
                    log.info(line)
                # 파이프로 실행해도 요약이 바로 보이도록 flush 한다.
                print(f"\n결과: {status.state.name}"
                      f"{' / ' + status.fail_reason.value if status.fail_reason else ''}"
                      f"  ({now_ms:.0f}ms)", flush=True)
                print(stats.console_report(), flush=True)
                saved = True

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                log.info("q 입력: 종료" + ("" if saved else " (진행 중이던 시도는 기록하지 않음)"))
                break
            if key == ord("r"):
                if not saved:
                    writer.release()
                    log.info(f"r 입력: 진행 중이던 시도 중단 (t={now_ms:.0f}, "
                             f"{status.step_index + 1}단계). 결과·통계에 넣지 않음")
                challenge, machine, recorder = new_session(config, participant,
                                                           session_dir, fps)
                log.info(f"새 Challenge {challenge.challenge_id}: "
                         f"{' -> '.join(challenge.actions)}")
                log.info(f"t=0 1단계 {challenge.actions[0]} 시작")
                previous = None
                writer = cv2.VideoWriter(str(recorder.video_path),
                                         cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                         (width, height))
                started, saved = time.time(), False
                last_edges = []
            if key == ord("s"):
                cv2.destroyAllWindows()
                participant = input("참가자 ID: ").strip() or participant
                recorder.participant = participant
                log.info(f"참가자 ID 변경: {participant}")

    if not saved:
        writer.release()
    cap.release()
    cv2.destroyAllWindows()

    print("\n" + "=" * 60, flush=True)
    print("최종 요약", flush=True)
    print("=" * 60, flush=True)
    print(stats.console_report(), flush=True)
    print(f"\n세션 기록: {csv_path}", flush=True)
    print(f"상세 로그: {log_path}", flush=True)
    log.info("최종 요약\n" + stats.console_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
