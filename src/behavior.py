"""行为状态机：控制桌宠自动发呆/散步，以及被拖拽和触发互动时的状态切换。

只负责“决策 + 计算下一帧要走到哪、播什么动画”，实际画面移动交给窗口层。

待机姿势：
  - relax：手臂在身侧（静止帧）
  - belly：捧腹（静止帧）
  - idle_transition 正放：relax → belly；倒放：belly → relax
  - idle_special 首尾都是捧腹，只能从 belly 切入，播完仍回 belly

移动（散步/追鼠标）：
  - crawl_down：站→趴（不位移）
  - crawl：趴着循环爬行并位移，方向可斜向，撞到屏幕边缘反弹
  - crawl_up：趴→站（不位移），结束后回捧腹待机

长时间无互动：
  - squat_down：站→蹲
  - squat：蹲着循环，直到被互动打断
  - squat_up：蹲→站，结束后回捧腹待机
"""

from __future__ import annotations

import math
import random
from enum import Enum, auto

from . import config
from .sprite import Animation, SpriteLibrary


class State(Enum):
    IDLE = auto()
    CRAWL_DOWN = auto()  # 站→趴，准备移动
    WALK = auto()
    CHASE = auto()       # 朝鼠标爬过去
    CRAWL_UP = auto()    # 趴→站，结束移动
    SQUAT_DOWN = auto()  # 站→蹲
    SQUAT = auto()       # 蹲着发呆
    SQUAT_UP = auto()    # 蹲→站
    DRAG = auto()
    ACTION = auto()      # 菜单互动 / 姿势切换 / 特殊待机等


class Behavior:
    def __init__(self, library: SpriteLibrary):
        self.lib = library
        self.state = State.IDLE
        self.facing_right = True          # 朝向，用于水平翻转
        self._timer = 0.0                 # 当前状态剩余时间
        self._walk_vec = (1.0, 0.0)       # 爬行方向(单位向量，可斜向)
        self._bounds = (0, 1920, 0, 1080)  # 可散步范围 left,right,top,bottom
        self._chase_target = (0.0, 0.0)   # 追鼠标目标(窗口左上角期望坐标)
        self._since_interaction = 0.0     # 距上次互动的时间，用于自动蹲下
        self._idle_pose = "belly"         # 当前静止姿势：relax | belly
        self._queued_action: str | None = None  # 姿势切完 / 站起后接着播的菜单动作
        self._queued_move: str | None = None    # 姿势切完后开始的移动：walk|chase|destroy
        self._queued_squat = False              # 姿势切完后开始蹲下
        self._move_kind: str | None = None      # 当前移动类型 walk|chase|destroy
        self._frozen = False
        self._destroy_arrived_event = False
        self._watching_destroy = False
        self._destroy_action_finished_event = False
        self._destroy_impact_event = False
        self._destroy_facing_right: bool | None = None
        self.anim: Animation = self.lib.make(config.IDLE_POSE_ACTIONS[self._idle_pose])
        self._enter_idle(allow_extras=False)

    # ---- 外部注入屏幕边界 ----
    def set_bounds(self, left: int, right: int, top: int, bottom: int) -> None:
        self._bounds = (left, max(left + 1, right), top, max(top + 1, bottom))

    def wants_chase_target(self) -> bool:
        """趴下/爬行/站起过程中，追鼠标需要持续刷新目标与朝向。"""
        return self._move_kind == "chase" and self.state in (
            State.CRAWL_DOWN, State.CHASE, State.CRAWL_UP,
        )

    def set_frozen(self, frozen: bool) -> None:
        """冻结行为决策和计时；当前动画仍由 update 推进。"""
        self._frozen = frozen

    def start_destroy_chase(self, facing_right: bool | None = None) -> None:
        """追逐已由窗口层固定好的桌面图标目标。"""
        self._since_interaction = 0.0
        self._queued_action = None
        self._queued_move = None
        self._queued_squat = False
        self._destroy_arrived_event = False
        self._destroy_action_finished_event = False
        self._watching_destroy = False
        self._destroy_impact_event = False
        self._destroy_facing_right = facing_right
        if facing_right is not None:
            self.facing_right = facing_right

        if self.state in (State.SQUAT_DOWN, State.SQUAT, State.SQUAT_UP):
            self._move_kind = "destroy"
            self._queued_move = "destroy"
            if self.state != State.SQUAT_UP:
                self._enter_squat_up()
            return
        self._begin_move("destroy")

    def destroy_arrived(self) -> bool:
        """摧毁追逐站起后返回 True 一次。"""
        arrived = self._destroy_arrived_event
        self._destroy_arrived_event = False
        return arrived

    def begin_destroy_action(self) -> None:
        """开始摧毁动画，并监听其一次性完成事件。"""
        self._watching_destroy = True
        self._destroy_action_finished_event = False
        self._destroy_impact_event = False
        self.start_action("destroy")

    def destroy_impact(self) -> bool:
        """销毁2完整播放后产生一次回收事件，后续三段继续播放。"""
        impact = self._destroy_impact_event
        self._destroy_impact_event = False
        return impact

    def cancel_destroy_action(self) -> None:
        self._watching_destroy = False
        self._destroy_impact_event = False
        self._destroy_action_finished_event = False
        self._destroy_arrived_event = False
        self._destroy_facing_right = None
        if self.state is not State.DRAG:
            self._queued_move = None
            self._queued_action = None
            self._idle_pose = "belly"
            self._enter_idle(allow_extras=False)

    def destroy_action_finished(self) -> bool:
        """摧毁动画播完后返回 True 一次。"""
        finished = self._destroy_action_finished_event
        self._destroy_action_finished_event = False
        return finished

    # ---- 状态切换 ----
    def _switch(self, action: str, state: State) -> None:
        self.state = state
        self.anim = self.lib.make(action)

    def _hold_idle_pose(self) -> None:
        """保持当前静止姿势，进入 IDLE 计时。"""
        action = config.IDLE_POSE_ACTIONS[self._idle_pose]
        self._switch(action, State.IDLE)
        self._timer = random.uniform(config.IDLE_MIN_SEC, config.IDLE_MAX_SEC)

    def _enter_idle(self, allow_extras: bool = True) -> None:
        self._move_kind = None
        # 待机时偶尔：特殊动作(仅捧腹) / 姿势切换
        if allow_extras:
            r = random.random()
            acc = 0.0

            if self._idle_pose == "belly":
                acc += config.IDLE_SPECIAL_CHANCE
                if r < acc and "idle_special" in config.ACTIONS:
                    # 特殊动作首尾都是捧腹，切入/切出都保持 belly
                    self._switch("idle_special", State.ACTION)
                    self._timer = float("inf")
                    return

            acc += config.IDLE_POSE_SWITCH_CHANCE
            if r < acc:
                # 正放：放松→捧腹；倒放：捧腹→放松
                nxt = "idle_to_belly" if self._idle_pose == "relax" else "idle_to_relax"
                self._switch(nxt, State.ACTION)
                self._timer = float("inf")
                return

        self._hold_idle_pose()

    def _on_action_finished(self) -> None:
        """非循环动作播完后的衔接：更新姿势，再回静止待机（或播排队动作/开始移动/蹲下）。"""
        action = self.anim.action
        if self._watching_destroy and action in config.DESTROY_SEQUENCE:
            if action == "destroy_slam":
                self._destroy_impact_event = True
            index = config.DESTROY_SEQUENCE.index(action)
            if index + 1 < len(config.DESTROY_SEQUENCE):
                self._begin_menu_action(config.DESTROY_SEQUENCE[index + 1])
                return
            self._watching_destroy = False
            self._destroy_action_finished_event = True
            self._idle_pose = "belly"
        if action in config.POSE_TRANSITIONS:
            self._idle_pose = config.POSE_TRANSITIONS[action]
            if self._queued_action:
                nxt = self._queued_action
                self._queued_action = None
                self._begin_menu_action(nxt)
                return
            if self._queued_move:
                kind = self._queued_move
                self._queued_move = None
                self._enter_crawl_down(kind)
                return
            if self._queued_squat:
                self._queued_squat = False
                self._enter_squat_down()
                return
        elif action in config.POSE_AFTER_ACTION:
            self._idle_pose = config.POSE_AFTER_ACTION[action]
        self._enter_idle(allow_extras=False)

    def _decide_move(self) -> None:
        # 待机结束后：一定概率去追鼠标，否则随机爬行散步
        kind = "chase" if random.random() < config.CHASE_CHANCE else "walk"
        self._begin_move(kind)

    def _begin_move(self, kind: str) -> None:
        """开始一次移动：必要时先切到捧腹，再播站→趴。"""
        self._move_kind = kind
        self._queued_move = None
        if kind == "walk":
            self._walk_vec = self._random_walk_vec()
            self.facing_right = self._walk_vec[0] > 0

        # 爬行起止都是捧腹；当前放松则先切姿势
        if self._idle_pose == "relax":
            self._queued_move = kind
            self._switch("idle_to_belly", State.ACTION)
            self._timer = float("inf")
            return
        self._enter_crawl_down(kind)

    def _random_walk_vec(self) -> tuple[float, float]:
        """随机爬行方向：左右必选其一，一定概率带上下分量走斜线。"""
        dx = random.choice((-1.0, 1.0))
        dy = 0.0
        if random.random() < config.WALK_DIAGONAL_CHANCE:
            slope = config.WALK_MAX_SLOPE
            dy = random.uniform(-slope, slope)
        length = math.hypot(dx, dy)
        return dx / length, dy / length

    def _enter_crawl_down(self, kind: str) -> None:
        self._move_kind = kind
        self._idle_pose = "belly"
        self._switch("crawl_down", State.CRAWL_DOWN)

    def _enter_walk_crawl(self) -> None:
        self._switch("crawl", State.WALK)
        # 按整数个爬行循环计时，收尾时正好停在循环末帧，接“趴→站”不跳姿势
        cycle = len(self.anim.frame_set.frames) / self.anim.fps
        lo = max(1, round(config.WALK_MIN_SEC / cycle))
        hi = max(lo, int(config.WALK_MAX_SEC / cycle))
        self._timer = random.randint(lo, hi) * cycle

    def _enter_chase_crawl(self) -> None:
        self._switch("crawl", State.CHASE)
        self._timer = (
            config.DESTROY_CHASE_MAX_SEC
            if self._move_kind == "destroy"
            else config.CHASE_MAX_SEC
        )

    def _enter_crawl_up(self) -> None:
        self._switch("crawl_up", State.CRAWL_UP)

    # ---- 长时间无互动：蹲下 ----
    def _begin_squat(self) -> None:
        """进入蹲下流程；起止都是捧腹，放松时先切姿势。"""
        self._move_kind = None
        self._queued_move = None
        if self._idle_pose == "relax":
            self._queued_squat = True
            self._switch("idle_to_belly", State.ACTION)
            self._timer = float("inf")
            return
        self._enter_squat_down()

    def _enter_squat_down(self) -> None:
        self._idle_pose = "belly"
        self._switch("squat_down", State.SQUAT_DOWN)

    def _enter_squat_loop(self) -> None:
        self._switch("squat", State.SQUAT)

    def _enter_squat_up(self) -> None:
        if self.state == State.SQUAT_UP:
            return
        self._switch("squat_up", State.SQUAT_UP)

    def set_chase_target(self, target_x: float, target_y: float) -> None:
        """窗口层每帧把鼠标位置换算成期望的窗口左上角坐标传进来。"""
        self._chase_target = (target_x, target_y)

    def notify_interaction(self) -> None:
        """任何鼠标互动都调用它，重置自动蹲下计时；蹲着时会站起来。"""
        self._since_interaction = 0.0
        if self.state in (State.SQUAT_DOWN, State.SQUAT):
            self._enter_squat_up()

    def start_drag(self) -> None:
        # 拖拽直接切拎起姿势，不播蹲→站（手感更跟手）
        self._since_interaction = 0.0
        self._queued_action = None
        self._queued_move = None
        self._queued_squat = False
        self._move_kind = None
        self._watching_destroy = False
        self._destroy_arrived_event = False
        self._destroy_action_finished_event = False
        self._destroy_impact_event = False
        self._switch("drag", State.DRAG)

    def start_action(self, action: str) -> None:
        """右键菜单触发互动。"""
        self._since_interaction = 0.0
        self._queued_move = None
        self._queued_squat = False
        self._move_kind = None
        if action not in config.ACTIONS:
            return

        # 蹲着时：先站起来，再播菜单动作
        if self.state in (State.SQUAT_DOWN, State.SQUAT, State.SQUAT_UP):
            self._queued_action = action
            if self.state != State.SQUAT_UP:
                self._enter_squat_up()
            return

        self._queued_action = None
        # 难绷首尾是捧腹：当前若是放松，先切到捧腹再播，避免跳帧
        if action == "laugh" and self._idle_pose == "relax":
            self._queued_action = "laugh"
            self._switch("idle_to_belly", State.ACTION)
            self._timer = float("inf")
            return
        self._begin_menu_action(action)

    def _begin_menu_action(self, action: str) -> None:
        self._switch(action, State.ACTION)
        spec = config.ACTIONS[action]
        if not spec.loop:
            # 一次性动画播完靠 finished，不被 hold 截断
            self._timer = float("inf")
        else:
            self._timer = config.ACTION_HOLD_SEC

    def end_drag(self) -> None:
        self._since_interaction = 0.0
        self._queued_action = None
        self._queued_move = None
        self._queued_squat = False
        self._move_kind = None
        self._enter_idle(allow_extras=False)

    # ---- 主循环推进 ----
    def update(self, dt: float, x: float, y: float) -> tuple[float, float]:
        """推进动画与行为，返回新的坐标(仅爬行位移时改变)。"""
        self.anim.advance(dt)
        if self._frozen:
            return x, y

        # 长时间无互动 -> 蹲下发呆（只从站立待机触发）
        self._since_interaction += dt
        if (config.AUTO_SQUAT_SEC > 0
                and self.state == State.IDLE
                and self._since_interaction >= config.AUTO_SQUAT_SEC):
            self._begin_squat()
            return x, y

        if self.state == State.CRAWL_DOWN:
            if self._move_kind == "chase" or (
                self._move_kind == "destroy" and self._destroy_facing_right is None
            ):
                self.facing_right = self._chase_target[0] > x
            self._update_crawl_down()
        elif self.state == State.WALK:
            x, y = self._update_walk(dt, x, y)
        elif self.state == State.CHASE:
            x, y = self._update_chase(dt, x, y)
        elif self.state == State.CRAWL_UP:
            self._update_crawl_up()
        elif self.state == State.SQUAT_DOWN:
            self._update_squat_down()
        elif self.state == State.SQUAT_UP:
            self._update_squat_up()
        elif self.state == State.SQUAT:
            pass  # 蹲着循环，等互动唤醒
        elif self.state in (State.IDLE, State.ACTION):
            self._update_timed(dt)
        # DRAG 由窗口层驱动位置，这里不动坐标

        return x, y

    def _update_crawl_down(self) -> None:
        if self.anim.finished:
            if self._move_kind in ("chase", "destroy"):
                self._enter_chase_crawl()
            else:
                self._enter_walk_crawl()

    def _update_crawl_up(self) -> None:
        if self.anim.finished:
            move_kind = self._move_kind
            self._idle_pose = "belly"
            self._move_kind = None
            if move_kind == "destroy":
                self._destroy_arrived_event = True
            self._enter_idle(allow_extras=False)

    def _update_squat_down(self) -> None:
        if self.anim.finished:
            self._enter_squat_loop()

    def _update_squat_up(self) -> None:
        if not self.anim.finished:
            return
        self._idle_pose = "belly"
        if self._queued_action:
            nxt = self._queued_action
            self._queued_action = None
            self._begin_menu_action(nxt)
            return
        if self._queued_move:
            kind = self._queued_move
            self._queued_move = None
            self._enter_crawl_down(kind)
            return
        self._enter_idle(allow_extras=False)

    def _update_timed(self, dt: float) -> None:
        # 非循环互动 / 姿势切换 / 特殊待机播完 -> 按衔接逻辑回 idle
        if self.state == State.ACTION and self.anim.finished:
            self._on_action_finished()
            return
        # 循环互动：靠计时结束
        if self.state == State.ACTION:
            if self._timer != float("inf"):
                self._timer -= dt
                if self._timer <= 0:
                    self._enter_idle(allow_extras=False)
            return
        self._timer -= dt
        if self._timer <= 0:
            self._decide_move()

    def _update_walk(self, dt: float, x: float, y: float) -> tuple[float, float]:
        left, right, top, bottom = self._bounds
        vx, vy = self._walk_vec
        x += vx * config.WALK_SPEED * dt
        y += vy * config.WALK_SPEED * dt
        # 撞边界就反弹继续爬（仍在同一段移动时间内）
        if x <= left:
            x = left
            vx = abs(vx)
            self.facing_right = True
        elif x >= right:
            x = right
            vx = -abs(vx)
            self.facing_right = False
        if y <= top:
            y = top
            vy = abs(vy)
        elif y >= bottom:
            y = bottom
            vy = -abs(vy)
        self._walk_vec = (vx, vy)

        self._timer -= dt
        if self._timer <= 0:
            self._enter_crawl_up()
        return x, y

    def _update_chase(self, dt: float, x: float, y: float) -> tuple[float, float]:
        left, right, top, bottom = self._bounds
        destroying = self._move_kind == "destroy"
        if destroying:
            # 图标可在屏幕边缘，允许透明窗口部分越界以让坐压点真正到达图标。
            tx, ty = self._chase_target
        else:
            tx = max(left, min(right, self._chase_target[0]))
            ty = max(top, min(bottom, self._chase_target[1]))
        dx, dy = tx - x, ty - y
        dist = math.hypot(dx, dy)
        # 到得足够近就站起、回待机
        if dist <= (1.0 if destroying else config.CHASE_STOP_DIST):
            self._enter_crawl_up()
            return (tx, ty) if destroying else (x, y)

        if abs(dx) > 1.0 and not (destroying and self._destroy_facing_right is not None):
            self.facing_right = dx > 0
        step = config.CHASE_SPEED * dt
        if step >= dist:
            x, y = tx, ty
        else:
            x += dx / dist * step
            y += dy / dist * step

        self._timer -= dt
        if self._timer <= 0:   # 追太久还没到就站起放弃
            self._enter_crawl_up()
        return x, y

    def on_action_started_timer(self, seconds: float) -> None:
        self._timer = seconds
