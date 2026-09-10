"""素材处理流水线：视频/图片 -> 透明序列帧。

用法示例:
    # 处理一段吃饭动作的绿幕视频，自动选择抠图方法
    python tools/process_assets.py --input raw/eat.mp4 --action eat

    # 处理一个装满绿幕图片的文件夹
    python tools/process_assets.py --input raw/walk_frames --action walk

    # 强制指定抠图方法
    python tools/process_assets.py --input raw/sleep.mp4 --action sleep --method rembg

参数:
    --input    视频文件 / 图片文件 / 图片文件夹
    --action   目标动作名 (idle/walk/drag/bath/eat/sleep ...)，输出到 assets/<action>/
    --method   auto(默认) | chroma(绿幕抠色) | rembg(AI 抠图)
    --fps      从视频抽帧的帧率(默认 12)
    --max-frames  最多保留多少帧(默认 0=不限)
    --size     输出最大边长(默认取 config.PET_MAX_SIZE)

依赖(仅处理素材时需要，运行桌宠不需要):
    pip install -r requirements-tools.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


# ---------------------------------------------------------------- 帧读取

def read_frames(inp: Path, fps: int):
    """返回 RGB numpy 帧列表。"""
    import numpy as np  # noqa: F401

    if inp.is_dir():
        files = sorted(p for p in inp.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not files:
            raise SystemExit(f"文件夹里没有图片: {inp}")
        return [_read_image(p) for p in files]

    ext = inp.suffix.lower()
    if ext in IMAGE_EXTS:
        return [_read_image(inp)]
    if ext in VIDEO_EXTS:
        return _read_video(inp, fps)
    raise SystemExit(f"不支持的输入类型: {inp}")


def _read_image(path: Path):
    import numpy as np
    from PIL import Image

    img = Image.open(path).convert("RGB")
    return np.asarray(img)


def _read_video(path: Path, fps: int):
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"无法打开视频: {path}")
    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 24.0
    step = max(1, round(src_fps / fps)) if fps else 1
    frames = []
    i = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        if i % step == 0:
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        i += 1
    cap.release()
    if not frames:
        raise SystemExit(f"未能从视频读到帧: {path}")
    return frames


# ---------------------------------------------------------------- 方法选择

def choose_method(frame) -> str:
    """根据首帧背景判断走绿幕抠色还是 AI 抠图。

    采样四周边框像素：若整体明显偏绿且较均匀 -> chroma，否则 rembg。
    """
    import numpy as np

    h, w, _ = frame.shape
    m = max(2, int(min(h, w) * 0.06))
    border = np.concatenate([
        frame[:m, :, :].reshape(-1, 3),
        frame[-m:, :, :].reshape(-1, 3),
        frame[:, :m, :].reshape(-1, 3),
        frame[:, -m:, :].reshape(-1, 3),
    ]).astype(np.float32)

    r, g, b = border[:, 0], border[:, 1], border[:, 2]
    green_dominant = float(np.mean((g > r + 25) & (g > b + 25)))
    std = float(np.mean(np.std(border, axis=0)))

    if green_dominant > 0.6 and std < 55:
        print(f"[auto] 背景偏绿且均匀 (green={green_dominant:.2f}, std={std:.1f}) -> chroma")
        return "chroma"
    print(f"[auto] 背景不适合绿幕抠色 (green={green_dominant:.2f}, std={std:.1f}) -> rembg")
    return "rembg"


# ---------------------------------------------------------------- 抠图

def key_chroma(frame):
    """绿幕抠像：差值键(greenness) + 连通背景清除 + 全图去绿溢色。

    对 AI 绿幕(绿色不纯、带绿晕)也能把绿边清干净，同时尽量不吃主体。
    返回 RGBA(np.uint8)。
    """
    import cv2
    import numpy as np

    h, w, _ = frame.shape
    f = frame.astype(np.float32)
    r, g, b = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    mx_rb = np.maximum(r, b)
    greenness = g - mx_rb            # >0 越大越绿

    # 从边框估计背景绿度作为阈值基准
    m = max(2, int(min(h, w) * 0.05))
    border = np.concatenate([
        greenness[:m, :].ravel(), greenness[-m:, :].ravel(),
        greenness[:, :m].ravel(), greenness[:, -m:].ravel(),
    ])
    pos = border[border > 0]
    bg_level = float(np.median(pos)) if pos.size else 40.0
    bg_level = max(bg_level, 22.0)

    # 差值键：绿度越接近背景越透明；明显非绿处完全不透明
    low = bg_level * 0.30
    alpha = np.clip((bg_level - greenness) / (bg_level - low + 1e-6), 0.0, 1.0)
    alpha[greenness <= low] = 1.0
    alpha[greenness >= bg_level] = 0.0

    # 连通背景清除：把与画面边缘相连的绿色(含腿间空洞)彻底抠掉
    hsv = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    green_hard = ((greenness > bg_level * 0.55) & (hsv[:, :, 1] > 55)).astype(np.uint8) * 255
    work = green_hard.copy()
    for x in range(0, w, max(1, w // 60)):
        if work[0, x] == 255:
            cv2.floodFill(work, None, (x, 0), 128)
        if work[h - 1, x] == 255:
            cv2.floodFill(work, None, (x, h - 1), 128)
    for y in range(0, h, max(1, h // 60)):
        if work[y, 0] == 255:
            cv2.floodFill(work, None, (0, y), 128)
        if work[y, w - 1] == 255:
            cv2.floodFill(work, None, (w - 1, y), 128)
    alpha[work == 128] = 0.0

    a8 = (alpha * 255).astype(np.uint8)
    # 填主体内部细小空洞，但不做腐蚀/开运算，保住尾巴等细节
    a8 = cv2.morphologyEx(a8, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    a8 = cv2.GaussianBlur(a8, (3, 3), 0)

    # 全图去绿溢色：把每个像素的绿通道压到不超过 max(r,b)，消除绿晕
    out = frame.copy()
    cap = np.maximum(out[:, :, 0], out[:, :, 2])
    out[:, :, 1] = np.minimum(out[:, :, 1], cap)

    return np.dstack([out, a8])


def key_rembg(frame, session):
    """AI 抠图，返回 RGBA。"""
    from rembg import remove
    import numpy as np
    from PIL import Image

    out = remove(Image.fromarray(frame), session=session)
    return np.asarray(out.convert("RGBA"))


# ---------------------------------------------------------------- 后处理

def autocrop(rgba, margin_ratio: float = 0.04):
    import numpy as np

    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha > 10)
    if len(xs) == 0:
        return rgba
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    mx = int((x1 - x0) * margin_ratio)
    my = int((y1 - y0) * margin_ratio)
    x0 = max(0, x0 - mx); y0 = max(0, y0 - my)
    x1 = min(rgba.shape[1] - 1, x1 + mx); y1 = min(rgba.shape[0] - 1, y1 + my)
    return rgba[y0:y1 + 1, x0:x1 + 1]


def union_crop(frames_rgba, margin_ratio: float = 0.10):
    """用全部帧的外接矩形做统一裁切，避免逐帧缩放跳动。"""
    import numpy as np

    x0 = y0 = 10**9
    x1 = y1 = -1
    for rgba in frames_rgba:
        ys, xs = np.where(rgba[:, :, 3] > 10)
        if len(xs) == 0:
            continue
        x0 = min(x0, int(xs.min()))
        x1 = max(x1, int(xs.max()))
        y0 = min(y0, int(ys.min()))
        y1 = max(y1, int(ys.max()))
    if x1 < 0:
        return frames_rgba

    h, w = frames_rgba[0].shape[:2]
    mx = int((x1 - x0) * margin_ratio)
    my = int((y1 - y0) * margin_ratio)
    x0 = max(0, x0 - mx); y0 = max(0, y0 - my)
    x1 = min(w - 1, x1 + mx); y1 = min(h - 1, y1 + my)
    return [rgba[y0:y1 + 1, x0:x1 + 1] for rgba in frames_rgba]


def save_frame(rgba, out_path: Path, max_size: int):
    from PIL import Image

    img = Image.fromarray(rgba, mode="RGBA")
    if max_size and max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    img.save(out_path)


def stabilize_frames(frames_rgba, margin: float = 0.08):
    """把每帧主体放到固定画布：水平居中、脚底对齐，走路时不会在框里漂移。"""
    import numpy as np

    boxes = []
    for rgba in frames_rgba:
        ys, xs = np.where(rgba[:, :, 3] > 10)
        if len(xs) == 0:
            boxes.append(None)
            continue
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))

    widths = [b[2] - b[0] + 1 for b in boxes if b]
    heights = [b[3] - b[1] + 1 for b in boxes if b]
    if not widths:
        return frames_rgba

    # 画布取最大主体尺寸 + 边距
    base_w = max(widths)
    base_h = max(heights)
    canvas_w = int(base_w * (1 + margin * 2))
    canvas_h = int(base_h * (1 + margin * 2))
    pad_x = (canvas_w - base_w) // 2
    pad_y = (canvas_h - base_h) // 2

    out = []
    for rgba, box in zip(frames_rgba, boxes):
        canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
        if box is None:
            out.append(canvas)
            continue
        x0, y0, x1, y1 = box
        crop = rgba[y0:y1 + 1, x0:x1 + 1]
        # 水平居中，脚底对齐到同一基线
        dx = pad_x + (base_w - crop.shape[1]) // 2
        dy = pad_y + (base_h - crop.shape[0])
        x_end = min(canvas_w, dx + crop.shape[1])
        y_end = min(canvas_h, dy + crop.shape[0])
        sx = max(0, -dx); sy = max(0, -dy)
        dx = max(0, dx); dy = max(0, dy)
        canvas[dy:y_end, dx:x_end] = crop[sy:sy + (y_end - dy), sx:sx + (x_end - dx)]
        out.append(canvas)
    return out


def save_frames_uniform(frames_rgba, out_dir: Path, max_size: int, stabilize: bool = False):
    """统一画布尺寸后再缩放保存，保证序列帧宽高一致。"""
    import numpy as np
    from PIL import Image

    if stabilize:
        frames_rgba = stabilize_frames(frames_rgba)
    else:
        frames_rgba = union_crop(frames_rgba)
        max_h = max(f.shape[0] for f in frames_rgba)
        max_w = max(f.shape[1] for f in frames_rgba)
        padded = []
        for rgba in frames_rgba:
            canvas = np.zeros((max_h, max_w, 4), dtype=np.uint8)
            y = (max_h - rgba.shape[0]) // 2
            x = (max_w - rgba.shape[1]) // 2
            canvas[y:y + rgba.shape[0], x:x + rgba.shape[1]] = rgba
            padded.append(canvas)
        frames_rgba = padded

    for i, rgba in enumerate(frames_rgba):
        img = Image.fromarray(rgba, mode="RGBA")
        if max_size and max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        img.save(out_dir / f"frame_{i:04d}.png")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    from src import config

    ap = argparse.ArgumentParser(description="视频/图片 -> 透明序列帧")
    ap.add_argument("--input", required=True)
    ap.add_argument("--action", required=True)
    ap.add_argument("--method", choices=["auto", "chroma", "rembg"], default="auto")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--start-sec", type=float, default=0.0, help="跳过片头秒数")
    ap.add_argument("--stabilize", action="store_true", help="主体居中+脚底对齐（走路推荐）")
    ap.add_argument("--size", type=int, default=config.PET_MAX_SIZE)
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        raise SystemExit(f"输入不存在: {inp}")

    out_dir = ROOT / "assets" / args.action
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    print(f"读取帧: {inp}")
    frames = read_frames(inp, args.fps)
    if args.start_sec > 0:
        skip = int(args.start_sec * args.fps)
        frames = frames[skip:]
        print(f"跳过片头 {args.start_sec}s -> 剩余 {len(frames)} 帧")
    if args.max_frames > 0:
        frames = frames[:args.max_frames]
    print(f"共 {len(frames)} 帧")

    method = args.method
    if method == "auto":
        method = choose_method(frames[0])

    session = None
    if method == "rembg":
        from rembg import new_session
        session = new_session("u2net")

    keyed = []
    for i, frame in enumerate(frames):
        if method == "chroma":
            keyed.append(key_chroma(frame))
        else:
            keyed.append(key_rembg(frame, session))
        if (i + 1) % 10 == 0 or i == len(frames) - 1:
            print(f"  key {i + 1}/{len(frames)}")

    save_frames_uniform(keyed, out_dir, args.size, stabilize=args.stabilize)
    print(f"完成 -> {out_dir}  (method={method}, stabilize={args.stabilize})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
