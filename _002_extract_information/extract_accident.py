"""从事故报告抽取实体（继承基类）。

示例输入：公开的事故调查报告全文。
"""
from __future__ import annotations

from typing import Any

from _002_extract_information.extractor_base import BaseExtractor


class AccidentExtractor(BaseExtractor):
    """解析事故报告 → Accident/Equipment/Operation/Material + CAUSED_BY/RESULTS_IN/MENTIONS 等。"""

    @property
    def task_name(self) -> str:
        return "accident"

    def build_prompt(self, text: str, **kwargs: Any) -> str:
        return (
            "请从以下事故报告中抽取实体与关系，重点识别："
            "事故名称、事故发生的时间地点、涉事设备设施、危险物质、"
            "事故类型与直接/间接原因、暴露出的违规行为，"
            "并补充 attributes：{date: 事发日期, casualties: 伤亡情况, cause: 原因}。\n\n"
            f"【事故报告】\n{text[:12000]}"
        )
