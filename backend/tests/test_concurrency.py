"""동시 요청 (명세 10장). 백엔드는 AI 호출에 락을 걸지 않는다 (명세 8장)."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.conftest import post_json
from tests.payloads import enroll_same_body, stub_prediction, verify_body

USERS = [f"user{i}" for i in range(6)]


def test_parallel_enroll_and_verify_mixed(client):
    gesture = stub_prediction(0)
    for uid in USERS:
        client.post("/users", json={"id": uid, "name": uid})
    for uid in USERS[:3]:
        post_json(client, "/enroll", enroll_same_body(uid, gesture, 0))

    jobs = []
    for i in range(30):
        uid = USERS[i % 6]
        if uid in USERS[3:] and i < 12:
            jobs.append(("/enroll", enroll_same_body(uid, gesture, 0)))
        else:
            jobs.append(("/verify", verify_body(uid, 0)))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda j: post_json(client, *j), jobs))

    assert [r.status_code for r in results] == [200] * len(jobs)
    for (url, body), res in zip(jobs, results):
        if url == "/verify" and body["userId"] in USERS[:3]:
            assert res.json()["passed"] is True
            assert res.json()["score"] == pytest.approx(1.0, abs=1e-5)

    # 병렬 등록 이후에는 모두 통과
    for uid in USERS:
        assert post_json(client, "/verify", verify_body(uid, 0)).json()["passed"] is True
    assert len(client.get("/users").json()) == 6


def test_parallel_verify_during_threshold_switch(client):
    gesture = stub_prediction(0)
    client.post("/users", json={"id": "kim", "name": "김길동"})
    post_json(client, "/enroll", enroll_same_body("kim", gesture, 0))

    def work(i):
        if i % 5 == 0:
            return client.post("/admin/threshold", json={"basis": ["eer", "far5", "far1"][i % 3]})
        return post_json(client, "/verify", verify_body("kim", 0))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(work, range(40)))
    assert all(r.status_code == 200 for r in results)
    thresholds = {r.json()["threshold"] for r in results if "score" in r.json()}
    assert thresholds <= {0.627516, 0.436046, 0.272128}
    assert client.get("/logs").json()["total"] == 32


def test_async_gather_verify(client):
    """ASGI 레벨에서 진짜 동시 코루틴으로 보낸다."""
    gesture = stub_prediction(0)
    client.post("/users", json={"id": "kim", "name": "김길동"})
    post_json(client, "/enroll", enroll_same_body("kim", gesture, 0))
    app = client.app
    bodies = [verify_body("kim", i % 3) for i in range(30)]

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await asyncio.gather(*[
                ac.post("/verify", content=json.dumps(b), headers={"Content-Type": "application/json"})
                for b in bodies
            ])

    results = asyncio.run(run())
    assert all(r.status_code == 200 for r in results)
    by_seed: dict[int, set] = {}
    for i, r in enumerate(results):
        d = r.json()
        by_seed.setdefault(i % 3, set()).add((d["predictedGesture"], d["score"], d["passed"]))
    assert all(len(v) == 1 for v in by_seed.values())  # 같은 입력 → 같은 결과
    (predicted, score, passed), = by_seed[0]
    assert (predicted, passed) == (gesture, True) and score == pytest.approx(1.0, abs=1e-5)
