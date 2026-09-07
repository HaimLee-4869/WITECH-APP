"""파일명 파싱 규칙 (SPEC 2장).

    {참가자}_{동작}_{조건}_{번호}.mp4      예: P01_OPEN_PALM_near_01.mp4
    {참가자}_NEG_{종류}_{번호}.mp4         예: P01_NEG_halffist_01.mp4

규칙과 다른 파일은 조용히 건너뛰지 않고 경고 대상(ParseError)으로 돌려준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SHAPE_ACTIONS = ("OPEN_PALM", "FIST", "INDEX", "TWO_FINGERS")
MOVE_ACTIONS = ("MOVE_LEFT", "MOVE_RIGHT", "MOVE_UP", "MOVE_DOWN")
POSITIVE_ACTIONS = SHAPE_ACTIONS + MOVE_ACTIONS
CONDITIONS = ("near", "far", "dark")
# NEG 영상은 무엇에 대한 반례인지가 다르다. 섞어서 통계를 내면 안 된다.
#   손 모양 반례: 손은 가만히 있고 모양만 애매하다
#   이동 반례:   손 모양은 정상(편 손)이고 움직임만 애매하다
#   추적 반례:   손이 화면에서 사라진다
SHAPE_NEG_KINDS = ("halffist", "threefingers", "indexring", "indexpinky")
MOVE_NEG_KINDS = ("shake", "diagonal")
TRACKING_NEG_KINDS = ("exit",)
NEG_KINDS = SHAPE_NEG_KINDS + MOVE_NEG_KINDS + TRACKING_NEG_KINDS

SHAPE_NEG_ACTIONS = tuple(f"NEG_{k}" for k in SHAPE_NEG_KINDS)
MOVE_NEG_ACTIONS = tuple(f"NEG_{k}" for k in MOVE_NEG_KINDS)

_PARTICIPANT_RE = re.compile(r"^P\d{2}$")
_INDEX_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class ClipMeta:
    """영상 1개의 메타데이터."""
    stem: str
    participant: str
    action: str          # POSITIVE_ACTIONS 중 하나 또는 "NEG_<kind>"
    condition: str | None  # NEG 영상은 None
    index: str

    @property
    def is_negative(self) -> bool:
        return self.action.startswith("NEG_")

    @property
    def is_shape(self) -> bool:
        return self.action in SHAPE_ACTIONS

    @property
    def is_move(self) -> bool:
        return self.action in MOVE_ACTIONS

    @property
    def neg_kind(self) -> str | None:
        return self.action[len("NEG_"):] if self.is_negative else None


class ParseError(ValueError):
    """파일명이 규칙에 맞지 않을 때."""


def parse_stem(stem: str) -> ClipMeta:
    """확장자를 제외한 파일명을 ClipMeta로 파싱한다. 실패하면 ParseError."""
    parts = stem.split("_")
    if len(parts) < 3:
        raise ParseError(f"토큰이 너무 적음: {stem!r}")

    participant, rest = parts[0], parts[1:]
    if not _PARTICIPANT_RE.match(participant):
        raise ParseError(f"참가자 ID 형식이 아님(P##): {participant!r} in {stem!r}")

    if not _INDEX_RE.match(rest[-1]):
        raise ParseError(f"끝이 번호가 아님: {rest[-1]!r} in {stem!r}")
    index, body = rest[-1], rest[:-1]

    if body and body[0] == "NEG":
        if len(body) != 2:
            raise ParseError(f"NEG 파일명은 NEG_<종류>_<번호> 형태여야 함: {stem!r}")
        kind = body[1]
        if kind not in NEG_KINDS:
            raise ParseError(f"알 수 없는 NEG 종류 {kind!r}: {stem!r}")
        return ClipMeta(stem, participant, f"NEG_{kind}", None, index)

    if len(body) < 2:
        raise ParseError(f"동작/조건 토큰이 부족함: {stem!r}")
    condition, action = body[-1], "_".join(body[:-1])
    if condition not in CONDITIONS:
        raise ParseError(f"알 수 없는 조건 {condition!r}: {stem!r}")
    if action not in POSITIVE_ACTIONS:
        raise ParseError(f"알 수 없는 동작 {action!r}: {stem!r}")
    return ClipMeta(stem, participant, action, condition, index)
