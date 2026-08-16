"""PPED 数据集：PASCAL-VOC XML → ultralytics YOLO 格式 + 9:1 train/val 划分。

输入（解压 PPED_data.zip 后）：
    datasets/PPED/data/JPEGImages/*.jpg     原图
    datasets/PPED/data/Annotations/*.xml     VOC 标注
    datasets/PPED/data/feature.csv           元数据（仅参考）

输出（ultralytics 标准布局，可直接喂给 yolo train）：
    datasets/PPED/
        images/train/*.jpg
        images/val/*.jpg
        labels/train/*.txt
        labels/val/*.txt
        data.yaml         nc=6 + 类别名
        classes.txt       类别名（id 顺序）

运行：
    python -m _007_fine_tune.convert_voc2yolo
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Optional

from common.logger import get_logger

logger = get_logger(__name__)

# 类别 id → 名称。PPED 按 GB 39800.1-2020 的 6 类防护用品（与论文一致）。
CLASS_NAMES: list[str] = [
    "protective_glasses",    # 护目镜
    "face_shield",           # 防护面罩
    "gas_mask",              # 防毒面具
    "mask",                  # 口罩
    "protective_clothing",   # 防护服
    "protective_gloves",     # 防护手套
]

# XML 原始类别名（PPED 数据集用驼峰缩写）→ 规范类名。核对过 3317 个 XML，
# 恰好 6 类且能一一对应，没有多余/遗漏。
VOC_NAME_MAP: dict[str, str] = {
    "Goggles": "protective_glasses",    # 护目镜
    "Face_Shield": "face_shield",       # 防护面罩
    "Gas_Mask": "gas_mask",             # 防毒面具
    "Mask": "mask",                     # 口罩
    "Coverall": "protective_clothing",  # 防护服
    "Gloves": "protective_gloves",      # 防护手套
}

# 9:1 划分：文件名 hash 落到 [0,10) 取 < 9 → train
VAL_EVERY: int = 10


def _load_image_size(anno_path: Path) -> Optional[tuple[int, int]]:
    """从 XML <size> 读图片宽高；缺省时返回 None（调用方用图像实际尺寸兜底）。"""
    try:
        root = ET.parse(anno_path).getroot()
        w = int(root.findtext("size/width") or 0)
        h = int(root.findtext("size/height") or 0)
        return (w, h) if w > 0 and h > 0 else None
    except (ET.ParseError, OSError, ValueError):
        return None


def _object_names(anno_path: Path) -> list[str]:
    """读取一个 XML 里所有 <object><name>，归一化为规范类名，用于校验类别覆盖。"""
    root = ET.parse(anno_path).getroot()
    return [VOC_NAME_MAP.get(obj.findtext("name") or "", obj.findtext("name") or "")
            for obj in root.findall("object")]


def _xml_to_yolo_lines(anno_path: Path, w_img: int, h_img: int) -> list[str]:
    """VOC XML → YOLO txt 行（归一化 cx/cy/w/h）。跳过无法解析/越界的框。"""
    root = ET.parse(anno_path).getroot()
    lines: list[str] = []
    for obj in root.findall("object"):
        raw = (obj.findtext("name") or "").strip()
        name = VOC_NAME_MAP.get(raw, raw)
        if name not in CLASS_NAMES:
            continue
        cls_id = CLASS_NAMES.index(name)
        box = obj.find("bndbox")
        if box is None:
            continue
        try:
            xmin = float(box.findtext("xmin") or 0)
            ymin = float(box.findtext("ymin") or 0)
            xmax = float(box.findtext("xmax") or 0)
            ymax = float(box.findtext("ymax") or 0)
        except (TypeError, ValueError):
            continue
        if xmax <= xmin or ymax <= ymin or w_img <= 0 or h_img <= 0:
            continue
        cx = (xmin + xmax) / 2 / w_img
        cy = (ymin + ymax) / 2 / h_img
        w = (xmax - xmin) / w_img
        h = (ymax - ymin) / h_img
        # 裁剪到 [0,1] 防御 XML 越界框
        cx, cy, w, h = (max(0.0, min(1.0, v)) for v in (cx, cy, w, h))
        lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines


def main() -> None:
    datasets_dir = Path(__file__).parent / "datasets"
    pped_data = datasets_dir / "PPED" / "data"
    jpeg_dir = pped_data / "JPEGImages"
    anno_dir = pped_data / "Annotations"

    if not jpeg_dir.is_dir() or not anno_dir.is_dir():
        logger.error("未找到 PPED 数据目录（%s / %s），请先解压 PPED_data.zip", jpeg_dir, anno_dir)
        raise SystemExit(1)

    # 1) 统计类别覆盖，确认 CLASS_NAMES 与数据一致
    counter: Counter[str] = Counter()
    for xml in sorted(anno_dir.glob("*.xml")):
        for name in _object_names(xml):
            counter[name] += 1
    logger.info("XML 中出现的类别：%s", dict(counter))
    unknown = set(counter) - set(CLASS_NAMES)
    if unknown:
        logger.warning("CLASS_NAMES 未覆盖的类别（将被忽略）：%s", unknown)
    for name in CLASS_NAMES:
        if name not in counter:
            logger.warning("类别 %s 在数据中无样本，检查类别名", name)

    # 2) 收集有效样本（XML 可解析且对应图片存在）
    samples: list[tuple[Path, Path]] = []
    for xml in sorted(anno_dir.glob("*.xml")):
        jpg = jpeg_dir / (xml.stem + ".jpg")
        if not jpg.is_file():
            continue
        size = _load_image_size(xml)
        if size is None:
            # 缺 <size> 时用图像实际宽高兜底
            from PIL import Image
            try:
                with Image.open(jpg) as im:
                    size = im.size
            except OSError:
                continue
        samples.append((xml, jpg))

    logger.info("有效样本 %d 张", len(samples))
    if not samples:
        logger.error("没有可转换的样本，终止")
        raise SystemExit(1)

    # 3) 9:1 划分并写出 ultralytics 布局
    out = datasets_dir / "PPED"
    for subset in ("train", "val"):
        (out / "images" / subset).mkdir(parents=True, exist_ok=True)
        (out / "labels" / subset).mkdir(parents=True, exist_ok=True)

    n_train = n_val = 0
    for i, (xml, jpg) in enumerate(samples):
        subset = "val" if i % VAL_EVERY == 0 else "train"
        dst_jpg = out / "images" / subset / jpg.name
        dst_txt = out / "labels" / subset / (jpg.stem + ".txt")
        if not dst_jpg.is_file():
            shutil.copy2(jpg, dst_jpg)
        w_img, h_img = _load_image_size(xml) or (None, None)
        if w_img is None:
            from PIL import Image
            with Image.open(jpg) as im:
                w_img, h_img = im.size
        lines = _xml_to_yolo_lines(xml, w_img, h_img)
        dst_txt.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if subset == "train":
            n_train += 1
        else:
            n_val += 1

    # 4) classes.txt + data.yaml
    (out / "classes.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")
    yaml_lines = [
        f"# PPED 化工防护数据集（GB 39800.1-2020）",
        f"path: {out.as_posix()}   # 数据集根目录",
        "train: images/train",
        "val: images/val",
        f"nc: {len(CLASS_NAMES)}",
        "names:",
    ]
    for cid, name in enumerate(CLASS_NAMES):
        yaml_lines.append(f"  {cid}: {name}")
    (out / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    logger.info("转换完成：train=%d val=%d → %s", n_train, n_val, out / "data.yaml")


if __name__ == "__main__":
    main()
