"""从法规文本抽取实体关系（继承基类）。

示例输入：GB 30871 动火作业安全规范条款 / 应急管理部令等。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from _002_extract_information.extractor_base import BaseExtractor
from common.logger import get_logger

logger = get_logger(__name__)


class RegulationExtractor(BaseExtractor):
    """解析法规/标准条文 → Regulation/Operation/Equipment/Hazard + 各类关系。"""

    @property
    def task_name(self) -> str:
        return "regulation"

    def build_prompt(self, text: str, **kwargs: Any) -> str:
        return (
            "请从以下法规/标准文本中抽取实体与关系，重点识别："
            "法规名称与条款号、涉及的危险作业类型（动火/高处/受限空间/吊装等）、"
            "设备设施、危险物质、场所、所需资质与作业票，"
            "以及明确的要求（需要办理、必须持证、禁止从事等）。\n\n"
            f"【法规文本】\n{text[:12000]}"
        )


def extract_regulation_from_file(file_path: str | Path) -> dict[str, Any]:
    """便捷入口：从文件读取法规原文并抽取。"""
    path = Path(file_path)
    with open(path, "r", encoding="utf-8") as fp:
        content = fp.read()
    return RegulationExtractor().extract(content, source_name=path.stem)
