"""분포 측정 (SPEC 4.4). 이 프로젝트에서 가장 중요한 스크립트.

임계값을 정하지 않는다. **측정만 한다.** 도출은 04_derive_thresholds.py가 한다.

산출물 (reports/):
  frame_features.csv        프레임 단위 원본 특징
  summary_shape_angles.csv  동작×조건×손가락×좌표계별 각도 요약
  summary_finger_roles.csv  '펴야 하는 손가락' vs '접어야 하는 손가락' 풀링 분포
  summary_detection.csv     조건별 검출 실패율/신뢰도
  summary_motion.csv        동작×윈도우길이별 변위비/주축비 요약
  summary_strokes.csv       MOVE 영상의 왕복 획 수
  fig_*.png                 겹쳐 그린 히스토그램과 궤적
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402


def _use_korean_font() -> None:
    """리포트 라벨이 한글이라 한글 글꼴이 없으면 네모로 깨진다."""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"):
        if name in available:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


_use_korean_font()

from core import features as F  # noqa: E402
from core.geometry import FINGER_NAMES, NON_THUMB_FINGERS  # noqa: E402
from core.landmark_io import HERE, load_all_clips, load_json, load_paths  # noqa: E402
from core.naming import MOVE_ACTIONS, SHAPE_ACTIONS  # noqa: E402

# 동작별로 어떤 손가락이 펴져 있어야 하는지 (SPEC 4.6의 패턴 표). 임계값이 아니라 정의다.
EXPECTED_PATTERN: dict[str, dict[str, bool]] = {
    "OPEN_PALM": {"index": True, "middle": True, "ring": True, "pinky": True},
    "FIST": {"index": False, "middle": False, "ring": False, "pinky": False},
    "INDEX": {"index": True, "middle": False, "ring": False, "pinky": False},
    "TWO_FINGERS": {"index": True, "middle": True, "ring": False, "pinky": False},
}
# 엄지는 판정에서 빼지만 임계값 자체는 데이터에서 뽑아야 하므로 따로 모은다.
THUMB_EXPECTED = {"OPEN_PALM": True, "FIST": False}

MOVE_AXIS = {"MOVE_LEFT": ("x", -1), "MOVE_RIGHT": ("x", +1),
             "MOVE_UP": ("y", -1), "MOVE_DOWN": ("y", +1)}


def build_frame_table(clips, policy) -> pd.DataFrame:
    rows = []
    for clip in clips:
        angles = {sp: F.frame_angles(clip, sp) for sp in policy["angle_spaces_considered"]}
        centers, scales = F.frame_palm_tracks(clip)
        n = clip.num_frames
        for i in range(n):
            row = {
                "stem": clip.meta.stem,
                "participant": clip.meta.participant,
                "action": clip.meta.action,
                "condition": clip.meta.condition or "none",
                "frame": i,
                "valid": bool(clip.valid_mask[i]),
                "detection_score": float(clip.detection_score[i]),
                "handedness": str(clip.handedness[i]),
                "hand_scale_px": float(scales[i]),
                "palm_x_px": float(centers[i, 0]),
                "palm_y_px": float(centers[i, 1]),
                "fps": clip.fps,
            }
            for sp, arr in angles.items():
                for j, name in enumerate(FINGER_NAMES):
                    row[f"angle_{sp}_{name}"] = float(arr[i, j])
            rows.append(row)
    return pd.DataFrame(rows)


def summarize_shape_angles(frames: pd.DataFrame, spaces) -> pd.DataFrame:
    rows = []
    valid = frames[frames["valid"]]
    for (action, condition), grp in valid.groupby(["action", "condition"], sort=True):
        for sp in spaces:
            for name in FINGER_NAMES:
                s = F.percentile_summary(grp[f"angle_{sp}_{name}"].to_numpy())
                rows.append({"action": action, "condition": condition,
                             "angle_space": sp, "finger": name, **s})
    return pd.DataFrame(rows)


def summarize_finger_roles(frames: pd.DataFrame, spaces) -> tuple[pd.DataFrame, dict]:
    """'펴야 하는 손가락'과 '접어야 하는 손가락'의 각도를 풀링한다.

    임계값 하나가 갈라야 하는 두 모집단이 정확히 이것이다.
    """
    valid = frames[frames["valid"]]
    pools: dict[tuple[str, str, str], list[np.ndarray]] = defaultdict(list)

    for action, pattern in EXPECTED_PATTERN.items():
        sub = valid[valid["action"] == action]
        if sub.empty:
            continue
        for sp in spaces:
            for finger, is_ext in pattern.items():
                role = "extended" if is_ext else "curled"
                pools[(sp, "others", role)].append(sub[f"angle_{sp}_{finger}"].to_numpy())
    for action, is_ext in THUMB_EXPECTED.items():
        sub = valid[valid["action"] == action]
        if sub.empty:
            continue
        for sp in spaces:
            role = "extended" if is_ext else "curled"
            pools[(sp, "thumb", role)].append(sub[f"angle_{sp}_thumb"].to_numpy())

    # 경계 케이스는 손가락 그룹 전체를 하나의 풀로 본다.
    for neg in ("NEG_halffist", "NEG_threefingers", "NEG_indexring", "NEG_indexpinky"):
        sub = valid[valid["action"] == neg]
        if sub.empty:
            continue
        for sp in spaces:
            pools[(sp, "others", neg)].append(
                np.concatenate([sub[f"angle_{sp}_{f}"].to_numpy() for f in NON_THUMB_FINGERS]))

    rows, raw = [], {}
    for (sp, group, role), arrays in sorted(pools.items()):
        values = np.concatenate(arrays)
        raw[(sp, group, role)] = values
        rows.append({"angle_space": sp, "finger_group": group, "role": role,
                     **F.percentile_summary(values)})
    return pd.DataFrame(rows), raw


def summarize_detection(frames: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, grp in frames.groupby(["condition", "action"], sort=True):
        condition, action = keys
        scores = grp.loc[grp["valid"], "detection_score"].to_numpy()
        rows.append({"condition": condition, "action": action,
                     "frames": len(grp),
                     "valid_frames": int(grp["valid"].sum()),
                     "fail_ratio": float(1.0 - grp["valid"].mean()),
                     **{f"score_{k}": v for k, v in F.percentile_summary(scores).items()}})
    for condition, grp in frames.groupby("condition", sort=True):
        scores = grp.loc[grp["valid"], "detection_score"].to_numpy()
        rows.append({"condition": condition, "action": "(전체)",
                     "frames": len(grp),
                     "valid_frames": int(grp["valid"].sum()),
                     "fail_ratio": float(1.0 - grp["valid"].mean()),
                     **{f"score_{k}": v for k, v in F.percentile_summary(scores).items()}})
    return pd.DataFrame(rows)


def collect_motions(clips, window_ms_grid) -> pd.DataFrame:
    rows = []
    for clip in clips:
        centers, scales = F.frame_palm_tracks(clip)
        for window_ms in window_ms_grid:
            wf = int(round(window_ms / 1000.0 * clip.fps)) if clip.fps > 0 else 0
            for m in F.sliding_window_motions(centers, scales, wf):
                if not m.valid:
                    continue
                rows.append({"stem": clip.meta.stem,
                             "participant": clip.meta.participant,
                             "action": clip.meta.action,
                             "condition": clip.meta.condition or "none",
                             "window_ms": window_ms,
                             "window_frames": wf,
                             "displacement_ratio": m.displacement_ratio,
                             "axis_ratio": m.axis_ratio,
                             "axis": m.axis, "sign": m.sign,
                             "dx_ratio": m.dx_ratio, "dy_ratio": m.dy_ratio,
                             "coverage": m.coverage})
    return pd.DataFrame(rows)


def summarize_motion(motions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, grp in motions.groupby(["action", "condition", "window_ms"], sort=True):
        action, condition, window_ms = keys
        disp = F.percentile_summary(grp["displacement_ratio"].to_numpy())
        finite_axis = grp["axis_ratio"].replace([np.inf, -np.inf], np.nan).to_numpy()
        axis = F.percentile_summary(finite_axis)
        correct = np.nan
        if action in MOVE_AXIS:
            want_axis, want_sign = MOVE_AXIS[action]
            correct = float(((grp["axis"] == want_axis) & (grp["sign"] == want_sign)).mean())
        rows.append({"action": action, "condition": condition, "window_ms": window_ms,
                     "n_windows": len(grp),
                     **{f"disp_{k}": v for k, v in disp.items()},
                     **{f"axisratio_{k}": v for k, v in axis.items()},
                     "axis_ratio_inf_share": float(np.isinf(grp["axis_ratio"]).mean()),
                     "correct_direction_share": correct})
    return pd.DataFrame(rows)


def summarize_strokes(clips, amplitude_grid) -> pd.DataFrame:
    rows = []
    for clip in clips:
        if clip.meta.action not in MOVE_ACTIONS and clip.meta.action != "NEG_shake":
            continue
        centers, scales = F.frame_palm_tracks(clip)
        axis_idx = 0 if clip.meta.action in ("MOVE_LEFT", "MOVE_RIGHT", "NEG_shake") else 1
        for amp in amplitude_grid:
            rows.append({"stem": clip.meta.stem, "action": clip.meta.action,
                         "condition": clip.meta.condition or "none",
                         "amplitude_ratio": amp,
                         "strokes": F.count_strokes(centers, axis_idx, scales, amp)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 그림


def _overlay_hist(ax, series: dict[str, np.ndarray], bins: int, title: str, xlabel: str):
    finite = [v[np.isfinite(v)] for v in series.values() if v is not None]
    finite = [v for v in finite if v.size]
    if not finite:
        ax.set_title(f"{title} (데이터 없음)")
        return
    lo = min(float(v.min()) for v in finite)
    hi = max(float(v.max()) for v in finite)
    edges = np.linspace(lo, hi, bins + 1) if hi > lo else bins
    for label, values in series.items():
        v = np.asarray(values, float)
        v = v[np.isfinite(v)]
        if v.size:
            ax.hist(v, bins=edges, alpha=0.5, label=f"{label} (n={v.size})", density=True)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.legend(fontsize=7)


def plot_shape_overlays(frames, out_dir, bins, spaces):
    valid = frames[frames["valid"]]
    groups = [("OPEN_PALM_FIST_halffist", ["OPEN_PALM", "FIST", "NEG_halffist"]),
              ("TWO_FINGERS_negatives", ["TWO_FINGERS", "NEG_threefingers",
                                         "NEG_indexring", "NEG_indexpinky"])]
    for sp in spaces:
        for tag, actions in groups:
            present = [a for a in actions if (valid["action"] == a).any()]
            fig, axes = plt.subplots(1, len(FINGER_NAMES), figsize=(22, 3.6))
            for ax, finger in zip(axes, FINGER_NAMES):
                series = {a: valid.loc[valid["action"] == a,
                                       f"angle_{sp}_{finger}"].to_numpy() for a in present}
                _overlay_hist(ax, series, bins, finger, "관절 각도(도)")
            fig.suptitle(f"{tag} / angle_space={sp}")
            fig.tight_layout()
            fig.savefig(out_dir / f"fig_angles_{tag}_{sp}.png", dpi=110)
            plt.close(fig)

        # 조건(near/far/dark)별로 같은 동작의 각도가 흔들리는지
        fig, axes = plt.subplots(1, len(SHAPE_ACTIONS), figsize=(20, 3.6))
        for ax, action in zip(axes, SHAPE_ACTIONS):
            sub = valid[valid["action"] == action]
            series = {c: np.concatenate([sub.loc[sub["condition"] == c,
                                                 f"angle_{sp}_{f}"].to_numpy()
                                         for f in NON_THUMB_FINGERS])
                      for c in sorted(sub["condition"].unique())}
            _overlay_hist(ax, series, bins, action, "관절 각도(도)")
        fig.suptitle(f"조건별 각도 분포 (엄지 제외 4손가락 풀링) / angle_space={sp}")
        fig.tight_layout()
        fig.savefig(out_dir / f"fig_angles_by_condition_{sp}.png", dpi=110)
        plt.close(fig)


def plot_detection(frames, detection, out_dir, bins):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    overall = detection[detection["action"] == "(전체)"].sort_values("condition")
    axes[0].bar(overall["condition"], overall["fail_ratio"] * 100.0, color="tab:red")
    axes[0].set_title("조건별 손 검출 실패율")
    axes[0].set_ylabel("실패 프레임 %")
    for x, y in zip(overall["condition"], overall["fail_ratio"] * 100.0):
        axes[0].text(x, y, f"{y:.1f}%", ha="center", va="bottom", fontsize=9)

    series = {c: frames.loc[frames["valid"] & (frames["condition"] == c),
                            "detection_score"].to_numpy()
              for c in sorted(frames["condition"].unique())}
    _overlay_hist(axes[1], series, bins, "조건별 detection_score", "score")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_detection.png", dpi=110)
    plt.close(fig)


def plot_motion(motions, out_dir, bins, focus_ms):
    sub = motions[motions["window_ms"] == focus_ms]
    fig, axes = plt.subplots(1, 3, figsize=(19, 4))

    move = sub[sub["action"].isin(MOVE_ACTIONS)]["displacement_ratio"].to_numpy()
    shake = sub[sub["action"] == "NEG_shake"]["displacement_ratio"].to_numpy()
    diagonal = sub[sub["action"] == "NEG_diagonal"]["displacement_ratio"].to_numpy()
    _overlay_hist(axes[0], {"MOVE_*": move, "NEG_shake": shake, "NEG_diagonal": diagonal},
                  bins, f"정규화 변위 (window={focus_ms}ms)", "변위 / 손 크기")

    def axis_ratio_of(mask):
        v = sub.loc[mask, "axis_ratio"].replace([np.inf], np.nan).to_numpy()
        return v
    _overlay_hist(axes[1],
                  {"MOVE_LEFT": axis_ratio_of(sub["action"] == "MOVE_LEFT"),
                   "MOVE_RIGHT": axis_ratio_of(sub["action"] == "MOVE_RIGHT"),
                   "NEG_diagonal": axis_ratio_of(sub["action"] == "NEG_diagonal")},
                  bins, f"주축/부축 비율 (window={focus_ms}ms)", "|주축| / |부축|")

    move_sub = sub[sub["action"].isin(MOVE_ACTIONS)]
    _overlay_hist(axes[2],
                  {c: move_sub.loc[move_sub["condition"] == c,
                                   "displacement_ratio"].to_numpy()
                   for c in sorted(move_sub["condition"].unique())},
                  bins, "near/far 정규화 후 겹침 확인", "변위 / 손 크기")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_motion.png", dpi=110)
    plt.close(fig)


def plot_trajectories(clips, out_dir):
    targets = [c for c in clips
               if c.meta.action in MOVE_ACTIONS or c.meta.action in ("NEG_shake", "NEG_diagonal")]
    if not targets:
        return
    cols = 4
    rows = int(np.ceil(len(targets) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.6 * cols, 2.8 * rows), squeeze=False)
    for ax, clip in zip(axes.ravel(), targets):
        centers, scales = F.frame_palm_tracks(clip)
        scale = float(np.nanmedian(scales))
        t = np.arange(clip.num_frames) / (clip.fps or 1.0)
        ax.plot(t, (centers[:, 0] - np.nanmean(centers[:, 0])) / scale, label="x")
        ax.plot(t, (centers[:, 1] - np.nanmean(centers[:, 1])) / scale, label="y")
        ax.set_title(clip.meta.stem, fontsize=8)
        ax.set_xlabel("초")
        ax.set_ylabel("변위/손크기")
        ax.legend(fontsize=6)
    for ax in axes.ravel()[len(targets):]:
        ax.axis("off")
    fig.suptitle("MOVE / NEG 궤적 — 왕복 3회가 보이는지 확인")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_trajectories.png", dpi=100)
    plt.close(fig)


def main() -> int:
    paths = load_paths()
    policy = load_json(HERE / "configs" / "derivation_policy.json")
    mirror_flip = paths.get("mirror_flip") or {}
    if not mirror_flip:
        print("[경고] paths.json에 mirror_flip이 비어 있다. 02_check_mirror.py를 먼저 실행할 것.",
              file=sys.stderr)

    clips = load_all_clips(paths["landmark_cache"], mirror_flip)
    if not clips:
        print("랜드마크 캐시가 없다.", file=sys.stderr)
        return 1
    out_dir = Path(paths["report_out"])
    out_dir.mkdir(parents=True, exist_ok=True)
    spaces = policy["angle_spaces_considered"]
    bins = policy["histogram_bins"]

    print(f"영상 {len(clips)}개 로드 (mirror_flip={mirror_flip})")
    frames = build_frame_table(clips, policy)
    frames.to_csv(out_dir / "frame_features.csv", index=False, encoding="utf-8-sig")
    print(f"프레임 {len(frames)}행")

    shape_summary = summarize_shape_angles(frames, spaces)
    shape_summary.to_csv(out_dir / "summary_shape_angles.csv", index=False, encoding="utf-8-sig")

    roles, role_raw = summarize_finger_roles(frames, spaces)
    roles.to_csv(out_dir / "summary_finger_roles.csv", index=False, encoding="utf-8-sig")

    detection = summarize_detection(frames)
    detection.to_csv(out_dir / "summary_detection.csv", index=False, encoding="utf-8-sig")

    motions = collect_motions(clips, policy["motion_window_ms_grid"])
    motion_summary = summarize_motion(motions)
    motion_summary.to_csv(out_dir / "summary_motion.csv", index=False, encoding="utf-8-sig")

    amplitude_grid = [round(x, 2) for x in np.arange(0.2, 2.01, 0.1)]
    strokes = summarize_strokes(clips, amplitude_grid)
    strokes.to_csv(out_dir / "summary_strokes.csv", index=False, encoding="utf-8-sig")

    focus_ms = int(np.median(policy["motion_window_ms_grid"]))
    plot_shape_overlays(frames, out_dir, bins, spaces)
    plot_detection(frames, detection, out_dir, bins)
    plot_motion(motions, out_dir, bins, focus_ms)
    plot_trajectories(clips, out_dir)

    # ---- 콘솔 요약 ----
    print("\n=== 손가락 역할별 각도 분포 (임계값이 갈라야 할 두 모집단) ===")
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(roles[["angle_space", "finger_group", "role", "n", "mean", "std",
                     "p5", "p50", "p95"]].to_string(index=False))

    print("\n=== 조건별 검출 실패율 ===")
    print(detection[detection["action"] == "(전체)"][
        ["condition", "frames", "valid_frames", "fail_ratio", "score_p5", "score_p50"]
    ].to_string(index=False))

    print(f"\n=== 이동 지표 (window={focus_ms}ms) ===")
    m = motion_summary[motion_summary["window_ms"] == focus_ms]
    print(m[["action", "condition", "n_windows", "disp_p5", "disp_p50", "disp_p95",
             "axisratio_p5", "axisratio_p50", "axisratio_p95",
             "correct_direction_share"]].to_string(index=False))

    print(f"\n리포트 저장 위치: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
