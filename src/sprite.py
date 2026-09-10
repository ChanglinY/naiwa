"""序列帧加载与播放。

FrameSet: 从 assets/<folder>/ 加载排序好的帧；缺失时生成占位帧。
Animation: 按 fps 推进当前帧，支持循环 / 播放一次。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap

from . import config

_IMAGE_EXTS = {".png", ".webp", ".gif", ".bmp", ".jpg", ".jpeg"}
_MOTION_FILE = "motion.json"

# 每个动作占位图的主题色，方便没素材时区分状态
_PLACEHOLDER_COLORS: dict[str, str] = {
    "idle_relax":    "#6C8EBF",
    "idle_belly":    "#5B8DB8",
    "idle_to_belly": "#7E57C2",
    "idle_to_relax": "#9575CD",
    "idle_special":  "#5C6BC0",
    "laugh":         "#FF7043",
    "crawl_down":    "#66BB6A",
    "crawl":         "#43A047",
    "crawl_up":      "#2E7D32",
    "drag":          "#B85450",
    "squat_down":    "#8D6E63",
    "squat":         "#A1887F",
    "squat_up":      "#6D4C41",
}
_PLACEHOLDER_EMOJI: dict[str, str] = {
    "idle_relax":    "🐸",
    "idle_belly":    "🐸",
    "idle_to_belly": "🔄",
    "idle_to_relax": "🔄",
    "idle_special":  "✨",
    "laugh":         "😂",
    "crawl_down":    "⬇️",
    "crawl":         "🐸",
    "crawl_up":      "⬆️",
    "drag":          "🫨",
    "squat_down":    "🙇",
    "squat":         "🧘",
    "squat_up":      "⬆️",
}


def _assets_root() -> Path:
    """定位 assets 目录。

    打包成 exe 后：优先用 exe 同目录的 assets/（方便随时替换素材，不必重打包），
    没有则用打包进 exe 的内置 assets/。开发时用项目根下的 assets/。
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        external = exe_dir / "assets"
        if external.is_dir():
            return external
        base = Path(getattr(sys, "_MEIPASS", exe_dir))
        return base / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def _make_placeholder(action: str, frame_idx: int, total: int, size: int) -> QPixmap:
    """生成静止占位图。真实动画交给素材序列帧，占位图不再上下弹。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    d = int(size * 0.7)
    x = (size - d) // 2
    y = (size - d) // 2

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_PLACEHOLDER_COLORS.get(action, "#888888")))
    p.drawEllipse(x, y, d, d)

    p.setPen(QColor("#FFFFFF"))
    f = QFont()
    f.setPointSize(int(size * 0.30))
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, _PLACEHOLDER_EMOJI.get(action, "🐸"))
    p.end()
    return pm


def _scaled(pm: QPixmap, max_size: int) -> QPixmap:
    if pm.width() <= max_size and pm.height() <= max_size:
        return pm
    return pm.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _load_motion() -> dict[str, list[list[float]]]:
    """读取 assets/motion.json（tools/build_motion.py 生成）。缺失就不插值。"""
    path = _assets_root() / _MOTION_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_MOTION_CACHE: dict[str, list[list[float]]] | None = None


def _centroids(folder: str, count: int, scale: float) -> list[tuple[float, float]]:
    global _MOTION_CACHE
    if _MOTION_CACHE is None:
        _MOTION_CACHE = _load_motion()
    data = _MOTION_CACHE.get(folder)
    if not data or len(data) != count:
        return []
    return [(c[0] * scale, c[1] * scale) for c in data]


class FrameSet:
    """一个动作的所有帧。"""

    def __init__(self, frames: list[QPixmap], is_placeholder: bool,
                 centroids: list[tuple[float, float]] | None = None):
        self.frames = frames
        self.is_placeholder = is_placeholder
        # 各帧主体质心，用于帧间插值时先对齐再混合；空表示不做位移补偿
        self.centroids = centroids or []

    @classmethod
    def load(cls, action: str) -> "FrameSet":
        spec = config.ACTIONS[action]
        folder = _assets_root() / spec.folder
        max_size = max(1, int(config.PET_MAX_SIZE * spec.scale))
        files: list[Path] = []
        if folder.is_dir():
            files = sorted(
                p for p in folder.iterdir()
                if p.suffix.lower() in _IMAGE_EXTS
            )

        frames: list[QPixmap] = []
        scale = 1.0
        for f in files:
            pm = QPixmap(str(f))
            if not pm.isNull():
                fitted = _scaled(pm, max_size)
                if pm.width():
                    scale = fitted.width() / pm.width()
                frames.append(fitted)

        if frames:
            return cls(frames, is_placeholder=False,
                       centroids=_centroids(spec.folder, len(frames), scale))

        # 无素材 -> 占位帧
        total = 12
        ph = [_make_placeholder(action, i, total, config.PET_MAX_SIZE)
              for i in range(total)]
        return cls(ph, is_placeholder=True)


class Animation:
    """按 fps 推进 FrameSet 的当前帧；支持倒放。"""

    def __init__(
        self,
        action: str,
        frame_set: FrameSet,
        fps: int,
        loop: bool,
        reverse: bool = False,
    ):
        self.action = action
        self.frame_set = frame_set
        self.fps = max(fps, 1)
        self.loop = loop
        self.reverse = reverse
        self._elapsed = 0.0
        n = len(frame_set.frames)
        self._index = (n - 1) if reverse and n else 0
        self.finished = False  # 非循环动画播完后置 True

    def reset(self) -> None:
        self._elapsed = 0.0
        n = len(self.frame_set.frames)
        self._index = (n - 1) if self.reverse and n else 0
        self.finished = False

    @property
    def phase(self) -> float:
        """当前帧已播过的比例(0~1)，渲染时用来在相邻两帧之间插值。"""
        if self.finished:
            return 0.0
        return min(1.0, max(0.0, self._elapsed * self.fps))

    def _peek_index(self) -> int:
        """下一帧的下标；播完/单帧时仍返回当前帧。"""
        n = len(self.frame_set.frames)
        if n <= 1 or self.finished:
            return self._index
        if self.reverse:
            nxt = self._index - 1
            if nxt < 0:
                return n - 1 if self.loop else self._index
            return nxt
        nxt = self._index + 1
        if nxt >= n:
            return 0 if self.loop else self._index
        return nxt

    @property
    def upcoming(self) -> QPixmap:
        return self.frame_set.frames[self._peek_index()]

    @property
    def blend_shift(self) -> tuple[float, float]:
        """当前帧到下一帧的整体位移，插值时用它把两帧对齐。"""
        cents = self.frame_set.centroids
        j = self._peek_index()
        if j == self._index or len(cents) <= max(j, self._index):
            return (0.0, 0.0)
        ax, ay = cents[self._index]
        bx, by = cents[j]
        return (bx - ax, by - ay)

    def advance(self, dt: float) -> None:
        n = len(self.frame_set.frames)
        if n <= 1:
            if not self.loop:
                self.finished = True
            return
        self._elapsed += dt
        step = 1.0 / self.fps
        while self._elapsed >= step:
            self._elapsed -= step
            if self.reverse:
                self._index -= 1
                if self._index < 0:
                    if self.loop:
                        self._index = n - 1
                    else:
                        self._index = 0
                        self.finished = True
                        break
            else:
                self._index += 1
                if self._index >= n:
                    if self.loop:
                        self._index = 0
                    else:
                        self._index = n - 1
                        self.finished = True
                        break

    @property
    def current(self) -> QPixmap:
        return self.frame_set.frames[self._index]


class FrameBlender:
    """把相邻两帧按播放进度混成一帧，补上 24fps 素材在 60Hz 屏幕上的空档。

    两帧先按质心差挪到同一位置再混合，否则站起/趴下那种十几像素的位移会混出双影。
    Qt 在一次绘制里同时用 opacity 和 Plus 会退化成普通叠加（中间态发虚），
    所以下一帧先单独淡化到临时层，再以 Plus 相加，合成结果才是两帧的线性插值。
    """

    def __init__(self) -> None:
        self._out = QImage()
        self._tmp = QImage()

    def _buffers(self, size: QSize) -> tuple[QImage, QImage]:
        if self._out.size() != size:
            self._out = QImage(size, QImage.Format_ARGB32_Premultiplied)
            self._tmp = QImage(size, QImage.Format_ARGB32_Premultiplied)
        return self._out, self._tmp

    def blend(self, a: QPixmap, b: QPixmap, t: float,
              dx: float = 0.0, dy: float = 0.0) -> QImage:
        out, tmp = self._buffers(a.size())

        tmp.fill(0)
        p = QPainter(tmp)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(t)
        p.drawPixmap(QPointF(-dx * (1.0 - t), -dy * (1.0 - t)), b)
        p.end()

        out.fill(0)
        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(1.0 - t)
        p.drawPixmap(QPointF(dx * t, dy * t), a)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setOpacity(1.0)
        p.drawImage(0, 0, tmp)
        p.end()
        return out


class SpriteLibrary:
    """按动作名缓存 Animation；同一 folder 的动作共享 FrameSet。"""

    def __init__(self) -> None:
        self._frame_sets: dict[str, FrameSet] = {}  # key = assets folder

    def _frame_set(self, action: str) -> FrameSet:
        folder = config.ACTIONS[action].folder
        if folder not in self._frame_sets:
            self._frame_sets[folder] = FrameSet.load(action)
        return self._frame_sets[folder]

    def make(self, action: str) -> Animation:
        spec = config.ACTIONS[action]
        return Animation(
            action,
            self._frame_set(action),
            spec.fps,
            spec.loop,
            reverse=spec.reverse,
        )

    def any_real_assets(self) -> bool:
        return any(
            not self._frame_set(a).is_placeholder for a in config.ACTIONS
        )

    def destroy_anchor(self) -> tuple[float, float]:
        """坐压接触点由素材构建器生成，坐标相对于动画帧。"""
        data = json.loads((_assets_root() / "destroy.json").read_text(encoding="utf-8"))
        x, y = map(float, data["impact_anchor"])
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("Invalid destroy contact anchor")
        return x, y

    def bounding_size(self) -> tuple[int, int]:
        """所有动作里最大的帧宽/高，用来给窗口留够绘制空间避免裁切。"""
        max_w = max_h = config.PET_MAX_SIZE
        seen: set[str] = set()
        for action in config.ACTIONS:
            folder = config.ACTIONS[action].folder
            if folder in seen:
                continue
            seen.add(folder)
            for pm in self._frame_set(action).frames:
                max_w = max(max_w, pm.width())
                max_h = max(max_h, pm.height())
        return max_w, max_h
