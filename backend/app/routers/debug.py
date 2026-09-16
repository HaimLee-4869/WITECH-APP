"""POST /debug/challenge — 앱의 Challenge 판정 로그를 받는다.

안티스푸핑 Challenge 판정은 앱에서 한다. 실기기 화면의 진단 패널은 프레임마다
바뀌어 읽을 수 없으므로, 앱이 한 줄씩 보내고 여기서 파일과 콘솔에 남긴다.

- 파일: `backend/logs/challenge_debug.log` (한 세션을 통째로 복사해 보라고 남긴다)
- 콘솔: `challenge.debug` 로거. `CHALLENGE `로 시작하므로 grep하기 쉽다

⚠️ 개발용 엔드포인트다. 인증이 없고 앱이 보낸 문자열을 그대로 기록한다.
`DEBUG_LOG_ENABLED=false`로 끄면 404가 된다. 외부에 노출하지 말 것.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from app.config import Settings
from app.deps import get_settings
from app.errors import ApiError
from app.schemas import DebugLogBatch, DebugLogOut

log = logging.getLogger("challenge.debug")

router = APIRouter(prefix="/debug", tags=["debug"])

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_PATH = LOG_DIR / "challenge_debug.log"

# 앱이 보낸 줄 하나의 상한. 로그 파일이 통째로 커지는 것을 막는다.
MAX_LINE_BYTES = 2000


def _require_enabled(settings: Settings) -> None:
    if not settings.debug_log_enabled:
        raise ApiError(
            404, "not_found", "debug_log_disabled",
            "디버그 로그가 꺼져 있습니다 (DEBUG_LOG_ENABLED=false).",
        )


def _sanitize(line: str) -> str:
    """줄바꿈을 지우고 길이를 자른다.

    앱이 보낸 문자열을 그대로 파일에 쓰므로, 줄바꿈이 섞이면 한 줄 형식이 깨져
    grep이 소용없어진다. 제어문자도 뺀다.
    """
    flat = "".join(ch for ch in line if ch.isprintable())
    encoded = flat.encode("utf-8")[:MAX_LINE_BYTES]
    return encoded.decode("utf-8", errors="ignore")


@router.post("/challenge", response_model=DebugLogOut)
def post_challenge_log(
    body: DebugLogBatch,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> DebugLogOut:
    _require_enabled(settings)

    client = request.client.host if request.client else "?"
    stamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S.%f")[:-3]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        for raw in body.lines:
            line = _sanitize(raw)
            if not line:
                continue
            handle.write(f"{stamp} [{body.session_id}] {line}\n")
            log.info("%s %s", body.session_id, line)
            written += 1

    return DebugLogOut(written=written, path=str(LOG_PATH), client=client)


@router.get("/challenge", response_class=PlainTextResponse)
def get_challenge_log(
    lines: int = 0,
    settings: Settings = Depends(get_settings),
) -> str:
    """로그를 텍스트로 돌려준다. 브라우저에서 열어 통째로 복사하라고 둔다.

    `lines`를 주면 마지막 N줄만.
    """
    _require_enabled(settings)
    if not LOG_PATH.exists():
        return "(비어 있음)\n"
    text = LOG_PATH.read_text(encoding="utf-8")
    if lines > 0:
        return "\n".join(text.splitlines()[-lines:]) + "\n"
    return text


@router.delete("/challenge", response_model=DebugLogOut)
def clear_challenge_log(settings: Settings = Depends(get_settings)) -> DebugLogOut:
    """세션 하나만 깨끗하게 보려고 비운다."""
    _require_enabled(settings)
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    return DebugLogOut(written=0, path=str(LOG_PATH), client="")
