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
from core.challenge_logger import SessionRecorder, append_result  # noqa: E402
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


def draw_hud(frame, status, challenge, detected_shape, detected_move, config) -> None:
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 132), (25, 25, 25), -1)

    step = min(status.step_index + 1, len(challenge.actions))
    cv2.putText(frame, f"{step}/{len(challenge.actions)}", (16, 44), FONT, 1.1, WHITE, 2)

    if status.state is State.PASS:
        cv2.putText(frame, "PASS", (w // 2 - 90, h // 2), FONT, 3.0, GREEN, 6)
    elif status.state is State.FAIL:
        cv2.putText(frame, "FAIL", (w // 2 - 90, h // 2 - 30), FONT, 3.0, RED, 6)
        reason = status.fail_reason.value if status.fail_reason else ""
        cv2.putText(frame, reason, (w // 2 - 200, h // 2 + 30), FONT, 0.9, RED, 2)
        cv2.putText(frame, "press r to retry", (w // 2 - 130, h // 2 + 70),
                    FONT, 0.7, GREY, 2)
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
    print(f"\n새 Challenge {challenge.challenge_id}: {' -> '.join(challenge.actions)}")
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

    print("화면은 거울처럼 좌우가 뒤집혀 보인다. 화면에 보이는 방향으로 움직이면 된다.")
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
            draw_hud(display, status, challenge, shape_label, move_label, config)
            cv2.imshow("Challenge-Response", display)

            if status.finished and not saved:
                writer.release()
                recorder.save_landmarks(fps, width, height)
                append_result(csv_path, recorder, status, now_ms)
                print(f"결과: {status.state.name}"
                      f"{' / ' + status.fail_reason.value if status.fail_reason else ''}"
                      f"  → {csv_path}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
