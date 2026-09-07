"""Challenge 세션 결과 저장 (SPEC 4.10).

성공·실패 영상을 모두 남긴다. 실패 영상이 규칙 개선의 재료다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .challenge_generator import Challenge
from .challenge_state_machine import FailReason, State, Status

CSV_FIELDS = [
    "challenge_id", "participant", "started_at", "elapsed_ms", "result",
    "fail_reason", "action_1", "action_2", "action_3",
    "passed_1", "passed_2", "passed_3",
    "elapsed_1_ms", "elapsed_2_ms", "elapsed_3_ms",
    "retries_1", "retries_2", "retries_3",
    "frames", "detected_frames", "video_path", "landmark_path",
]


@dataclass
class SessionRecorder:
    """한 번의 Challenge 동안 프레임과 결과를 모은다."""
    challenge: Challenge
    participant: str
    started_at: str
    session_dir: Path
    landmarks: list = field(default_factory=list)
    valid: list = field(default_factory=list)
    scores: list = field(default_factory=list)
    handedness: list = field(default_factory=list)
    timestamps: list = field(default_factory=list)

    def add_frame(self, landmarks: Optional[np.ndarray], detected: bool,
                  score: float, hand_label: str, timestamp_ms: float) -> None:
        empty = np.full((21, 3), np.nan, dtype=np.float32)
        self.landmarks.append(empty if landmarks is None
                              else np.asarray(landmarks, dtype=np.float32))
        self.valid.append(bool(detected))
        self.scores.append(float(score))
        self.handedness.append(str(hand_label))
        self.timestamps.append(float(timestamp_ms))

    @property
    def landmark_path(self) -> Path:
        return self.session_dir / f"{self.challenge.challenge_id}.npz"

    @property
    def video_path(self) -> Path:
        return self.session_dir / f"{self.challenge.challenge_id}.mp4"

    def save_landmarks(self, fps: float, width: int, height: int) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        n = len(self.landmarks)
        np.savez_compressed(
            self.landmark_path,
            landmarks=(np.stack(self.landmarks) if n
                       else np.zeros((0, 21, 3), dtype=np.float32)),
            valid_mask=np.array(self.valid, dtype=bool),
            detection_score=np.array(self.scores, dtype=np.float32),
            handedness=np.array(self.handedness, dtype="<U8"),
            timestamp_ms=np.array(self.timestamps, dtype=np.float64),
            fps=np.float32(fps), width=np.int32(width), height=np.int32(height),
            challenge_id=self.challenge.challenge_id,
            participant=self.participant,
            actions=np.array(self.challenge.actions, dtype="<U16"),
            created_at=self.challenge.created_at,
        )
        return self.landmark_path


def append_result(csv_path: Path, recorder: SessionRecorder, status: Status,
                  elapsed_ms: float) -> None:
    """결과 CSV에 한 줄 추가한다. 파일이 없으면 헤더부터 쓴다."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()

    steps = list(status.steps)
    while len(steps) < 3:
        steps.append(None)

    fail: Optional[FailReason] = status.fail_reason
    row = {
        "challenge_id": recorder.challenge.challenge_id,
        "participant": recorder.participant,
        "started_at": recorder.started_at,
        "elapsed_ms": round(elapsed_ms, 1),
        "result": "PASS" if status.state is State.PASS else "FAIL",
        "fail_reason": fail.value if fail else "",
        "frames": len(recorder.valid),
        "detected_frames": int(sum(recorder.valid)),
        "video_path": str(recorder.video_path),
        "landmark_path": str(recorder.landmark_path),
    }
    for i, step in enumerate(steps[:3], start=1):
        row[f"action_{i}"] = step.action if step else ""
        row[f"passed_{i}"] = int(step.passed) if step else ""
        row[f"elapsed_{i}_ms"] = round(step.elapsed_ms, 1) if step else ""
        row[f"retries_{i}"] = step.retries_used if step else ""

    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
