"""算出每个动作各帧主体的质心，写到 assets/motion.json。

运行时把相邻两帧按播放进度混合，用来补上 24fps 素材在 60Hz 屏幕上的空档。
直接混合会出双影（站起那一下相邻帧能差十几像素），先按质心差把两帧挪到
同一位置再混合，中间态就只剩轻微柔化。

用法: python tools/build_motion.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUT = ASSETS / "motion.json"


def centroids(folder: Path) -> list[list[float]]:
    """各帧 alpha 加权质心（像素坐标，相对该动作的画布）。"""
    result: list[list[float]] = []
    for path in sorted(folder.glob("*.png")):
        alpha = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)[..., 3]
        total = alpha.sum()
        if total <= 0:
            result.append([0.0, 0.0])
            continue
        h, w = alpha.shape
        cx = (alpha * np.arange(w)[None, :]).sum() / total
        cy = (alpha * np.arange(h)[:, None]).sum() / total
        result.append([round(float(cx), 2), round(float(cy), 2)])
    return result


def build() -> int:
    data: dict[str, list[list[float]]] = {}
    for folder in sorted(p for p in ASSETS.iterdir() if p.is_dir()):
        c = centroids(folder)
        if len(c) > 1:   # 单帧动作不需要插值
            data[folder.name] = c
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"写出 {OUT}：{len(data)} 个动作，"
          f"{sum(len(v) for v in data.values())} 帧")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
