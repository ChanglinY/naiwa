"""桌宠的全局配置：动作定义、窗口参数、行为参数。

改素材/加动作基本只改这里。assets/<folder>/ 下放对应动作的序列帧 PNG，
按文件名排序播放；某个动作缺帧时会自动用占位图，程序照样能跑。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    name: str          # 动作标识
    folder: str        # assets/ 下的子目录名
    fps: int = 10      # 播放帧率
    loop: bool = True  # True=循环播放；False=播一遍后回到 idle
    faces_right: bool = True  # 素材默认朝向；False=朝左（如走路原片）
    scale: float = 1.0  # 显示缩放倍数；横向素材(如走路)可调大让角色看着更大
    reverse: bool = False  # True=倒放（用于姿势切换回程）


# ---- 窗口 / 显示 ----
# 所有动作共用一张画布(要同时装下站姿和趴姿)，所以这个值是画布边长，
# 不是角色高度；站姿实际高度约为它的 0.69 倍。
PET_MAX_SIZE = 290          # 显示时的最大边长(像素)，等比缩放
ALWAYS_ON_TOP = True        # 始终置顶
DISPLAY_FPS = 60            # 主循环刷新率
APP_NAME = "奶蛙"
# 相邻两帧按刷新率做淡入淡出插值。素材 24fps 而屏幕 60Hz，整帧播放时
# 每帧要占 2~3 个刷新周期，站起/趴下这类大位移动作会看着一顿一顿。
FRAME_BLEND = True
FRAME_BLEND_MIN_FPS = 30    # 只对低于该帧率的动作插值(高帧率素材本身够密)

# ---- 动作表 ----
# 待机有两种静止姿势：放松(手臂身侧) / 捧腹；其间用 transition 正放/倒放切换。
# idle_special 首尾都是捧腹，只能从捧腹姿势切入。
ACTIONS: dict[str, ActionSpec] = {
    "idle_relax":   ActionSpec("idle_relax",   "idle_relax",      1,  loop=True),
    "idle_belly":   ActionSpec("idle_belly",   "idle_belly",      1,  loop=True),
    "idle_to_belly": ActionSpec("idle_to_belly", "idle_transition", 24, loop=False),
    "idle_to_relax": ActionSpec("idle_to_relax", "idle_transition", 24, loop=False, reverse=True),
    "idle_special": ActionSpec("idle_special", "idle_special",    24, loop=False),
    "laugh":        ActionSpec("laugh",        "laugh",           24, loop=False),
    "destroy":      ActionSpec("destroy",      "destroy_turn",    24, loop=False),
    "destroy_slam": ActionSpec("destroy_slam", "destroy_slam",    24, loop=False),
    "destroy_rise": ActionSpec("destroy_rise", "destroy_rise",    24, loop=False),
    "destroy_return": ActionSpec("destroy_return", "destroy_return", 24, loop=False),
    "destroy_sniff": ActionSpec("destroy_sniff", "destroy_sniff",  24, loop=False),
    # 移动三阶段：站→趴 / 循环爬行 / 趴→站（素材朝右）
    "crawl_down":   ActionSpec("crawl_down",   "crawl_down",      24, loop=False),
    "crawl":        ActionSpec("crawl",        "crawl",           24, loop=True),
    "crawl_up":     ActionSpec("crawl_up",     "crawl_up",        24, loop=False),
    "drag":         ActionSpec("drag",         "drag",            8,  loop=True),
    # 长时间无互动：站→蹲 / 蹲着循环 / 蹲→站（起止捧腹）
    "squat_down":   ActionSpec("squat_down",   "squat_down",      24, loop=False),
    "squat":        ActionSpec("squat",        "squat",           24, loop=True),
    "squat_up":     ActionSpec("squat_up",     "squat_up",        24, loop=False),
}

# 右键菜单里出现的互动项：(显示文字, 动作名)
MENU_ACTIONS: list[tuple[str, str]] = [
    ("难绷", "laugh"),
]

# 循环类互动默认保持多久再回待机（预留；当前菜单项均为播完即停）
ACTION_HOLD_SEC = 8.0

# 姿势切换相关动作（播完后更新当前静止姿势）
POSE_TRANSITIONS = {
    "idle_to_belly": "belly",
    "idle_to_relax": "relax",
}
IDLE_POSE_ACTIONS = {
    "relax": "idle_relax",
    "belly": "idle_belly",
}
# 播完后强制回到某静止姿势（首尾帧已对齐该姿势）
POSE_AFTER_ACTION = {
    "idle_special": "belly",
    "laugh": "belly",
    "destroy": "belly",
    "crawl_up": "belly",
}

# ---- 自动行为 ----
WALK_SPEED = 55             # 爬行移动速度(像素/秒)
WALK_DIAGONAL_CHANCE = 0.6  # 每段爬行走斜线的概率(其余为水平)
WALK_MAX_SLOPE = 0.7        # 斜线的纵向/横向速度比上限
IDLE_MIN_SEC = 3.0          # 每段发呆最短时间
IDLE_MAX_SEC = 8.0          # 每段发呆最长时间
WALK_MIN_SEC = 6.0          # 每段爬行最短时间（约一轮多爬行动画）
WALK_MAX_SEC = 12.0         # 每段爬行最长时间
# 进入待机时随机穿插（互斥，按顺序判定）
IDLE_SPECIAL_CHANCE = 0.14  # 特殊待机动作（仅捧腹姿势）
IDLE_POSE_SWITCH_CHANCE = 0.28  # 在两种静止姿势间切换
AUTO_SQUAT_SEC = 300.0      # 超过这么久没有任何互动，奶蛙蹲下发呆(0=关闭；5分钟)

# ---- 追鼠标 ----
CHASE_CHANCE = 0.4          # 待机结束时，去追鼠标(而非随机散步)的概率
CHASE_SPEED = 85            # 追鼠标爬行速度(像素/秒)
CHASE_STOP_DIST = 40        # 与鼠标水平距离小于该值就停下
CHASE_MAX_SEC = 10.0        # 单次最多追多久，超时放弃

# ---- 桌面摧毁 ----
DESTROY_CHASE_MAX_SEC = 60.0
DESTROY_SEQUENCE = ("destroy", "destroy_slam", "destroy_rise", "destroy_return", "destroy_sniff")
OVERLAY_PROMPT = "你要销毁哪个文件？"
OVERLAY_WRONG = "不是这个"
OVERLAY_GONE = "已经没了"
OVERLAY_WRONG_SEC = 1.2
OVERLAY_GONE_SEC = 3.0
OVERLAY_FADE_MS = 250
SHELL_MENU_LABEL = "召唤奶蛙摧毁"

# ---- 拖拽“拎起来”效果 ----
DRAG_THRESHOLD_PX = 6       # 移动超过该像素才算拖动（单击不切换拎起姿势）
DRAG_MAX_TILT = 22.0        # 拖动时最大倾斜角度(度)
DRAG_TILT_GAIN = 0.035      # 水平像素/秒 -> 角度，右拖时身体向左滞后
DRAG_SWAY_STIFFNESS = 110.0 # 弹簧回正力度
DRAG_SWAY_DAMPING = 12.0    # 停手后轻晃并收稳
DRAG_GRIP = (111 / 290, 18 / 240)  # 素材头顶尖端的归一化位置
