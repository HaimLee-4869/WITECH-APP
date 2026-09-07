"""무작위 Challenge 생성 (SPEC 4.8).

- random이 아니라 secrets를 쓴다. random은 시드 예측이 가능해 재현 공격에 취약하다.
- 손 모양 2개는 서로 달라야 한다. 같은 모양이 연속되면 사용자가 손을 그대로 두어도
  두 단계를 통과해버린다.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .naming import MOVE_ACTIONS, SHAPE_ACTIONS

NUM_SHAPES = 2   # 손 모양 단계 수 (SPEC 4.8). 임계값이 아니라 프로토콜 정의다.
NUM_MOVES = 1    # 이동 단계 수


@dataclass(frozen=True)
class Challenge:
    challenge_id: str
    actions: list[str]
    created_at: str
    shape_pool: tuple[str, ...] = field(default=SHAPE_ACTIONS)
    move_pool: tuple[str, ...] = field(default=MOVE_ACTIONS)

    def __len__(self) -> int:
        return len(self.actions)


def _sample_distinct(pool: tuple[str, ...], k: int) -> list[str]:
    """중복 없이 k개를 뽑는다 (secrets 기반)."""
    if k > len(pool):
        raise ValueError(f"풀({len(pool)})보다 많은 {k}개를 뽑을 수 없다")
    remaining = list(pool)
    picked: list[str] = []
    for _ in range(k):
        picked.append(remaining.pop(secrets.randbelow(len(remaining))))
    return picked


def _shuffle(items: list[str]) -> list[str]:
    """secrets 기반 Fisher-Yates."""
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def generate_challenge(shape_pool: tuple[str, ...] = SHAPE_ACTIONS,
                       move_pool: tuple[str, ...] = MOVE_ACTIONS,
                       num_shapes: int = NUM_SHAPES,
                       num_moves: int = NUM_MOVES) -> Challenge:
    """손 모양 2개(서로 다름) + 이동 1개를 뽑아 순서를 섞는다."""
    shapes = _sample_distinct(tuple(shape_pool), num_shapes)
    moves = _sample_distinct(tuple(move_pool), num_moves)
    return Challenge(
        challenge_id=str(uuid.uuid4()),
        actions=_shuffle(shapes + moves),
        created_at=datetime.now(timezone.utc).isoformat(),
        shape_pool=tuple(shape_pool),
        move_pool=tuple(move_pool),
    )


def is_shape_action(action: str) -> bool:
    return action in SHAPE_ACTIONS


def is_move_action(action: str) -> bool:
    return action in MOVE_ACTIONS
