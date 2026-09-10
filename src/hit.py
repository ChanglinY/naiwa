from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IconHit:
    """A desktop icon's path, label, and screen-pixel bounding rectangle."""

    path: str
    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def contains(self, px: int, py: int) -> bool:
        """Use half-open bounds, matching Win32 rectangle conventions."""
        return (
            self.w > 0
            and self.h > 0
            and self.x <= px < self.x + self.w
            and self.y <= py < self.y + self.h
        )


def hit_icon(icons: Iterable[IconHit], px: int, py: int) -> IconHit | None:
    """Return the first icon whose screen rectangle contains the point."""
    return next((icon for icon in icons if icon.contains(px, py)), None)
