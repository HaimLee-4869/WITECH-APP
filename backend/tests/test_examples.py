"""README 앱팀 전달용 예시 파일이 실제로 통과하는지 (규격 문서가 코드와 어긋나지 않게)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import post_json

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_example_payloads_are_accepted(client):
    client.post("/users", json={"id": "kim", "name": "김길동", "department": "개발팀"})

    enroll = post_json(client, "/enroll", _load("enroll_request.json"))
    assert enroll.status_code == 200, enroll.text
    assert enroll.json()["enrolled"] is True

    body = _load("verify_request.json")
    verify = post_json(client, "/verify", body)
    assert verify.status_code == 200, verify.text
    assert verify.json()["reason"] != "invalid_input"


def test_verify_example_covers_documented_rules():
    body = _load("verify_request.json")
    assert body["camera"] == {"width": 720, "height": 1280}
    assert any(f["lm"] is None for f in body["frames"])            # 손 없는 프레임 표기
    t = [f["tMs"] for f in body["frames"]]
    assert t == sorted(set(t)) and t[-1] - t[0] >= 750
    assert sum(1 for f in body["frames"] if f["lm"]) >= 8
    assert body["capturedAt"].endswith("+09:00")


def test_enroll_example_shape():
    body = _load("enroll_request.json")
    assert [t["takeNo"] for t in body["takes"]] == [1, 2, 3]
    assert all(len(f["lm"]) == 21 for t in body["takes"] for f in t["frames"])
