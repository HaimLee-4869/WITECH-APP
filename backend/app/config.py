"""설정. 환경변수(.env)에서 읽는다.

운영 중 바뀌어야 하는 값(threshold, 등록 횟수 등)은 여기가 아니라 DB에 둔다. (명세 원칙 D)
여기에는 프로세스 시작 시 정해지는 값만 둔다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./signid.db"
    ai_device: str = "cpu"
    log_level: str = "INFO"
    cors_origins: str = "*"

    # startup에서 alembic upgrade head를 실행할지.
    auto_migrate: bool = True

    # /stats/monthly 월 경계 계산용 (KST).
    stats_utc_offset_hours: int = 9

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
