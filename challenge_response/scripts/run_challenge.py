"""실시간 Challenge 프로토타입 (SPEC 4.10).

    python scripts/run_challenge.py [--participant P01] [--camera 0]

키 조작:  q 종료   r 재시작   s 참가자 ID 입력

화면은 거울처럼 좌우 반전해 보여주고, 판정도 config의 coordinate_frame에 따라
화면 기준으로 한다. 성공·실패 영상을 모두 저장한다.
"""
from __future__ import annotations

import argparse
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
                                   append_result)
from core.challenge_state_machine import (ChallengeStateMachine,  # noqa: E402
                                          Observation, State)
from core.hand_action_detector import HandActionDetector  # noqa: E402
from core.landmark_io import HERE, load_json, load_paths  # noqa: E402
from core.movement_detector import MovementDetector  # noqa: E402
import guide_overlay  # noqa: E402

WHITE, GREEN, RED, YELLOW, GREY = ((255, 255, 255), (80, 220, 120),
                                   (70, 70, 235), (60, 200, 240), (170, 170, 170))
FONT = cv2.FONT_HERSHEY_SIMPLEX
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


def draw_move_debug(frame, probe, config) -> None:
    """이동 판정의 두 관문이 지금 어떤 값인지 그대로 보여준다.

    임계값을 짐작해서 바꾸기 전에, 무엇이 막고 있는지부터 눈으로 본다.
    """
    movement = config["movement"]
    min_disp = movement.get("min_displacement_ratio")
    axis_min = movement.get("axis_dominance_ratio")

    lines = []
    filled, needed = probe.frames_filled, probe.frames_needed
    # 윈도우가 아직 안 찼는 건 실패가 아니므로 X를 붙이지 않는다.
    lines.append(("window", f"{filled}/{needed}",
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
    x, y = 14, 150

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


def draw_stats(frame, stats) -> None:
    """이번 실행의 사유별 통계. 결과 화면에서만 띄운다."""
    if stats.attempts == 0:
        return
    lines = stats.summary_lines()
    pad, line_h = 10, 19
    box_w = 268
    box_h = pad * 2 + line_h * len(lines)
    x, y = 14, frame.shape[0] - box_h - 96

    panel = frame[y:y + box_h, x:x + box_w]
    if panel.shape[0] != box_h or panel.shape[1] != box_w:
        return
    cv2.addWeighted(panel, 0.2, np.full_like(panel, (30, 30, 30), np.uint8), 0.8, 0, panel)
    cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), (90, 90, 90), 1)

    for i, text in enumerate(lines):
        colour = WHITE if i == 0 else GREY
        cv2.putText(frame, text, (x + pad, y + pad + line_h * (i + 1) - 6),
                    FONT, 0.42, colour, 1, cv2.LINE_AA)


def draw_hud(frame, status, challenge, detected_shape, detected_move, config,
             stats=None) -> None:
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 132), (25, 25, 25), -1)

    step = min(status.step_index + 1, len(challenge.actions))
    cv2.putText(frame, f"{step}/{len(challenge.actions)}", (16, 44), FONT, 1.1, WHITE, 2)

    if status.state is State.PASS:
        cv2.putText(frame, "PASS", (w // 2 - 90, h // 2 - 35), FONT, 3.0, GREEN, 6)
        cv2.putText(frame, "press r for next", (w // 2 - 130, h // 2 + 12),
                    FONT, 0.7, GREY, 2)
    elif status.state is State.FAIL:
        # 아래쪽은 통계 패널이 쓰므로 결과 문구는 위로 올린다.
        cv2.putText(frame, "FAIL", (w // 2 - 90, h // 2 - 35), FONT, 3.0, RED, 6)
        reason = status.fail_reason.value if status.fail_reason else ""
        cv2.putText(frame, reason, (w // 2 - 200, h // 2 - 2), FONT, 0.9, RED, 2)
        cv2.putText(frame, "press r to retry", (w // 2 - 130, h // 2 + 22),
                    FONT, 0.7, GREY, 2)
    if status.finished and stats is not None:
        draw_stats(frame, stats)
    else:
        caption = ACTION_CAPTION.get(status.current_action or "", "")
        cv2.putText(frame, caption, (110, 46), FONT, 1.2, YELLOW, 3)

        total = float(config["timing"]["per_action_timeout_ms"])
        ratio = max(min(status.remaining_ms / total, 1.0), 0.0) if total else 0.0
        cv2.rectangle(frame, (16, 66), (w - 16, 84), (60, 60, 60), -1)
        colour = GREEN if ratio > 0.3 else RED
        cv2.rectangle(frame, (16, 66), (16 + int((w - 32) * ratio), 84), colour, -1)

        if is_shape_action(status.current_action or ""):
            hold_w = int((w - 32) * status.hold_progress)
            cv2.rectangle(frame, (16, 90), (16 + hold_w, 100), YELLOW, -1)

    cv2.putText(frame, f"shape={detected_shape}  move={detected_move}",
                (16, 122), FONT, 0.6, GREY, 1)

    if status.current_action and not status.finished:
        guide_overlay.draw_guide(frame, status.current_action, config)
        if status.move_probe is not None:
            draw_move_debug(frame, status.move_probe, config)
    guide_overlay.draw_next_actions(frame, challenge.actions,
                                    status.step_index, config)
    cv2.putText(frame, "  ".join(challenge.actions), (16, h - 10), FONT, 0.45, GREY, 1)


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
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    session_dir = Path(paths.get("session_out", "./data/sessions"))
    session_dir.mkdir(parents=True, exist_ok=True)
    csv_path = session_dir / "results.csv"

    stats = RunStats()
    print("화면은 거울처럼 좌우가 뒤집혀 보인다. 화면에 보이는 방향으로 움직이면 된다.",
          flush=True)
    participant = args.participant
    challenge, machine, recorder = new_session(config, participant, session_dir, fps)
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
            if landmarks is not None:
                shape_label = machine.shape_detector.detect(observation.angle_coords).label
                move_label = status.detected_move

            display = cv2.flip(frame_bgr, 1)
            if landmarks is not None:
                draw_landmarks(display, landmarks, width, height)
            draw_hud(display, status, challenge, shape_label, move_label, config, stats)
            cv2.imshow("Challenge-Response", display)

            if status.finished and not saved:
                writer.release()
                recorder.save_landmarks(fps, width, height)
                append_result(csv_path, recorder, status, now_ms, config)
                stats.record(status, now_ms)
                # 파이프로 실행해도 요약이 바로 보이도록 flush 한다.
                print(f"\n결과: {status.state.name}"
                      f"{' / ' + status.fail_reason.value if status.fail_reason else ''}"
                      f"  ({now_ms:.0f}ms)", flush=True)
                print(stats.console_report(), flush=True)
                saved = True

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("r"):
                if not saved:
                    writer.release()
                challenge, machine, recorder = new_session(config, participant,
                                                           session_dir, fps)
                writer = cv2.VideoWriter(str(recorder.video_path),
                                         cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                         (width, height))
                started, saved = time.time(), False
            if key == ord("s"):
                cv2.destroyAllWindows()
                participant = input("참가자 ID: ").strip() or participant
                recorder.participant = participant

    if not saved:
        writer.release()
    cap.release()
    cv2.destroyAllWindows()

    print("\n" + "=" * 60, flush=True)
    print("최종 요약", flush=True)
    print("=" * 60, flush=True)
    print(stats.console_report(), flush=True)
    print(f"\n세션 기록: {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
