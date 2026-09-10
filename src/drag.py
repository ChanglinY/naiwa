"""按秒推进的阻尼弹簧，不依赖鼠标事件频率。"""
import math
from . import config


class DragSway:
    def __init__(self):
        self.angle = 0.0
        self.velocity = 0.0
        self.cursor_velocity = 0.0

    def advance(self, dt: float, dx: float = 0.0) -> float:
        if dt <= 0:
            return self.angle
        elapsed = min(dt, 0.1)
        raw_velocity = max(-2500.0, min(2500.0, dx / dt))
        self.cursor_velocity += (raw_velocity - self.cursor_velocity) * (1 - math.exp(-elapsed * 18))
        target = max(-config.DRAG_MAX_TILT, min(config.DRAG_MAX_TILT,
                     self.cursor_velocity * config.DRAG_TILT_GAIN))
        steps = max(1, math.ceil(elapsed * 240))
        step = elapsed / steps
        for _ in range(steps):
            self.velocity += (config.DRAG_SWAY_STIFFNESS * (target - self.angle)
                              - config.DRAG_SWAY_DAMPING * self.velocity) * step
            self.angle += self.velocity * step
            if abs(self.angle) > config.DRAG_MAX_TILT:
                self.angle = math.copysign(config.DRAG_MAX_TILT, self.angle)
                if self.angle * self.velocity > 0:
                    self.velocity = 0.0
        return self.angle
