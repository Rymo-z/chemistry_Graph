"""PPED 数据集 CPU 短训脚本（YOLOv8n 微调）。

按任务链 #37：CPU 3~5 轮短训（imgsz 320，fraction 子集防 OOM）。
输出 runs/<name>/weights/best.pt，供 #38 验证。

用法：
    python -m _007_fine_tune.train_pped --epochs 3 --fraction 0.5
    python -m _007_fine_tune.train_pped --epochs 5 --fraction 1.0
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO

MODEL = Path(__file__).parent.parent / "models" / "yolov8n.pt"
DATA = Path(__file__).parent / "datasets" / "PPED" / "data.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="PPED CPU 短训")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数（短训建议 3~5）")
    parser.add_argument("--fraction", type=float, default=0.5, help="数据子集比例，防 CPU OOM")
    parser.add_argument("--imgsz", type=int, default=320, help="输入尺寸")
    parser.add_argument("--batch", type=int, default=16, help="批次大小")
    parser.add_argument("--name", type=str, default="pped_cpu", help="run 名称")
    args = parser.parse_args()

    if not MODEL.is_file():
        raise SystemExit(f"缺预训练权重：{MODEL}")
    if not DATA.is_file():
        raise SystemExit(f"缺数据集 yaml：{DATA}")

    print(f"[train] 模型 {MODEL} | 数据 {DATA} | epochs={args.epochs} "
          f"fraction={args.fraction} imgsz={args.imgsz} batch={args.batch}", flush=True)

    model = YOLO(str(MODEL))
    model.train(
        data=str(DATA),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        fraction=args.fraction,
        device="cpu",
        workers=2,
        cache=False,
        project=str(Path(__file__).parent / "runs"),
        name=args.name,
        exist_ok=True,
    )
    best = Path(__file__).parent / "runs" / args.name / "weights" / "best.pt"
    print(f"[train] 完成，best.pt = {best} (存在={best.is_file()})", flush=True)


if __name__ == "__main__":
    main()
