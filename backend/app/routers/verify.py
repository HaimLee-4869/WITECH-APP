from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.schemas import VerifyRequest, VerifyResponse
from app.services import auth_service

router = APIRouter(tags=["verify"])


@router.post("/verify", response_model=VerifyResponse)
async def verify(body: VerifyRequest, request: Request) -> VerifyResponse:
    # auth_logs.landmarks_json에는 앱이 보낸 바이트를 그대로 남긴다 (추가 학습 데이터).
    raw = (await request.body()).decode("utf-8")
    settings = request.app.state.settings

    def work():
        with request.app.state.db.session() as session:
            return auth_service.verify(session, settings, body, raw)

    return await run_in_threadpool(work)
