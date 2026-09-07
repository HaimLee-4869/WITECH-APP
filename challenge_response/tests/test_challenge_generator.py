"""challenge_generator.py 검증 (SPEC 4.8)."""
from __future__ import annotations

import uuid

import pytest

from core import challenge_generator as cg
from core.naming import MOVE_ACTIONS, SHAPE_ACTIONS

TRIALS = 400


def test_challenge_has_three_actions():
    assert len(cg.generate_challenge().actions) == cg.NUM_SHAPES + cg.NUM_MOVES


def test_two_shapes_are_always_distinct():
    for _ in range(TRIALS):
        shapes = [a for a in cg.generate_challenge().actions if cg.is_shape_action(a)]
        assert len(shapes) == cg.NUM_SHAPES
        assert len(set(shapes)) == cg.NUM_SHAPES


def test_exactly_one_move_action():
    for _ in range(TRIALS):
        moves = [a for a in cg.generate_challenge().actions if cg.is_move_action(a)]
        assert len(moves) == cg.NUM_MOVES


def test_actions_come_from_declared_pools():
    for _ in range(TRIALS):
        for action in cg.generate_challenge().actions:
            assert action in SHAPE_ACTIONS + MOVE_ACTIONS


def test_challenge_id_is_uuid4():
    challenge = cg.generate_challenge()
    assert uuid.UUID(challenge.challenge_id).version == 4


def test_challenge_ids_are_unique():
    ids = {cg.generate_challenge().challenge_id for _ in range(TRIALS)}
    assert len(ids) == TRIALS


def test_created_at_is_recorded():
    assert cg.generate_challenge().created_at


def test_move_appears_in_every_position_over_many_draws():
    """이동 단계가 항상 마지막에 오면 순서 섞기가 동작하지 않는 것이다."""
    positions = set()
    for _ in range(TRIALS):
        actions = cg.generate_challenge().actions
        positions.add(next(i for i, a in enumerate(actions) if cg.is_move_action(a)))
    assert positions == {0, 1, 2}


def test_all_shape_pairs_are_reachable():
    seen = set()
    for _ in range(TRIALS * 4):
        shapes = tuple(sorted(a for a in cg.generate_challenge().actions
                              if cg.is_shape_action(a)))
        seen.add(shapes)
    expected = {tuple(sorted((a, b)))
                for a in SHAPE_ACTIONS for b in SHAPE_ACTIONS if a != b}
    assert seen == expected


def test_sample_distinct_rejects_oversized_request():
    with pytest.raises(ValueError):
        cg._sample_distinct(("A", "B"), 3)
