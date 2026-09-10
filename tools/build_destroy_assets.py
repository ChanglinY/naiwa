"""Build the five destroy clips without resizing/rebuilding existing pet assets.

python tools/build_destroy_assets.py [--video-dir PATH]
The return clip reverses the original turn, without mirroring, to join both poses.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.build_assets import bbox, iter_keyed, keyed_frame, solve_transform
from tools.build_motion import centroids


def build(video_dir: Path) -> None:
    assets = ROOT / "assets"
    reference = np.asarray(Image.open(assets / "idle_belly/frame_0000.png").convert("RGBA"))
    height, width = reference.shape[:2]
    turn = video_dir / "销毁1-往左转.mp4"
    slam = video_dir / "销毁2.mp4"
    first = keyed_frame(turn, 0)
    scale, dx, dy = solve_transform(reference, first)
    relative = solve_transform(keyed_frame(turn, -1), keyed_frame(slam, 0))
    side = (scale * relative[0], dx + scale * relative[1], dy + scale * relative[2])
    sequences = [
        ("destroy_turn", turn, (scale, dx, dy), False),
        ("destroy_slam", slam, side, False),
        ("destroy_rise", video_dir / "销毁3.mp4", side, False),
        ("destroy_return", turn, (scale, dx, dy), True),
        ("destroy_sniff", video_dir / "摸屁股闻手.mp4", (scale, dx, dy), False),
    ]
    metadata = {"canvas": [width, height], "clips": {}}
    preview = []
    motion_path = assets / "motion.json"
    motion = json.loads(motion_path.read_text(encoding="utf-8"))
    for action, source, transform, reverse in sequences:
        cap = cv2.VideoCapture(str(source))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        if abs(fps - 24) > 0.01:
            raise ValueError(f"Expected 24fps source, got {fps}: {source}")
        s, x, y = transform
        matrix = np.array([[s, 0, x], [0, s, y]], dtype=np.float32)
        folder = assets / action
        folder.mkdir(exist_ok=True)
        frames = []
        for rgba in iter_keyed(source):
            frame = cv2.warpAffine(rgba, matrix, (width, height), flags=cv2.INTER_AREA)
            frames.append(Image.fromarray(frame))
        if not frames:
            raise ValueError(f"Empty clip: {source}")
        if reverse:
            frames.reverse()
        # Only remove this builder's frames, after fully decoding the source.
        assert folder.resolve().parent == assets.resolve()
        for old in folder.glob("frame_*.png"):
            old.unlink()
        for index, frame in enumerate(frames):
            frame.save(folder / f"frame_{index:04d}.png")
        motion[action] = centroids(folder)
        metadata["clips"][action] = {"source": source.name, "frames": len(frames), "fps": fps,
                                       "horizontal_mirror": False, "reverse": reverse}
        if action == "destroy_slam":
            # Rear half of the seated silhouette; exclude extended feet on the left.
            alpha = np.asarray(frames[-1])[..., 3]
            b = bbox(np.asarray(frames[-1]))
            assert b is not None
            contact_x = b[0] + (b[2] - b[0]) * 0.76
            column = alpha[:, max(0, round(contact_x) - 3):round(contact_x) + 4]
            contact_y = int(np.where(column.max(axis=1) > 96)[0][-1])
            metadata["impact_anchor"] = [round(contact_x / width, 6), round(contact_y / height, 6)]
        for frame in frames[::2]:
            background = Image.new("RGBA", frame.size, (239, 237, 230, 255))
            background.alpha_composite(frame)
            preview.append(background.convert("RGB"))
        print(f"{action}: {len(frames)} frames", flush=True)
    motion_path.write_text(json.dumps(motion, separators=(",", ":")), encoding="utf-8")
    (assets / "destroy.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    preview[0].save(ROOT / "build/destroy-preview.gif", save_all=True, append_images=preview[1:],
                    duration=83, loop=0)
    print("Impact anchor:", metadata["impact_anchor"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-dir", type=Path, default=Path.home() / "Videos" / "奶蛙")
    build(parser.parse_args().video_dir)
