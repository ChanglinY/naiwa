from __future__ import annotations

from dataclasses import dataclass

from src.behavior import Behavior, State
from src import config


@dataclass
class _Frames:
    frames: list[object]


class _Animation:
    def __init__(self, action: str) -> None:
        self.action = action
        self.frame_set = _Frames([object(), object()])
        self.fps = 10
        self.finished = False
        self.advanced = 0.0

    def advance(self, dt: float) -> None:
        self.advanced += dt


class _Library:
    def make(self, action: str) -> _Animation:
        return _Animation(action)


def test_frozen_advances_animation_without_behavior_timers() -> None:
    behavior = Behavior(_Library())
    timer = behavior._timer
    behavior.set_frozen(True)

    assert behavior.update(1.0, 12.0, 34.0) == (12.0, 34.0)
    assert behavior.anim.advanced == 1.0
    assert behavior._timer == timer
    assert behavior._since_interaction == 0.0


def test_destroy_chase_uses_fixed_target_and_emits_once() -> None:
    behavior = Behavior(_Library())
    behavior.set_chase_target(100.0, 100.0)
    behavior.start_destroy_chase()

    assert behavior.state == State.CRAWL_DOWN
    assert behavior.wants_chase_target() is False

    behavior.anim.finished = True
    behavior.update(0.0, 0.0, 0.0)
    assert behavior.state == State.CHASE

    behavior.update(0.0, 100.0, 100.0)
    assert behavior.state == State.CRAWL_UP
    behavior.anim.finished = True
    behavior.update(0.0, 100.0, 100.0)

    assert behavior.destroy_arrived() is True
    assert behavior.destroy_arrived() is False


def test_destroy_animation_finished_emits_once() -> None:
    behavior = Behavior(_Library())
    behavior.begin_destroy_action()
    assert behavior.anim.action == "destroy"

    for action in config.DESTROY_SEQUENCE:
        assert behavior.anim.action == action
        assert behavior.destroy_impact() is False
        behavior.anim.finished = True
        behavior.update(0.0, 0.0, 0.0)
        assert behavior.destroy_impact() is (action == "destroy_slam")
        assert behavior.destroy_impact() is False
        assert behavior.destroy_action_finished() is (action == "destroy_sniff")
        assert behavior.destroy_action_finished() is False
    assert behavior.state is State.IDLE


def test_drag_before_impact_never_emits_recycle_event() -> None:
    behavior = Behavior(_Library())
    behavior.begin_destroy_action()
    behavior.anim.finished = True
    behavior.update(0, 0, 0)
    assert behavior.anim.action == "destroy_slam"
    behavior.start_drag()
    assert not behavior.destroy_impact()
    assert not behavior.destroy_action_finished()


def test_destroy_reaches_exact_contact_point_outside_normal_window_bounds() -> None:
    behavior = Behavior(_Library())
    behavior.set_bounds(0, 500, 0, 500)
    behavior.set_chase_target(-50, -100)
    behavior.start_destroy_chase(facing_right=True)
    behavior.anim.finished = True
    behavior.update(0, 0, 0)
    x, y = 0.0, 0.0
    for _ in range(200):
        x, y = behavior.update(1 / 60, x, y)
        if behavior.state is State.CRAWL_UP:
            break
    assert (x, y) == (-50, -100)
    assert behavior.facing_right is True
