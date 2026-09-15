"""웹캠 반례 녹화 모드 (2026-09-16).

    python scripts/record_negatives.py --participant P01 [--takes 5] [--kinds shake,diagonal,exit]
                                       [--window-height 780] [--camera 0] [--capture 1280x720]

흔들기·대각선·손 이탈을 종류별로 녹화하고, 찍는 즉시 실시간 challenge와 같은 판정 경로로
오검출 여부를 보여준다 (core/negative_eval.py). 임계값은 바꾸지 않는다.

키:  SPACE  녹화 시작(3초 카운트다운) / 녹화 중이면 바로 끝내기 / 결과 화면이면 다음
     r      결과 화면에서 방금 찍은 것을 다시 찍기(같은 번호로 덮어씀)
     n      이번 순서 건너뛰기
     q      종료

저장: data/negatives_live/{참가자}_NEG_{종류}_{번호}.mp4 / .npz, results.csv,
      record_YYYYMMDD_HHMMSS.log (프레임별 판정 포함)
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

from core import geometry as g  # noqa: E402
from core.challenge_state_machine import RULE_VERSION, Observation  # noqa: E402
from core.landmark_io import HERE, load_json  # noqa: E402
from core.negative_eval import NEGATIVE_KINDS, NegativeProbe  # noqa: E402
import guide_overlay  # noqa: E402
import korean_text  # noqa: E402
import run_challenge as RC  # noqa: E402

OUT_DIR = HERE / "data" / "negatives_live"
# 화면 안내용 값(판정과 무관)
COUNTDOWN_MS = 3000

KIND_TEXT = {
    "shake": ("흔들기",
              "손바닥을 편 채 제자리에서 흔드세요. 좌우·상하를 섞어도 됩니다.",
              "통과한 이동과 비슷한 크기로 흔들어 보세요 (오른쪽 패널의 최대 변위비 참고)."),
    "diagonal": ("대각선",
                 "손바닥을 편 채 대각선으로 왕복하세요.",
                 "오른쪽 위 ↔ 왼쪽 아래, 또는 왼쪽 위 ↔ 오른쪽 아래."),
    "exit": ("손 이탈",
             "손바닥을 편 채 움직이다가 화면 밖으로 손을 빼세요.",
             "위·아래·왼쪽·오른쪽 어느 쪽이든 됩니다. 손이 사라지면 자동으로 끝납니다."),
}
CSV_FIELDS = ["recorded_at", "rule_version", "participant", "kind", "take", "stem",
              "duration_ms", "frames", "hand_frames", "windows", "confirmed_windows",
              "confirmed_share", "max_disp_ratio", "reference_disp_ratio", "events",
              "events_detail", "accept_LEFT_ms", "accept_RIGHT_ms", "accept_UP_ms",
              "accept_DOWN_ms", "tracking_end", "tracking_end_ms", "no_false_accept",
              "verdict", "video_path", "npz_path"]


def reference_displacement() -> tuple[float, str]:
    """이번 규칙 버전에서 통과한 이동 단계의 최대 변위비 중앙값 (results.csv에서 계산)."""
    path = HERE / "data" / "sessions" / "results.csv"
    if not path.exists():
        return float("nan"), "results.csv 없음"
    rows = pd.read_csv(path)
    passed = rows[(rows.get("move_passed") == 1) & rows["move_max_disp_ratio"].notna()]
    current = passed[passed["rule_version"] == RULE_VERSION]
    use, label = (current, f"규칙 {RULE_VERSION}") if len(current) else (passed, "전체 규칙")
    if use.empty:
        return float("nan"), "통과한 이동 기록 없음"
    return float(use["move_max_disp_ratio"].median()), f"{label}, 통과한 이동 {len(use)}회"


def next_index(participant: str, kind: str) -> int:
    existing = [int(p.stem.rsplit("_", 1)[1]) for p in OUT_DIR.glob(f"{participant}_NEG_{kind}_*.npz")
                if p.stem.rsplit("_", 1)[1].isdigit()]
    return max(existing, default=0) + 1


def put_band_text(canvas, lines, top, left=16, size=20, colour=RC.WHITE):
    """상단/하단 띠에 한글 여러 줄. PIL이 비싸서 띠 영역만 넘긴다."""
    line_h = size + 8
    region = canvas[top:top + line_h * len(lines) + 6, left:canvas.shape[1] - 8]
    for i, (text, fallback) in enumerate(lines):
        korean_text.put_text(region, text, (0, i * line_h), size=size, colour=colour,
                             fallback=fallback)


def draw_side_stats(canvas, x, y, probe: NegativeProbe | None, reference, reference_label,
                    config) -> None:
    move = config["movement"]
    # OpenCV 기본 글꼴은 한글을 못 그리므로 패널은 영문만 쓴다.
    lines = [f"ref max disp {reference:.3f}", "  (median of passed moves, results.csv)"]
    if probe is not None:
        r = probe.result
        max_disp = r.max_displacement_ratio
        lines += [f"this take max disp {max_disp:.3f}" if np.isfinite(max_disp) else "this take max disp --",
                  f"windows {r.evaluated_windows}  confirmed {r.confirmed_windows}",
                  f"accepted events {len(r.events)}"]
        lines += [f"  {t / 1000:5.2f}s {label}" for t, label in r.events[-4:]]
        if r.tracking_end:
            lines.append(f"tracking end {r.tracking_end}")
    lines.append(f"gates: disp>={move['min_displacement_ratio']} axis>={move['axis_dominance_ratio']}")
    for i, text in enumerate(lines):
        colour = RC.GREY
        if probe is not None and text.startswith("this take max disp") and np.isfinite(reference):
            colour = RC.YELLOW if probe.result.max_displacement_ratio >= reference else RC.WHITE
        if text.startswith("accepted events") and probe is not None and probe.result.events:
            colour = RC.RED
        cv2.putText(canvas, text, (x, y + 18 * (i + 1)), RC.FONT, 0.45, colour, 1, cv2.LINE_AA)


def save_take(stem, kind, take, participant, timestamps, landmarks, valid, scores,
              handed, fps, width, height, reference) -> Path:
    path = OUT_DIR / f"{stem}.npz"
    n = len(timestamps)
    np.savez_compressed(
        path,
        landmarks=np.stack(landmarks) if n else np.zeros((0, 21, 3), np.float32),
        valid_mask=np.array(valid, bool), detection_score=np.array(scores, np.float32),
        handedness=np.array(handed, dtype="<U8"), timestamp_ms=np.array(timestamps, np.float64),
        fps=np.float32(fps), width=np.int32(width), height=np.int32(height),
        kind=kind, take=np.int32(take), participant=participant, rule_version=RULE_VERSION,
        reference_disp_ratio=np.float32(reference))
    return path


def append_csv(row: dict) -> None:
    path = OUT_DIR / "results.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--participant", default="P01")
    ap.add_argument("--takes", type=int, default=5)
    ap.add_argument("--kinds", default=",".join(NEGATIVE_KINDS))
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--capture", default=None)
    ap.add_argument("--window-height", type=int, default=None)
    args = ap.parse_args()

    import mediapipe as mp

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in NEGATIVE_KINDS]
    if unknown:
        print(f"알 수 없는 종류: {unknown} (가능: {NEGATIVE_KINDS})", file=sys.stderr)
        return 1

    config = load_json(HERE / "configs" / "challenge_config.json")
    policy = load_json(HERE / "configs" / "derivation_policy.json")
    targets = policy["targets"]
    mp_settings = load_json(HERE / "configs" / "extraction.json")["mediapipe_hands"]
    take_ms = float(config["timing"]["total_timeout_ms"])   # 한 Challenge 전체 시간만큼 찍는다
    reference, reference_label = reference_displacement()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"카메라 {args.camera}번을 열 수 없다.", file=sys.stderr)
        return 1
    if args.capture:
        w_req, h_req = (int(v) for v in args.capture.lower().split("x"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w_req)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h_req)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log, log_path = RC.open_run_log(OUT_DIR, prefix="record")
    canvas_w, canvas_h = width + RC.SIDE_PANEL, RC.TOP_BAND + height + RC.BOTTOM_BAND
    target_h = args.window_height or int((RC.screen_height() or canvas_h) * 0.9)
    cv2.namedWindow(RC.WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(RC.WINDOW, int(canvas_w * target_h / canvas_h), target_h)

    plan = []
    for kind in kinds:
        start = next_index(args.participant, kind)
        plan += [(kind, i + 1, start + i) for i in range(args.takes)]

    header = (f"반례 녹화 participant={args.participant} kinds={kinds} x{args.takes} "
              f"take={take_ms:.0f}ms camera {width}x{height} rule={RULE_VERSION}")
    log.info(header)
    log.info(f"비교 기준 최대 변위비 {reference:.3f} ({reference_label})")
    print(header, flush=True)
    print(f"비교 기준: 통과한 이동의 최대 변위비 중앙값 {reference:.3f} ({reference_label})", flush=True)
    print(f"저장 위치: {OUT_DIR}\n상세 로그: {log_path}", flush=True)
    print("키: SPACE 시작/끝내기/다음   r 다시 찍기   n 건너뛰기   q 종료", flush=True)

    summary: dict[str, list[tuple[int, bool, float, int]]] = {k: [] for k in kinds}
    position = 0
    state = "READY"
    probe = None
    take_started = countdown_started = 0.0
    frames_buf = []
    writer = None
    last_edges: list[str] = []
    stop_requested = False
    result_text = ("", "")
    result_ok = True

    def reset_buffers():
        return {"t": [], "lm": [], "valid": [], "score": [], "hand": []}

    buf = reset_buffers()

    with mp.solutions.hands.Hands(**mp_settings) as hands:
        while position < len(plan):
            kind, order, index = plan[position]
            stem = f"{args.participant}_NEG_{kind}_{index:02d}"
            ok, frame_bgr = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            mp_result = hands.process(rgb)

            landmarks, score, hand_label = None, float("nan"), ""
            if mp_result.multi_hand_landmarks:
                hl = mp_result.multi_hand_landmarks[0]
                landmarks = np.array([[p.x, p.y, p.z] for p in hl.landmark], np.float32)
                cls = mp_result.multi_handedness[0].classification[0]
                score, hand_label = float(cls.score), cls.label

            now = time.time()
            status = None
            if state == "COUNTDOWN" and (now - countdown_started) * 1000 >= COUNTDOWN_MS:
                state = "RECORDING"
                take_started = now
                probe = NegativeProbe(config, kind, fps)
                stop_requested = False
                buf = reset_buffers()
                writer = cv2.VideoWriter(str(OUT_DIR / f"{stem}.mp4"),
                                         cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                log.info(f"[{stem}] 녹화 시작 ({KIND_TEXT[kind][0]} {order}/{args.takes})")

            if state == "RECORDING":
                t_ms = (now - take_started) * 1000.0
                writer.write(frame_bgr)
                if landmarks is not None:
                    coords = g.to_isotropic(landmarks, width, height)
                    obs = Observation(t_ms, True, score, coords, coords)
                else:
                    obs = Observation(t_ms, False)
                status = probe.update(obs)
                buf["t"].append(t_ms)
                buf["lm"].append(landmarks if landmarks is not None
                                 else np.full((21, 3), np.nan, np.float32))
                buf["valid"].append(landmarks is not None)
                buf["score"].append(score)
                buf["hand"].append(hand_label)
                if status is not None:
                    RC.log_frame(log, t_ms, status, None, score)
                if t_ms >= take_ms or probe.finished or stop_requested:
                    state = "FINISH"

            if state == "FINISH":
                writer.release()
                writer = None
                duration = buf["t"][-1] if buf["t"] else 0.0
                npz_path = save_take(stem, kind, index, args.participant, buf["t"], buf["lm"],
                                     buf["valid"], buf["score"], buf["hand"], fps, width, height,
                                     reference)
                r = probe.result
                result_ok, verdict = r.verdict(targets)
                accepts = r.first_accept_ms()
                row = {
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "rule_version": RULE_VERSION, "participant": args.participant, "kind": kind,
                    "take": index, "stem": stem, "duration_ms": round(duration),
                    "frames": r.frames, "hand_frames": r.hand_frames,
                    "windows": r.evaluated_windows, "confirmed_windows": r.confirmed_windows,
                    "confirmed_share": round(r.confirmed_share, 4),
                    "max_disp_ratio": round(r.max_displacement_ratio, 4)
                    if np.isfinite(r.max_displacement_ratio) else "",
                    "reference_disp_ratio": round(reference, 4) if np.isfinite(reference) else "",
                    "events": len(r.events),
                    "events_detail": "; ".join(f"{t:.0f}ms {lab}" for t, lab in r.events),
                    **{f"accept_{a.replace('MOVE_', '')}_ms": ("" if v is None else round(v))
                       for a, v in accepts.items()},
                    "tracking_end": r.tracking_end or "",
                    "tracking_end_ms": round(r.tracking_end_ms) if r.tracking_end_ms else "",
                    "no_false_accept": int(result_ok), "verdict": verdict,
                    "video_path": str(OUT_DIR / f"{stem}.mp4"), "npz_path": str(npz_path),
                }
                append_csv(row)
                summary[kind] = [s for s in summary[kind] if s[0] != index]
                summary[kind].append((index, result_ok, r.max_displacement_ratio, len(r.events)))
                mark = "오검출 없음" if result_ok else "오검출"
                result_text = (f"{KIND_TEXT[kind][0]} {order}/{args.takes}: {mark}", verdict)
                log.info(f"[{stem}] {mark} — {verdict} / 최대 변위비 {r.max_displacement_ratio:.3f} "
                         f"(기준 {reference:.3f}), 윈도우 {r.evaluated_windows}, "
                         f"프레임 {r.frames} (손 {r.hand_frames})")
                print(f"[{stem}] {mark} — {verdict} / 최대 변위비 {r.max_displacement_ratio:.3f} "
                      f"(기준 {reference:.3f})", flush=True)
                state = "RESULT"

            # ---- 화면
            display = cv2.flip(frame_bgr, 1)
            if landmarks is not None:
                RC.draw_landmarks(display, landmarks, width, height)
            canvas, rect = RC.compose_canvas(display)
            vx, vy, vw, vh = rect
            side_x = vx + vw + 14
            cv2.rectangle(canvas, (0, 0), (canvas.shape[1], RC.TOP_BAND), (25, 25, 25), -1)
            title = f"{KIND_TEXT[kind][0]}  {order}/{args.takes}   ({stem})"
            state_line = {
                "READY": ("SPACE를 누르면 3초 뒤 녹화를 시작합니다", "press SPACE to start"),
                "COUNTDOWN": ("준비하세요…", "get ready"),
                "RECORDING": (f"녹화 중 — SPACE로 바로 끝내기 (최대 {take_ms / 1000:.0f}초)", "recording"),
                "RESULT": ("SPACE 다음   r 다시 찍기   q 종료", "SPACE next / r redo / q quit"),
            }[state]
            put_band_text(canvas, [(title, title), state_line], top=12, size=24,
                          colour=RC.YELLOW)
            if state == "RECORDING":
                elapsed = min((now - take_started) * 1000.0 / take_ms, 1.0)
                cv2.rectangle(canvas, (16, RC.TOP_BAND - 16), (canvas.shape[1] - 16, RC.TOP_BAND - 6),
                              (60, 60, 60), -1)
                cv2.rectangle(canvas, (16, RC.TOP_BAND - 16),
                              (16 + int((canvas.shape[1] - 32) * elapsed), RC.TOP_BAND - 6), RC.RED, -1)
            if state == "COUNTDOWN":
                left = max(COUNTDOWN_MS - (now - countdown_started) * 1000, 0) / 1000
                cv2.putText(canvas, f"{int(np.ceil(left))}", (vx + vw // 2 - 30, vy + vh // 2 + 30),
                            RC.FONT, 4.0, RC.YELLOW, 8)

            if status is not None and status.move_probe is not None:
                RC.draw_move_debug(canvas, status.move_probe, config, origin=(side_x, vy + 14))
            draw_side_stats(canvas, side_x, vy + 14 + 120, probe if state in ("RECORDING", "RESULT") else None,
                            reference, reference_label, config)

            band_top = vy + vh
            if state == "RESULT":
                put_band_text(canvas, [(result_text[0], result_text[0]), (result_text[1][:60], "")],
                              top=band_top + 12, size=22,
                              colour=RC.GREEN if result_ok else RC.RED)
            else:
                put_band_text(canvas, [(KIND_TEXT[kind][1], kind), (KIND_TEXT[kind][2], "")],
                              top=band_top + 12, size=20, colour=RC.WHITE)

            if landmarks is not None:
                edges, exited = guide_overlay.edge_sides(landmarks, width, height), False
                last_edges = edges
            else:
                edges, exited = last_edges, bool(last_edges)
            if edges and state != "RESULT":
                x, y, w, h = rect
                for side in edges:
                    bars = {"top": (x, y, x + w, y + 10), "bottom": (x, y + h - 10, x + w, y + h),
                            "left": (x, y, x + 10, y + h), "right": (x + w - 10, y, x + w, y + h)}
                    x0, y0, x1, y1 = bars[side]
                    cv2.rectangle(canvas, (x0, y0), (x1, y1), RC.RED, -1)
            cv2.imshow(RC.WINDOW, canvas)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                log.info("q 입력: 종료")
                break
            if key == ord(" "):
                if state == "READY":
                    state, countdown_started = "COUNTDOWN", now
                elif state == "RECORDING":
                    stop_requested = True       # 다음 프레임에서 저장한다
                elif state == "RESULT":
                    position += 1
                    state = "READY"
            elif key == ord("r") and state == "RESULT":
                log.info(f"[{stem}] 다시 찍기")
                state, countdown_started = "COUNTDOWN", now
            elif key == ord("n") and state == "READY":
                log.info(f"[{stem}] 건너뜀")
                position += 1

    if writer is not None:
        writer.release()
    cap.release()
    cv2.destroyAllWindows()

    lines = ["", "=" * 64, "반례 녹화 요약 (오검출 없음 / 찍은 수)", "=" * 64]
    for kind in kinds:
        takes = sorted(summary[kind])
        if not takes:
            lines.append(f"{KIND_TEXT[kind][0]:<6} 찍은 것 없음")
            continue
        ok_n = sum(t[1] for t in takes)
        disp = [t[2] for t in takes if np.isfinite(t[2])]
        lines.append(f"{KIND_TEXT[kind][0]:<6} {ok_n}/{len(takes)}  최대 변위비 "
                     + ", ".join(f"{d:.2f}" for d in disp)
                     + f"  (기준 {reference:.2f})  이동 인정 합계 {sum(t[3] for t in takes)}회")
    lines.append(f"결과 CSV: {OUT_DIR / 'results.csv'}")
    lines.append(f"상세 로그: {log_path}")
    for line in lines:
        print(line, flush=True)
    log.info("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
