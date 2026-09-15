from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.schemas import EnrollRequest, EnrollResponse
from app.services import enroll_service

router = APIRouter(tags=["enroll"])


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(body: EnrollRequest, request: Request) -> EnrollResponse:
    # 원본 JSON을 손실 없이 저장하기 위해 파싱 전 body도 받는다.
    raw = await request.json()

    def work():
        with request.app.state.db.session() as session:
            return enroll_service.enroll(session, body, raw)

    # 임베딩은 CPU 작업이므로 이벤트 루프 밖에서
    return await run_in_threadpool(work)
