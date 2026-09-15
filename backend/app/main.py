"""FastAPI 앱.

AI 모델은 별도 서버가 아니라 같은 프로세스에서 import하는 라이브러리다 (명세 원칙 A).
load_model()은 startup에서 한 번만 호출한다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai import encoder
from app.config import Settings, get_settings
from app.database import Database
from app.errors import install_error_handlers
from app.migrations import upgrade_to_head
from app.routers import config, enroll, logs, users, verify
from app.seed import ensure_seed_data

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            upgrade_to_head(settings.database_url)
        app.state.db = Database(settings.database_url)
        encoder.load_model(device=settings.ai_device)  # 반드시 1회만
        with app.state.db.session() as session:
            ensure_seed_data(session)
        log.info(
            "ready: encoder=%s gesture=%s use_gesture_classifier=%s",
            encoder.MODEL_VERSION, encoder.GESTURE_MODEL_VERSION, settings.use_gesture_classifier,
        )
        yield
        app.state.db.dispose()

    app = FastAPI(title="Sign-ID Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(enroll.router)
    app.include_router(verify.router)
    app.include_router(users.router)
    app.include_router(logs.router)
    app.include_router(config.router)
    return app


app = create_app()
