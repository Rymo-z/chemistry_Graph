"""下载 / 复用模型权重到项目内 models/ 目录。

- embedding：bge-large-zh-v1.5（SentenceTransformer 本地目录）
  - 默认从 HuggingFace（BAAI/bge-large-zh-v1.5）下载；
  - 也可用 `--source local --from-local <已有目录>` 复制本机已下好的模型，避免重下 ~1.3GB。
- YOLOv8：yolov8n.pt（Ultralytics 官方权重，AGPL-3.0）

用法：
    python scripts/download_models.py                          # 下载 bge + yolov8n
    python scripts/download_models.py --source local --from-local "D:\\...\\bge-large-zh-v1.5"
    python scripts/download_models.py --bge-only
    python scripts/download_models.py --yolo-only
    python scripts/download_models.py --force                  # 已存在也重新下载
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# 项目根 = scripts/ -> 项目根
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
BGE_REPO = "BAAI/bge-large-zh-v1.5"
BGE_LOCAL_DIR = MODELS_DIR / "bge-large-zh-v1.5"
YOLO_URL = "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt"
YOLO_FILE = MODELS_DIR / "yolov8n.pt"


def _download_bge_from_hf() -> None:
    """从 HuggingFace 拉取 bge-large-zh-v1.5 到 models/。"""
    from huggingface_hub import snapshot_download

    print(f"[bge] 从 HuggingFace 下载 {BGE_REPO} -> {BGE_LOCAL_DIR}")
    snapshot_download(repo_id=BGE_REPO, local_dir=str(BGE_LOCAL_DIR))


def _copy_bge_from_local(src: Path) -> None:
    """复制本机已有 bge 目录（省去重新下载）。"""
    if not src.is_dir():
        raise SystemExit(f"[bge] 本地目录不存在: {src}")
    print(f"[bge] 复制 {src} -> {BGE_LOCAL_DIR}")
    shutil.copytree(src, BGE_LOCAL_DIR, dirs_exist_ok=True)


def _download_yolo() -> None:
    """下载 yolov8n.pt 官方权重。"""
    import requests

    YOLO_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"[yolo] 下载 {YOLO_URL}")
    resp = requests.get(YOLO_URL, stream=True, timeout=60)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    done = 0
    with open(YOLO_FILE, "wb") as fp:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            fp.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r[yolo] {pct:3d}%  ({done / (1 << 20):.1f}/{total / (1 << 20):.1f} MB)", end="")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="下载/复用模型权重到 models/")
    parser.add_argument(
        "--source", choices=["hf", "local"], default="hf",
        help="bge 模型来源：hf 从 HuggingFace 下载（默认），local 从本机目录复制",
    )
    parser.add_argument("--from-local", type=Path, default=None,
                        help="--source local 时的本机 bge 目录路径")
    parser.add_argument("--bge-only", action="store_true", help="只处理 embedding 模型")
    parser.add_argument("--yolo-only", action="store_true", help="只处理 YOLO 权重")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载/复制")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.yolo_only:
        if BGE_LOCAL_DIR.exists() and not args.force:
            print(f"[bge] 已存在，跳过（--force 可重下）: {BGE_LOCAL_DIR}")
        else:
            if args.source == "local":
                if not args.from_local:
                    parser.error("--source local 需要 --from-local <路径>")
                _copy_bge_from_local(args.from_local)
            else:
                _download_bge_from_hf()

    if not args.bge_only:
        if YOLO_FILE.exists() and not args.force:
            print(f"[yolo] 已存在，跳过（--force 可重下）: {YOLO_FILE}")
        else:
            _download_yolo()

    # 提示按当前 .env 指向配置（示例模板默认指向 models/ 相对路径）
    print()
    print("完成。请确认 .env 中指向：")
    print(f"  EMBEDDING_MODEL=models/bge-large-zh-v1.5")
    print(f"  YOLO_MODEL_PATH=models/yolov8n.pt")
    print("（从项目根目录启动服务，start.bat / start.sh 已处理）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
