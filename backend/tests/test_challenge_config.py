"""Challenge 설정이 GET /config로 내려가고 PATCH로 조정되는지.

앱은 임계값을 하나도 갖고 있지 않다. 여기가 깨지면 앱이 판정을 못 한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import app_config_service as cfg

BACKEND_DIR = Path(__file__).resolve().parent.parent
SOURCE = BACKEND_DIR.parent / "challenge_response" / "configs" / "challenge_config.json"


def test_config_includes_challenge(client):
    body = client.get("/config").json()["challenge"]

    assert body["angleSpace"] == "image_iso"
    assert body["coordinateFrame"] == "mirrored"
    assert body["frameReferenceFps"] == 30.0
    assert body["fingerExtendedAngle"] == {"thumb": 148.9, "others": 135.9}
    assert body["shapeHoldFrames"] == 7
    assert body["escapeFrames"] == 14
    assert body["movement"]["minDisplacementRatio"] == 0.226
    assert body["movement"]["axisDominanceRatio"] == 3.634
    assert body["timing"] == {
        "perActionTimeoutMs": 2000, "totalTimeoutMs": 6000, "maxRetries": 1,
        # 손을 들기 전에는 제한 시간이 흐르지 않는다 (앱 대기 단계)
        "waitHandReadyMs": 400, "waitHandTimeoutMs": 15000,
        # 단계 사이에 동작을 준비할 시간 (제한 시간이 흐르지 않는다)
        "stepPrepareMs": 1500,
        # 단계 결과(PASS/FAIL)를 보여주는 시간 (역시 흐르지 않는다)
        "stepResultHoldMs": 1500,
    }
    assert body["steps"] == {"numShapes": 2, "numMoves": 1}


def test_null_gates_stay_null(client):
    """도출 실패(null)를 0이나 임의값으로 채우지 않는다. null이 '게이트를 끈다'는 뜻이다."""
    body = client.get("/config").json()["challenge"]
    assert body["shapeConfidenceMin"] is None
    assert body["fistMaxTipWristRatio"] == 0.909


def test_direction_map_covers_move_pool(client):
    body = client.get("/config").json()["challenge"]
    assert set(body["movePool"]) <= set(body["movement"]["directionMap"])
    assert body["movement"]["directionMap"]["MOVE_LEFT"] == ["x", -1]
    assert body["movement"]["directionMap"]["MOVE_UP"] == ["y", -1]


@pytest.mark.parametrize(
    "patch, path, expected",
    [
        ({"timing": {"perActionTimeoutMs": 2500}}, ("timing", "perActionTimeoutMs"), 2500),
        ({"escapeFrames": 8}, ("escapeFrames",), 8),
        ({"shapeHoldFrames": 5}, ("shapeHoldFrames",), 5),
        ({"steps": {"numShapes": 1, "numMoves": 1}}, ("steps", "numShapes"), 1),
    ],
)
def test_patch_adjusts_timing_knobs(client, patch, path, expected):
    """실기기 체감에 맞춰 서버 값만 바꾼다. 앱 재배포 없이."""
    res = client.patch("/admin/config", json={"challenge": patch})
    assert res.status_code == 200, res.text

    node = res.json()["challenge"]
    for key in path:
        node = node[key]
    assert node == expected

    # 다시 읽어도 유지된다 (DB에 저장됐다)
    node = client.get("/config").json()["challenge"]
    for key in path:
        node = node[key]
    assert node == expected


def test_patch_merges_instead_of_replacing(client):
    """일부 키만 보내면 나머지는 그대로 있어야 한다."""
    client.patch("/admin/config", json={"challenge": {"timing": {"perActionTimeoutMs": 2500}}})
    body = client.get("/config").json()["challenge"]

    assert body["timing"]["perActionTimeoutMs"] == 2500
    assert body["timing"]["totalTimeoutMs"] == 6000     # 안 보낸 값
    assert body["timing"]["maxRetries"] == 1
    assert body["movement"]["minDisplacementRatio"] == 0.226


def test_patch_rejects_invalid_and_keeps_previous(client):
    """검증 실패면 아무것도 바꾸지 않는다. 반쯤 적용된 설정이 남으면 안 된다."""
    res = client.patch("/admin/config", json={"challenge": {"escapeFrames": -5}})
    assert res.status_code == 422
    assert res.json()["detail"]["reason"] == "invalid_challenge_config"

    assert client.get("/config").json()["challenge"]["escapeFrames"] == 14


def test_patch_rejects_more_shapes_than_pool(client):
    """서로 다른 모양 5개를 4개 풀에서 뽑을 수 없다."""
    res = client.patch("/admin/config", json={"challenge": {"steps": {"numShapes": 5, "numMoves": 1}}})
    assert res.status_code == 422


def test_patch_warns_when_total_timeout_too_small(client, caplog):
    """단계 수 × 단계 제한보다 전체 제한이 작으면 마지막 단계가 죽는다."""
    with caplog.at_level("WARNING"):
        res = client.patch(
            "/admin/config",
            json={"challenge": {"timing": {"perActionTimeoutMs": 3000, "totalTimeoutMs": 4000}}},
        )
    assert res.status_code == 200
    assert "TOTAL_TIMEOUT" in caplog.text


def test_patch_logs_frame_values_in_ms(client, caplog):
    """프레임 수를 바꾸면 기준 fps에서 몇 ms인지 함께 남긴다."""
    with caplog.at_level("WARNING"):
        client.patch("/admin/config", json={"challenge": {"escapeFrames": 6}})
    assert "challenge.escapeFrames 14 → 6" in caplog.text
    assert "200ms" in caplog.text     # 6프레임 @ 30fps


def test_other_config_patch_still_works(client):
    """challenge를 안 보내면 기존 동작 그대로."""
    res = client.patch("/admin/config", json={"enrollmentTakes": 4})
    assert res.status_code == 200
    assert res.json()["enrollmentTakes"] == 4
    assert res.json()["challenge"]["shapeHoldFrames"] == 7


# --- 원본과의 일치 ------------------------------------------------------------------

def test_defaults_match_challenge_response_source():
    """번들 기본값이 challenge_response 원본에서 벗어나지 않았는지.

    두 파일이 조용히 갈라지면 앱이 도출과 다른 임계값으로 판정하게 된다.
    """
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    bundled = cfg.default_challenge_config()

    assert bundled["angleSpace"] == source["angle_space"]
    assert bundled["coordinateFrame"] == source["coordinate_frame"]
    assert bundled["frameReferenceFps"] == source["frame_reference_fps"]
    assert bundled["shapeHoldFrames"] == source["shape_hold_frames"]
    assert bundled["escapeFrames"] == source["escape_frames"]
    assert bundled["shapeConfidenceMarginDeg"] == source["shape_confidence_margin_deg"]
    assert bundled["shapeConfidenceMin"] == source["shape_confidence_min"]
    assert bundled["fistMaxTipWristRatio"] == source["fist_max_tip_wrist_ratio"]
    assert bundled["fingerExtendedAngle"]["thumb"] == source["finger_extended_angle"]["thumb"]
    assert bundled["fingerExtendedAngle"]["others"] == source["finger_extended_angle"]["others"]

    move_src, move_out = source["movement"], bundled["movement"]
    assert move_out["windowMs"] == move_src["window_ms"]
    assert move_out["minDisplacementRatio"] == move_src["min_displacement_ratio"]
    assert move_out["axisDominanceRatio"] == move_src["axis_dominance_ratio"]
    assert move_out["maxDurationMs"] == move_src["max_duration_ms"]
    assert move_out["restDisplacementRatio"] == move_src["rest_displacement_ratio"]
    assert {k: list(v) for k, v in move_out["directionMap"].items()} == move_src["direction_map"]

    for key, src_key in (("perActionTimeoutMs", "per_action_timeout_ms"),
                         ("totalTimeoutMs", "total_timeout_ms"),
                         ("maxRetries", "max_retries")):
        assert bundled["timing"][key] == source["timing"][src_key]
    assert bundled["tracking"]["maxLostFrames"] == source["tracking"]["max_lost_frames"]
    assert bundled["tracking"]["minDetectionScore"] == source["tracking"]["min_detection_score"]


def test_import_script_dry_run_reports_no_change():
    """번들 기본값이 원본과 같으므로 dry-run에 바뀐 값이 없어야 한다."""
    out = subprocess.run(
        [sys.executable, "scripts/import_challenge_config.py", "--dry-run"],
        cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8",
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "바뀐 값 없음" in out.stdout
    assert "저장하지 않았다" in out.stdout


def test_direction_map_is_replaced_not_merged(client):
    """방향 표를 부분 병합하면 나머지가 옛 도출값으로 남아 조용히 어긋난다."""
    res = client.patch("/admin/config", json={"challenge": {"movement": {"directionMap": {
        "MOVE_LEFT": ["x", 1], "MOVE_RIGHT": ["x", -1],
        "MOVE_UP": ["y", 1], "MOVE_DOWN": ["y", -1],
    }}}})
    assert res.status_code == 200

    table = res.json()["challenge"]["movement"]["directionMap"]
    assert table == {
        "MOVE_LEFT": ["x", 1], "MOVE_RIGHT": ["x", -1],
        "MOVE_UP": ["y", 1], "MOVE_DOWN": ["y", -1],
    }
    # 같은 요청의 다른 movement 키는 병합으로 남아 있어야 한다
    assert res.json()["challenge"]["movement"]["minDisplacementRatio"] == 0.226


def test_partial_direction_map_is_rejected(client):
    """일부 방향만 보내면 movePool을 못 덮어 검증에서 걸린다."""
    res = client.patch("/admin/config", json={
        "challenge": {"movement": {"directionMap": {"MOVE_LEFT": ["x", 1]}}}
    })
    assert res.status_code == 422
    assert client.get("/config").json()["challenge"]["movement"]["directionMap"][
        "MOVE_RIGHT"] == ["x", 1]


def test_frame_stale_knobs_are_served(client):
    """'손 없음' 판단 기준도 서버가 정한다. 앱에 고정 상수를 두지 않는다."""
    tracking = client.get("/config").json()["challenge"]["tracking"]
    assert tracking["frameStaleFactor"] == 3.0
    assert tracking["frameStaleMinMs"] == 150
    assert tracking["frameStaleMaxMs"] == 800


def test_frame_stale_factor_is_adjustable(client):
    res = client.patch(
        "/admin/config",
        json={"challenge": {"tracking": {"frameStaleFactor": 4.5}}},
    )
    assert res.status_code == 200
    assert res.json()["challenge"]["tracking"]["frameStaleFactor"] == 4.5
    # 나머지는 그대로
    assert res.json()["challenge"]["tracking"]["maxLostFrames"] == 38


def test_frame_stale_bounds_must_be_ordered(client):
    res = client.patch(
        "/admin/config",
        json={"challenge": {"tracking": {"frameStaleMinMs": 900}}},  # max 800보다 큼
    )
    assert res.status_code == 422
    assert client.get("/config").json()["challenge"]["tracking"]["frameStaleMinMs"] == 150


def test_step_prepare_is_adjustable(client):
    """단계 사이 여유를 실기기 체감으로 조정한다."""
    res = client.patch(
        "/admin/config", json={"challenge": {"timing": {"stepPrepareMs": 2500}}}
    )
    assert res.status_code == 200
    timing = res.json()["challenge"]["timing"]
    assert timing["stepPrepareMs"] == 2500
    assert timing["perActionTimeoutMs"] == 2000  # 나머지는 그대로


def test_step_result_hold_is_adjustable(client):
    """PASS/FAIL 표시 시간도 실기기 체감으로 조정한다."""
    res = client.patch(
        "/admin/config", json={"challenge": {"timing": {"stepResultHoldMs": 2500}}}
    )
    assert res.status_code == 200
    timing = res.json()["challenge"]["timing"]
    assert timing["stepResultHoldMs"] == 2500
    assert timing["stepPrepareMs"] == 1500      # 나머지는 그대로
    assert timing["perActionTimeoutMs"] == 2000
