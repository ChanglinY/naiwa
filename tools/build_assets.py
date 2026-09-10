"""统一构建全部素材：抠绿幕 + 对齐到同一坐标空间 + 共用画布。

为什么需要统一：源素材有两批渲染（1940x1068 / 1920x1080），同一姿势在两批里
大小差约 1%、位置差十几像素。各动作各自裁切时，切换动作角色就会跳一下。

做法：
  1. 以 1940x1068 那批为参考空间；
  2. 用两批共有的姿势（趴姿 / 蹲姿 / 站姿）分别求出缩放+平移；
  3. 两批渲染的“趴姿↔站姿”相对比例差约 2%，单一变换无法同时对齐两端，
     所以过渡片段（趴→站 等）的变换按帧在两个解之间渐变，保证首尾都严丝合缝；
  4. 所有动作共用一个裁切框与缩放系数，角色在画布里的绝对位置一致；
  5. 剪掉各段首尾的静止帧（爬行循环留静止帧会看成“滑行”）。

用法: python tools/build_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_motion import build as build_motion  # noqa: E402
from tools.process_assets import key_chroma  # noqa: E402
from src import config  # noqa: E402

VIDEO_DIR = Path(r"C:\Users\lynnyi\Videos\奶蛙")
DRAG_IMAGE = Path(
    r"C:\Users\lynnyi\Pictures\奶蛙素材"
    r"\task_image_TaskImage__72406291151785927023419-604329fd506a4730b7cb4f855f38422a_0.png"
)

REF_SIZE = (1940, 1068)   # 参考空间 (w, h)
CACHE_DIR = ROOT / "_asset_cache"   # 对齐后的成品帧缓存，便于反复调裁剪规则

Transform = tuple[float, float, float]   # (scale, dx, dy)

# 动作 -> [(源文件, 变换)]；变换为 None=本身就在参考空间，
# str=固定变换，(a, b)=按帧从 a 渐变到 b
SEQUENCES: dict[str, list[tuple[str, object]]] = {
    "idle_transition": [("摸肚子.mp4", None)],
    "idle_special":    [("待机动作.mp4", None)],
    "laugh":           [("大笑1.mp4", None),
                        ("大笑2.mp4", "laugh_mid"),
                        ("大笑3.mp4", ("laugh_mid", "stand"))],
    "crawl_down":      [("爬行1.mp4", None)],
    "crawl":           [("爬行2.mp4", "prone")],
    "crawl_up":        [("爬行3.mp4", ("prone", "stand"))],
    "squat_down":      [("蹲下1.mp4", None)],
    "squat":           [("蹲下2.mp4", "squat")],
    "squat_up":        [("蹲下3.mp4", ("squat", "stand"))],
}

# 变换名 -> [(参考片, 参考帧, 待对齐片, 待对齐帧)]，多组取平均
ALIGN_SPECS: dict[str, list[tuple[str, int, str, int]]] = {
    "prone":     [("爬行1.mp4", -1, "爬行2.mp4", 0)],
    "squat":     [("蹲下1.mp4", -1, "蹲下2.mp4", 0)],
    "laugh_mid": [("大笑1.mp4", -1, "大笑2.mp4", 0)],
    "stand":     [("摸肚子.mp4", -1, "爬行3.mp4", -1),
                  ("摸肚子.mp4", -1, "蹲下3.mp4", -1),
                  ("摸肚子.mp4", -1, "大笑3.mp4", -1)],
}


# ---------------------------------------------------------------- 基础工具

def iter_keyed(path: Path) -> Iterator[np.ndarray]:
    """逐帧读取并抠像，避免整段视频占内存。"""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"无法打开: {path}")
    try:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            yield key_chroma(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()


def keyed_frame(path: Path, index: int) -> np.ndarray:
    """只取某一帧并抠像。index 支持负数。"""
    cap = cv2.VideoCapture(str(path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        i = index if index >= 0 else total + index
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, bgr = cap.read()
        if not ok:
            raise SystemExit(f"读不到帧 {index}: {path}")
        return key_chroma(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()


def bbox(rgba: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(rgba[:, :, 3] > 10)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def warp(rgba: np.ndarray, t: Transform) -> np.ndarray:
    s, dx, dy = t
    m = np.array([[s, 0.0, dx], [0.0, s, dy]], dtype=np.float32)
    return cv2.warpAffine(
        rgba, m, REF_SIZE, flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0)
    )


def solve_transform(ref: np.ndarray, src: np.ndarray) -> Transform:
    """由同一姿势的两帧求 缩放 + 平移（水平居中对齐、脚底对齐）。"""
    rb, sb = bbox(ref), bbox(src)
    assert rb and sb
    s = (((rb[2] - rb[0] + 1) / (sb[2] - sb[0] + 1))
         + ((rb[3] - rb[1] + 1) / (sb[3] - sb[1] + 1))) / 2
    dx = (rb[0] + rb[2]) / 2 - (sb[0] + sb[2]) / 2 * s
    return s, dx, rb[3] - sb[3] * s


def lerp(a: Transform, b: Transform, t: float) -> Transform:
    return tuple(x + (y - x) * t for x, y in zip(a, b))  # type: ignore[return-value]


def frame_transform(spec: object, i: int, total: int,
                    solved: dict[str, Transform]) -> Transform | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        return solved[spec]
    a, b = spec  # type: ignore[misc]
    t = i / max(1, total - 1)
    return lerp(solved[a], solved[b], t)


def trim_motion(frames: np.ndarray, ratio: float = 0.25) -> tuple[int, int]:
    """按帧间动作量剪掉首尾静止段。

    只用于爬行循环：播静止帧时窗口仍在平移，会看成角色“滑行”。
    其他段落都是原地播放，多几帧静止无所谓，用 trim_duplicates 更安全。
    """
    steps = [
        float(np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)).mean())
        for i in range(1, len(frames))
    ]
    thr = float(np.percentile(steps, 95)) * ratio
    moving = [i for i, v in enumerate(steps, start=1) if v >= thr]
    if not moving:
        return 0, len(frames) - 1
    return moving[0] - 1, moving[-1]


def trim_duplicates(frames: np.ndarray, head: bool, tail: bool) -> tuple[int, int]:
    """剪掉首/尾与端点几乎一样的重复帧，端点姿势本身一定保留。

    只删“看不出区别”的帧，所以衔接用的首尾姿势不会被削掉；
    爬行循环靠它去掉两端的静止段，避免窗口平移时看成滑行。
    """
    n = len(frames)
    if n < 3:
        return 0, n - 1

    def d(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())

    steps = [d(frames[i], frames[i - 1]) for i in range(1, n)]
    eps = max(float(np.percentile(steps, 95)) * 0.06, 1e-3)

    start = 0
    if head:
        while start + 1 < n and d(frames[start + 1], frames[0]) < eps:
            start += 1
    end = n - 1
    if tail:
        while end - 1 > start and d(frames[end - 1], frames[n - 1]) < eps:
            end -= 1
    return start, end


def clip_length(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


# ---------------------------------------------------------------- 主流程

def main() -> int:
    for parts in SEQUENCES.values():
        for name, _ in parts:
            if not (VIDEO_DIR / name).exists():
                raise SystemExit(f"缺少源文件: {name}")
    if not DRAG_IMAGE.exists():
        raise SystemExit(f"缺少拖拽图: {DRAG_IMAGE}")

    # --- 1. 求各姿势的对齐变换 ---
    print("== 求对齐变换 ==")
    solved: dict[str, Transform] = {}
    for key, specs in ALIGN_SPECS.items():
        got = []
        for ref_name, ref_i, src_name, src_i in specs:
            t = solve_transform(
                keyed_frame(VIDEO_DIR / ref_name, ref_i),
                keyed_frame(VIDEO_DIR / src_name, src_i),
            )
            print(f"  {key:9s} {src_name}: scale={t[0]:.5f} dx={t[1]:+.1f} dy={t[2]:+.1f}")
            got.append(t)
        solved[key] = tuple(float(np.mean([g[i] for g in got])) for i in range(3))  # type: ignore[assignment]
        if len(got) > 1:
            t = solved[key]
            print(f"  {key:9s} 平均: scale={t[0]:.5f} dx={t[1]:+.1f} dy={t[2]:+.1f}")

    # 拖拽图：按分辨率换算，再对齐到站姿的中心线与地面
    drag_raw = key_chroma(np.asarray(Image.open(DRAG_IMAGE).convert("RGB")))
    stand_ref = keyed_frame(VIDEO_DIR / "摸肚子.mp4", -1)
    sb, db = bbox(stand_ref), bbox(drag_raw)
    assert sb and db
    ds = REF_SIZE[1] / drag_raw.shape[0]
    drag_t: Transform = (
        ds,
        (sb[0] + sb[2]) / 2 - (db[0] + db[2]) / 2 * ds,
        sb[3] - db[3] * ds,
    )
    print(f"  drag      scale={drag_t[0]:.5f} dx={drag_t[1]:+.1f} dy={drag_t[2]:+.1f}")

    # --- 2. 第一遍：全局裁切框 ---
    print("\n== 扫描素材 ==")
    gx0 = gy0 = 10**9
    gx1 = gy1 = -1

    def note(b: tuple[int, int, int, int] | None) -> None:
        nonlocal gx0, gy0, gx1, gy1
        if b is None:
            return
        gx0, gy0 = min(gx0, b[0]), min(gy0, b[1])
        gx1, gy1 = max(gx1, b[2]), max(gy1, b[3])

    for action, parts in SEQUENCES.items():
        count = 0
        for name, spec in parts:
            total = clip_length(VIDEO_DIR / name)
            for i, rgba in enumerate(iter_keyed(VIDEO_DIR / name)):
                t = frame_transform(spec, i, total, solved)
                note(bbox(warp(rgba, t) if t is not None else rgba))
                count += 1
        print(f"  {action}: {count} 帧")

    note(bbox(warp(drag_raw, drag_t)))

    mx, my = int((gx1 - gx0) * 0.03), int((gy1 - gy0) * 0.03)
    gx0, gy0 = max(0, gx0 - mx), max(0, gy0 - my)
    gx1 = min(REF_SIZE[0] - 1, gx1 + mx)
    gy1 = min(REF_SIZE[1] - 1, gy1 + my)
    box_w, box_h = gx1 - gx0 + 1, gy1 - gy0 + 1
    out_scale = config.PET_MAX_SIZE / max(box_w, box_h)
    out_w, out_h = round(box_w * out_scale), round(box_h * out_scale)
    print(f"\n全局裁切框 ({gx0},{gy0})-({gx1},{gy1})  {box_w}x{box_h} -> 画布 {out_w}x{out_h}")

    # --- 3. 第二遍：裁切缩放后缓存（未裁剪静止帧）---
    print("\n== 生成缓存 ==")
    CACHE_DIR.mkdir(exist_ok=True)

    def finish(rgba: np.ndarray) -> np.ndarray:
        crop = rgba[gy0:gy1 + 1, gx0:gx1 + 1]
        img = Image.fromarray(crop, mode="RGBA").resize((out_w, out_h), Image.LANCZOS)
        return np.asarray(img, dtype=np.uint8)

    for action, parts in SEQUENCES.items():
        stack = []
        for name, spec in parts:
            total = clip_length(VIDEO_DIR / name)
            for i, rgba in enumerate(iter_keyed(VIDEO_DIR / name)):
                t = frame_transform(spec, i, total, solved)
                stack.append(finish(warp(rgba, t) if t is not None else rgba))
        np.save(CACHE_DIR / f"{action}.npy", np.stack(stack))
        print(f"  {action}: {len(stack)} 帧")
    np.save(CACHE_DIR / "drag.npy", np.stack([finish(warp(drag_raw, drag_t))]))
    print("  drag: 1 帧")
    return write_assets()


def write_assets() -> int:
    """从缓存裁剪静止帧并输出 PNG（可单独重跑，不必重新抠像）。"""
    # 首/尾是否允许剪掉重复帧：末尾姿势要接回站姿的段落也可以剪，
    # 因为只剪“与端点几乎一样”的帧，端点姿势本身保留。
    TRIM = {
        "idle_transition": (True, True),
        "idle_special":    (True, True),
        "laugh":           (True, True),
        "crawl_down":      (True, True),
        "crawl":           (True, True),
        "crawl_up":        (True, True),
        "squat_down":      (True, True),
        "squat":           (True, True),
        "squat_up":        (True, True),
    }

    def fresh_dir(action: str) -> Path:
        out_dir = ROOT / "assets" / action
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.png"):
            old.unlink()
        return out_dir

    print("\n== 输出 ==")
    ends: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for action, (head, tail) in TRIM.items():
        frames = np.load(CACHE_DIR / f"{action}.npy")
        if action == "crawl":
            start, end = trim_motion(frames)
        else:
            start, end = trim_duplicates(frames, head, tail)
        kept = frames[start:end + 1]
        out_dir = fresh_dir(action)
        for i, f in enumerate(kept):
            Image.fromarray(f, mode="RGBA").save(out_dir / f"frame_{i:04d}.png")
        ends[action] = (kept[0], kept[-1])
        print(f"  {action}: {len(frames)} -> {len(kept)} png (保留 {start}..{end})")

    for action, frame in [
        ("idle_relax", ends["idle_transition"][0]),
        ("idle_belly", ends["idle_transition"][1]),
    ]:
        Image.fromarray(frame, mode="RGBA").save(fresh_dir(action) / "frame_0000.png")
        print(f"  {action}: 1 png")

    drag = np.load(CACHE_DIR / "drag.npy")[0]
    Image.fromarray(drag, mode="RGBA").save(fresh_dir("drag") / "frame_0000.png")
    print("  drag: 1 png")

    # --- 4. 帧质心表：运行时帧间插值要用 ---
    print()
    build_motion()

    # --- 5. 接缝自检 ---
    belly = ends["idle_transition"][1]

    def d(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())

    print("\n== 接缝检查 (数值越小越顺) ==")
    for label, a, b in [
        ("捧腹站姿 -> 趴下起始", belly, ends["crawl_down"][0]),
        ("趴下结束 -> 爬行起始", ends["crawl_down"][1], ends["crawl"][0]),
        ("爬行结束 -> 站起起始", ends["crawl"][1], ends["crawl_up"][0]),
        ("站起结束 -> 捧腹站姿", ends["crawl_up"][1], belly),
        ("爬行循环首尾", ends["crawl"][1], ends["crawl"][0]),
        ("捧腹站姿 -> 蹲下起始", belly, ends["squat_down"][0]),
        ("蹲下结束 -> 蹲姿循环", ends["squat_down"][1], ends["squat"][0]),
        ("蹲姿循环 -> 起身起始", ends["squat"][1], ends["squat_up"][0]),
        ("起身结束 -> 捧腹站姿", ends["squat_up"][1], belly),
        ("捧腹站姿 -> 难绷起始", belly, ends["laugh"][0]),
        ("难绷结束 -> 捧腹站姿", ends["laugh"][1], belly),
        ("捧腹站姿 -> 特殊待机", belly, ends["idle_special"][0]),
        ("特殊待机 -> 捧腹站姿", ends["idle_special"][1], belly),
    ]:
        print(f"  {label}: {d(a, b):.3f}")
    return 0


if __name__ == "__main__":
    # --reuse: 跳过抠像，直接用缓存重新裁剪输出
    if "--reuse" in sys.argv and (CACHE_DIR / "drag.npy").exists():
        raise SystemExit(write_assets())
    raise SystemExit(main())
