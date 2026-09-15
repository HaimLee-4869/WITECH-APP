"""API 에러 형식.

모든 4xx는 `{"detail": {"code", "reason", "message"}}` 형태로 내려간다.
앱은 `reason`으로 분기하고, `message`를 그대로 보여줄 수 있다.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        reason: str,
        message: str,
        take_no: int | None = None,
    ):
        super().__init__(f"{code}/{reason}: {message}")
        self.status_code = status_code
        self.code = code
        self.reason = reason
        self.message = message
        self.take_no = take_no

    def detail(self) -> dict:
        d = {"code": self.code, "reason": self.reason, "message": self.message}
        if self.take_no is not None:
            d["takeNo"] = self.take_no
        return d


def not_found(reason: str, message: str) -> ApiError:
    return ApiError(404, "not_found", reason, message)


def invalid_request(reason: str, message: str) -> ApiError:
    return ApiError(422, "invalid_request", reason, message)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail()})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "invalid_request",
                    "reason": "schema_validation",
                    "message": "요청 형식이 올바르지 않습니다.",
                    "errors": errors,
                }
            },
        )
