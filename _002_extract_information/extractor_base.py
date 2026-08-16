"""抽取基类：封装 LLM 调用、JSON 解析、结果保存。

子类需实现 `task_name` 与 `build_prompt()`，调用 `extract()` 即完成
「文本 → 结构化实体关系 JSON」的完整链路，结果自动落盘到 output/。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from _002_extract_information.schema import ENTITY_TYPE_VALUES, RELATION_TYPE_VALUES
from common.config import settings
from common.llm import LLMClient
from common.logger import get_logger

logger = get_logger(__name__)

EXTRACT_SYSTEM_PROMPT = """你是一名化工安全生产领域的知识工程专家。请从给定的文本中抽取实体与关系，并严格按 JSON 返回（不要输出 markdown 代码块）。

输出格式：
{{
  "source": "文本标题",
  "entities": [
    {{"type": "<EntityType>", "name": "实体名", "aliases": ["同义词"], "attributes": {{"关键属性": "值"}}}}
  ],
  "relations": [
    {{"source": "实体名A", "relation": "<RelationType>", "target": "实体名B", "attributes": {{"条款/依据": "..."}}}}
  ]
}}

硬性要求：
1. type 只能是以下枚举值之一：{entity_types}
2. relation 只能是以下枚举值之一：{relation_types}
3. entities 与 relations 中引用的实体名必须保持一致（同名才可关联）。
4. 抽取不到的字段留空，严禁编造文本中不存在的内容。
5. 控制输出规模：每文档实体不超过 80 个、关系不超过 150 条，优先保留
   化工安全生产合规最核心的内容（法规条款/作业/设备/物质/隐患/资质/事故）。
"""

# 分块抽取时追加的收窄约束：避免模型对单个分块过度展开，把输出撑爆 token 上限被截断。
COMPACT_SUFFIX = (
    "6. 输出必须精简：当前输入是一个长文档的其中一个分块，实体不超过 20 个、"
    "关系不超过 30 条，attributes 只保留 1-2 个最关键的值，严禁逐条罗列全文条款。"
)


class BaseExtractor(ABC):
    """从文本抽取实体关系的基类。"""

    def __init__(self) -> None:
        self.llm: LLMClient = LLMClient()
        self.output_dir: Path = settings.EXTRACT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 抽象接口
    # ------------------------------------------------------------------
    @property
    @abstractmethod
    def task_name(self) -> str:
        """任务标识（用于输出文件名与日志），如 'regulation' / 'hazard' / 'accident'。"""

    @abstractmethod
    def build_prompt(self, text: str, **kwargs: Any) -> str:
        """根据文本构造抽取提示词。"""

    # ------------------------------------------------------------------
    # 公共实现
    # ------------------------------------------------------------------
    @property
    def system_prompt(self) -> str:
        return EXTRACT_SYSTEM_PROMPT.format(
            entity_types="、".join(ENTITY_TYPE_VALUES),
            relation_types="、".join(RELATION_TYPE_VALUES),
        )

    def extract(
        self,
        text: str,
        *,
        source_name: str | None = None,
        max_tokens: int = 8000,
        output_path: Path | None = None,
        save_result: bool = True,
        compact: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """执行抽取并保存 JSON，返回抽取结果。

        Args:
            text: 输入文本（由子类 build_prompt 决定如何注入）。
            source_name: 记录来源标题（写入结果 source 字段）。
            max_tokens: 生成 token 上限（抽取长文本可调大）。
            output_path: 指定输出路径；None 时自动生成时间戳文件名。
                批量抽取传入确定性路径可实现幂等（重跑覆盖，不产生重复文件）。
            save_result: False 时只返回结果不落盘（供分块合并等内存使用）。
            compact: True 时追加精简约束，收窄单次输出规模（分块抽取用）。
        """
        logger.info(
            "[%s] 开始抽取，输入长度=%d", self.task_name, len(text or "")
        )
        prompt = self.build_prompt(text, **kwargs)
        system = self.system_prompt + ("\n" + COMPACT_SUFFIX if compact else "")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        try:
            data = self.llm.chat_json(messages, temperature=0.0, max_tokens=max_tokens)
        except (ValueError, json.JSONDecodeError):
            # 输出超限被截断导致解析失败：追加精简约束 + 更高上限重试一次，
            # 宁可少抽保证结果可用，不因个别文档的过度展开整篇失败。
            logger.warning("[%s] 首次抽取解析失败，追加精简约束重试", self.task_name)
            retry_system = system + ("\n" + COMPACT_SUFFIX if not compact else "")
            retry_tokens = max(max_tokens * 2, 12000)
            data = self.llm.chat_json(
                [{"role": "system", "content": retry_system}, {"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=retry_tokens,
            )
        data.setdefault("source", source_name or "unknown")
        saved_path = None
        if save_result:
            saved_path = self.save(data, path=output_path)
        logger.info(
            "[%s] 抽取完成：实体=%d 关系=%d → %s",
            self.task_name,
            len(data.get("entities", [])),
            len(data.get("relations", [])),
            saved_path,
        )
        return data

    def extract_chunked(
        self,
        text: str,
        *,
        source_name: str | None = None,
        chunk_len: int = 2500,
        max_tokens: int = 12000,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """超长文本分块抽取并合并结果（避免单次输出超 token 上限被截断）。

        分块更小 + 强制精简约束 + 更高生成上限，保证单块输出在 token 内完成；
        单块失败只跳过该块（记警告），不影响整篇结果。各块独立抽取，
        实体按 (type, name)、关系按 (source, relation, target) 去重后合并；
        只返回合并结果，不落盘（由调用方保存）。
        """
        chunks = [text[i : i + chunk_len] for i in range(0, len(text), chunk_len)]
        if len(chunks) <= 1:
            return self.extract(
                text, source_name=source_name, save_result=False,
                max_tokens=max_tokens, compact=True, **kwargs,
            )

        merged: dict[str, Any] = {
            "source": source_name or self.task_name,
            "entities": [],
            "relations": [],
        }
        seen_e: set[tuple[Any, Any]] = set()
        seen_r: set[tuple[Any, Any, Any]] = set()
        failed_chunks = 0
        for i, chunk in enumerate(chunks):
            try:
                data = self.extract(
                    chunk, source_name=f"{source_name}#{i + 1}", save_result=False,
                    max_tokens=max_tokens, compact=True, **kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                failed_chunks += 1
                logger.warning(
                    "[%s] 分块 %d/%d 抽取失败，跳过该块: %s",
                    self.task_name, i + 1, len(chunks), str(exc)[:120],
                )
                continue
            for e in data.get("entities") or []:
                key = (e.get("type"), e.get("name"))
                if key not in seen_e:
                    seen_e.add(key)
                    merged["entities"].append(e)
            for r in data.get("relations") or []:
                key = (r.get("source"), r.get("relation"), r.get("target"))
                if key not in seen_r:
                    seen_r.add(key)
                    merged["relations"].append(r)
        logger.info(
            "[%s] 分块合并完成：%d 块（失败 %d）→ 实体=%d 关系=%d",
            self.task_name, len(chunks), failed_chunks,
            len(merged["entities"]), len(merged["relations"]),
        )
        return merged

    def save(self, data: dict[str, Any], *, path: Path | None = None) -> Path:
        """抽取结果落盘。

        Args:
            data: 抽取结果字典。
            path: 指定输出路径；None 时用默认规则 output/{task}_{source}_{timestamp}.json。
        """
        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_source = "".join(
                c for c in str(data.get("source") or "doc") if c.isalnum() or c in "-_"
            )[:40]
            path = self.output_dir / f"{self.task_name}_{safe_source}_{timestamp}.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        return path

    def extract_batch(
        self, texts: list[str], **kwargs: Any
    ) -> list[dict[str, Any]]:
        """批量抽取入口（逐条调用 extract）。"""
        return [self.extract(text, **kwargs) for text in texts]
