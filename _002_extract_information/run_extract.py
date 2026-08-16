"""批量抽取入口：读取 _001_clawler 整合数据，逐条抽取实体关系落盘。

用法：
    python -m _002_extract_information.run_extract --limit 5          # 试跑 5 条验证链路
    python -m _002_extract_information.run_extract --source govlaws   # 只抽某数据源
    python -m _002_extract_information.run_extract --force            # 忽略已存在，强制重抽
    python -m _002_extract_information.run_extract --workers 8        # 并发数（默认 4）
    python -m _002_extract_information.run_extract                    # 全量（断点续跑）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from _002_extract_information.extract_accident import AccidentExtractor
from _002_extract_information.extract_regulation import RegulationExtractor
from _002_extract_information.extractor_base import BaseExtractor
from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

# 与各 extractor build_prompt 内部截断保持一致（超出部分不进提示词）
MAX_INPUT_CHARS = 12000
# 超过该长度启用分块抽取（避免单次输出超 token 上限被截断）
CHUNK_THRESHOLD = 8000
# 分块不宜过大：超大单块会让模型输出过度展开，即使提高 max_tokens 也仍被截断
CHUNK_LEN = 2500


def _safe_ident(title: str, task: str) -> str:
    """由标题生成稳定、安全的文件名标识（截断 + 短哈希防重）。

    同一标题始终得到同一文件名，重跑即覆盖 → 批量抽取幂等。
    """
    clean = "".join(c for c in title if c.isalnum() or c in "-_")[:40].strip("-_") or "doc"
    digest = hashlib.md5(title.encode("utf-8")).hexdigest()[:8]
    return f"{task}_{clean}_{digest}"


def _extractor_for(task: str, cache: dict[str, BaseExtractor]) -> BaseExtractor:
    if task not in cache:
        cache[task] = RegulationExtractor() if task == "regulation" else AccidentExtractor()
    return cache[task]


def _load_records() -> list[dict[str, Any]]:
    data_path = settings.CLAWLER_DATA_DIR / "all_records.jsonl"
    if not data_path.exists():
        raise FileNotFoundError(f"缺少整合数据: {data_path}，请先运行 _001_clawler.organize_data")
    with open(data_path, encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def _task_for(source: str) -> Optional[str]:
    if source in ("govlaws", "regulations"):
        return "regulation"
    if source == "accidents":
        return "accident"
    return None


def _extract_one(rec: dict[str, Any], task: str, out_path: Path) -> tuple[str, int, int]:
    """抽取单条，返回 (标题, 实体数, 关系数)。

    超长文本走 extract_chunked 分块抽取 + 合并，随后由本函数落盘。
    """
    title = rec.get("title", "") or "doc"
    content = (rec.get("content") or "")[:MAX_INPUT_CHARS]
    extractor = _extractor_for(task, _EXTRACTOR_CACHE)
    if len(content) <= CHUNK_THRESHOLD:
        result = extractor.extract(content, source_name=title, output_path=out_path)
    else:
        result = extractor.extract_chunked(
            content, source_name=title, chunk_len=CHUNK_LEN
        )
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("分块结果已落盘 → %s", out_path.name)
    return title, len(result.get("entities", [])), len(result.get("relations", []))


# 进程级缓存：每类任务复用一个 extractor（内部 LLMClient 为线程安全单例）
_EXTRACTOR_CACHE: dict[str, BaseExtractor] = {}


def main() -> int:
    parser = argparse.ArgumentParser(description="从 _001_clawler 整合数据批量抽取实体关系")
    parser.add_argument("--limit", type=int, default=0, help="最多抽取条数（0=全部）")
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 条")
    parser.add_argument("--source", choices=["govlaws", "regulations", "accidents"], help="只抽某数据源")
    parser.add_argument("--force", action="store_true", help="忽略已存在文件，强制重抽")
    parser.add_argument("--workers", type=int, default=4, help="并发请求数（默认 4）")
    args = parser.parse_args()

    records = _load_records()
    if args.source:
        records = [r for r in records if r["source"] == args.source]
    records = records[args.offset :]
    if args.limit:
        records = records[: args.limit]

    # 预过滤：已产出文件（非 force）直接跳过，实现断点续跑
    todo: list[tuple[dict[str, Any], str, Path]] = []
    skip = 0
    for rec in records:
        task = _task_for(rec.get("source", ""))
        if task is None:
            continue
        title = rec.get("title", "") or "doc"
        out_path = settings.EXTRACT_OUTPUT_DIR / f"{_safe_ident(title, task)}.json"
        if out_path.exists() and not args.force:
            skip += 1
            continue
        todo.append((rec, task, out_path))

    logger.info("批量抽取：总数=%d 待抽=%d 已存在跳过=%d（workers=%d）", len(records), len(todo), skip, args.workers)
    if not todo:
        logger.info("没有需要抽取的记录。")
        return 0

    done = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures: dict[Any, str] = {}
        for rec, task, out_path in todo:
            # 在循环内取标题，避免推导式作用域漏绑导致日志标题错乱
            title = rec.get("title", "") or "doc"
            futures[pool.submit(_extract_one, rec, task, out_path)] = title
        for future in as_completed(futures):
            title = futures[future]
            try:
                _, ne, nr = future.result()
                done += 1
                logger.info("完成 %s：实体=%d 关系=%d", title[:30], ne, nr)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.error("抽取失败 %s: %s", title[:30], exc)

    logger.info("批量抽取结束：成功=%d 失败=%d（累计跳过=%d）", done, failed, skip)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
