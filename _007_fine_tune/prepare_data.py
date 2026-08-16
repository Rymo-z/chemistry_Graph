"""从抽取结果生成微调 QA 对。

基于实体关系规则自动组合 QA 对（无需 LLM，可离线、可复现），
输出为标准指令微调格式的 jsonl：
    {"instruction": "...", "output": "..."}

运行：
    python -m _007_fine_tune.prepare_data
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

# 关系类型 → (问题模板, 答案模板)，{src}/{tgt} 为实体占位，{basis} 为条款/依据
_QA_TEMPLATES: dict[str, tuple[str, str]] = {
    "REQUIRES": (
        "{src}需要办理什么手续？",
        "根据{basis}，{src}需要办理/取得{tgt}。",
    ),
    "HAS_PERMIT": (
        "{src}需要办理什么作业票？",
        "根据{basis}，{src}需要办理{tgt}。",
    ),
    "REQUIRES_QUALIFICATION": (
        "{src}对作业人员资质有什么要求？",
        "根据{basis}，{src}要求作业人员持{tgt}上岗。",
    ),
    "PROHIBITS": (
        "根据法规，{src}禁止哪些行为？",
        "根据{basis}，{src}禁止{tgt}。",
    ),
    "HAS_HAZARD": (
        "{src}存在哪些隐患？",
        "{src}存在{tgt}隐患，依据：{basis}。",
    ),
}


def iter_extraction_files(output_dir: str | Path | None = None) -> Iterable[Path]:
    """遍历抽取结果 JSON 文件。"""
    base = Path(output_dir) if output_dir else settings.EXTRACT_OUTPUT_DIR
    return sorted(base.glob("*.json"))


def load_all(output_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """加载全部抽取结果（跳过损坏文件）。"""
    payloads: list[dict[str, Any]] = []
    for path in iter_extraction_files(output_dir):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                payloads.append(json.load(fp))
        except json.JSONDecodeError as exc:
            logger.warning("跳过损坏文件 %s: %s", path, exc)
    return payloads


def _extract_basis(attributes: dict[str, Any] | None, source: str) -> str:
    """从关系 attributes 中提取条款/依据文本。"""
    attrs = attributes or {}
    for key in ("条款", "依据", "出处", "条款号"):
        if attrs.get(key):
            return str(attrs[key])
    return str(source or "相关法规")


def build_qa_pairs(payloads: list[dict[str, Any]]) -> list[dict[str, str]]:
    """基于关系规则生成去重 QA 对。"""
    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for payload in payloads:
        source = payload.get("source", "未知来源")
        for rel in payload.get("relations") or []:
            template = _QA_TEMPLATES.get(rel.get("relation"))
            if template is None:
                continue
            src = str(rel.get("source") or "").strip()
            tgt = str(rel.get("target") or "").strip()
            if not src or not tgt:
                continue
            basis = _extract_basis(rel.get("attributes"), source)
            question = template[0].format(src=src, tgt=tgt, basis=basis)
            answer = template[1].format(src=src, tgt=tgt, basis=basis)
            key = (question, answer)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"instruction": question, "output": answer})
    return pairs


def main() -> None:
    """生成 train.jsonl 到 datasets/ 目录。"""
    payloads = load_all()
    pairs = build_qa_pairs(payloads)

    datasets_dir = Path(__file__).parent / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    output_path = datasets_dir / "train.jsonl"

    with open(output_path, "w", encoding="utf-8") as fp:
        for pair in pairs:
            fp.write(json.dumps(pair, ensure_ascii=False) + "\n")

    logger.info("生成 %d 条微调 QA 对 → %s", len(pairs), output_path)


if __name__ == "__main__":
    main()
