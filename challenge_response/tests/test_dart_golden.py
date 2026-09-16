"""Dart 대조용 골든 파일이 현재 규칙과 맞는지.

규칙을 고치고 골든을 다시 뽑지 않으면, Dart 테스트는 **옛 규칙**을 통과시키면서
초록으로 남는다. 두 구현이 갈라진 것을 아무도 모르게 된다. 그걸 막는다.

깨졌을 때:
    cd challenge_response
    python scripts/export_dart_golden.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import export_dart_golden as exporter

GOLDEN = Path(__file__).resolve().parent.parent.parent / "test" / "challenge" / "golden" / "cross_impl.json"


@pytest.fixture(scope="module")
def saved() -> dict:
    if not GOLDEN.exists():
        pytest.fail(f"골든이 없다: {GOLDEN}\npython scripts/export_dart_golden.py 실행할 것")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_rule_version_matches(saved):
    assert saved["ruleVersion"] == exporter.RULE_VERSION, (
        "판정 규칙이 바뀌었다. scripts/export_dart_golden.py를 다시 돌릴 것."
    )


def test_shape_results_are_current(saved):
    detector = exporter.HandActionDetector(exporter.CONFIG)
    fresh = {c["name"]: c for c in exporter.shape_cases(detector)}
    for case in saved["shapeCases"]:
        now = fresh[case["name"]]
        assert now["label"] == case["label"], case["name"]
        assert now["confidence"] == case["confidence"], case["name"]


def test_move_results_are_current(saved):
    movement = exporter.MovementDetector(exporter.CONFIG)
    fresh = {c["name"]: c for c in exporter.move_cases(movement)}
    for case in saved["moveCases"]:
        now = fresh[case["name"]]
        assert now["label"] == case["label"], case["name"]
        assert now["reason"] == case["reason"], case["name"]


def test_mirrored_labels_are_current(saved):
    fresh = {c["name"]: c for c in exporter.mirrored_move_cases()}
    for case in saved["mirroredMoveCases"]:
        assert fresh[case["name"]]["label"] == case["label"], case["name"]


def test_sequence_results_are_current(saved):
    fresh = {c["name"]: c for c in exporter.sequence_cases()}
    for case in saved["sequenceCases"]:
        now = fresh[case["name"]]
        assert now["state"] == case["state"], case["name"]
        assert now["failReason"] == case["failReason"], case["name"]
        assert now["stepsPassed"] == case["stepsPassed"], case["name"]


def test_golden_covers_the_rules_we_care_about(saved):
    """사라지면 안 되는 대조 항목."""
    names = {c["name"] for c in saved["sequenceCases"]}
    assert {"opposite_direction_fails_immediately",
            "escape_gate_blocks_free_pass",
            "escape_then_pass",
            "wrong_order"} <= names

    move_names = {c["name"] for c in saved["moveCases"]}
    assert {"diagonal_45", "diagonal_just_under", "too_small"} <= move_names
    assert len(saved["mirroredMoveCases"]) == 4
