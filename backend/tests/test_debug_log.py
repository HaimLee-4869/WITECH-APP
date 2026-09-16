"""POST /debug/challenge — 앱이 보낸 Challenge 판정 로그.

개발용 엔드포인트다. 인증이 없으므로 끌 수 있어야 하고, 앱이 보낸 문자열이
그대로 파일에 들어가므로 한 줄 형식이 깨지지 않아야 한다.
"""

from __future__ import annotations

import pytest

from app.routers import debug


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    """진짜 backend/logs/를 건드리지 않는다."""
    path = tmp_path / "challenge_debug.log"
    monkeypatch.setattr(debug, "LOG_DIR", tmp_path)
    monkeypatch.setattr(debug, "LOG_PATH", path)
    return path


def test_writes_lines_to_file(client, isolated_log):
    res = client.post("/debug/challenge", json={
        "sessionId": "3f2a",
        "lines": [
            "CHALLENGE begin id=3f2a actions=[FIST,MOVE_LEFT,OPEN_PALM]",
            "CHALLENGE move req=MOVE_LEFT win=560/550ms(8f)O disp=0.150/0.226(x0.66)X",
        ],
    })
    assert res.status_code == 200
    assert res.json()["written"] == 2

    text = isolated_log.read_text(encoding="utf-8")
    assert "CHALLENGE begin" in text
    assert "disp=0.150/0.226(x0.66)X" in text
    assert "[3f2a]" in text
    # 보낸 줄 수만큼만 늘어난다 (한 줄 형식 유지)
    assert len(text.strip().splitlines()) == 2


def test_appends_across_requests(client, isolated_log):
    """세션 하나를 통째로 복사해 볼 수 있어야 한다."""
    for i in range(3):
        client.post("/debug/challenge", json={
            "sessionId": "s", "lines": [f"CHALLENGE move seq={i}"],
        })
    assert len(isolated_log.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_newlines_in_a_line_do_not_break_the_format(client, isolated_log):
    """앱이 실수로 줄바꿈을 넣어도 한 줄로 남아야 grep이 쓸모 있다."""
    client.post("/debug/challenge", json={
        "sessionId": "s", "lines": ["CHALLENGE move a=1\nFAKE injected line"],
    })
    lines = isolated_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "FAKE injected line" in lines[0]


def test_long_line_is_truncated(client, isolated_log):
    client.post("/debug/challenge", json={
        "sessionId": "s", "lines": ["CHALLENGE " + "x" * 5000],
    })
    line = isolated_log.read_text(encoding="utf-8").strip()
    assert len(line) < 2200


def test_get_returns_the_log_as_text(client, isolated_log):
    client.post("/debug/challenge", json={
        "sessionId": "s", "lines": ["CHALLENGE result PASS steps=3/3"],
    })
    res = client.get("/debug/challenge")
    assert res.status_code == 200
    assert "CHALLENGE result PASS" in res.text


def test_get_tail(client, isolated_log):
    client.post("/debug/challenge", json={
        "sessionId": "s", "lines": [f"CHALLENGE n={i}" for i in range(10)],
    })
    res = client.get("/debug/challenge", params={"lines": 3})
    assert res.text.strip().splitlines() == [
        line for line in res.text.strip().splitlines()
    ]
    assert len(res.text.strip().splitlines()) == 3
    assert "n=9" in res.text


def test_get_on_empty_log(client, isolated_log):
    assert "비어 있음" in client.get("/debug/challenge").text


def test_delete_clears(client, isolated_log):
    client.post("/debug/challenge", json={"sessionId": "s", "lines": ["CHALLENGE x"]})
    assert isolated_log.exists()
    assert client.delete("/debug/challenge").status_code == 200
    assert not isolated_log.exists()


def test_rejects_empty_batch(client):
    res = client.post("/debug/challenge", json={"sessionId": "s", "lines": []})
    assert res.status_code == 422


def test_can_be_turned_off(client, db, isolated_log):
    """인증이 없는 엔드포인트라 끌 수 있어야 한다."""
    client.app.state.settings.debug_log_enabled = False
    try:
        assert client.post(
            "/debug/challenge", json={"sessionId": "s", "lines": ["x"]}
        ).status_code == 404
        assert client.get("/debug/challenge").status_code == 404
    finally:
        client.app.state.settings.debug_log_enabled = True
