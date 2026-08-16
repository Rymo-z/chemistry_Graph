"""从隐患描述抽取实体（继承基类）。

示例输入：巡检发现的隐患记录、整改通知单中的隐患描述等。
"""
from __future__ import annotations

from typing import Any

from _002_extract_information.extractor_base import BaseExtractor


class HazardExtractor(BaseExtractor):
    """解析隐患描述 → Hazard/Equipment/Location + HAS_HAZARD/LOCATED_IN 等关系。"""

    @property
    def task_name(self) -> str:
        return "hazard"

    def build_prompt(self, text: str, **kwargs: Any) -> str:
        return (
            "请从以下隐患描述/整改记录中抽取实体与关系，重点识别："
            "隐患类型、涉及设备设施、所在场所、可能的后果、整改要求与责任部门。"
            "隐患实体建议加入 attributes：{severity: 重大/一般, status: 待整改/已整改}。\n\n"
            f"【隐患描述】\n{text[:8000]}"
        )
