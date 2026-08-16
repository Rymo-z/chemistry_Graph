"""八大特殊作业数据加载/查询模块。

数据源 `work_permits.json`（依据 GB 30871-2022 全文整理，见
`_001_clawler/data/internal_docs/gb30871_2022_fulltext.txt`）。路径随配置走：
默认 `_001_clawler/data/work_permits.json`，示例模式（USE_SAMPLE_DATA=1）指向
`sample_data/work_permits.json`。供 permit_check_node 做数据驱动的作业票审核，
也可供 QA 检索作业规范依据。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from common.config import settings

_DATA_FILE: Path = settings.CLAWLER_DATA_DIR / "work_permits.json"


@lru_cache(maxsize=1)
def load_work_permits() -> dict[str, Any]:
    """加载并缓存 work_permits.json（缺文件时返回空结构，便于降级）。"""
    if not _DATA_FILE.is_file():
        return {"work_permits": []}
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


def find_work_permit(operation_type: str) -> Optional[dict[str, Any]]:
    """按作业类型名匹配一条作业记录（别名子串匹配，返回首个命中）。

    输入可为完整名（"动火作业"）或别名（"动火"、"受限空间"、"进入受限空间作业"等）。
    匹配不到返回 None。
    """
    if not operation_type:
        return None
    op = operation_type.strip()
    for wp in load_work_permits()["work_permits"]:
        candidates = [wp["work_type"]] + wp.get("aliases", [])
        if any(alias and alias in op for alias in candidates):
            return wp
    return None


def all_work_types() -> list[str]:
    """返回全部作业类型名。"""
    return [wp["work_type"] for wp in load_work_permits()["work_permits"]]


def get_requirements(wp: dict[str, Any]) -> dict[str, Any]:
    """取机器可校验的要求标志（guardian/gas_test/certificate 等）。"""
    return wp.get("requirements", {})


def get_safety_measures(wp: dict[str, Any]) -> list[str]:
    """取安全措施清单。"""
    return wp.get("safety_measures", [])


def get_permit_fields(wp: dict[str, Any]) -> list[str]:
    """取安全作业票字段清单。"""
    return wp.get("permit_fields", [])


def get_approval_flow(wp: dict[str, Any]) -> dict[str, Any]:
    """取审批流程（含分级审批人）。"""
    return wp.get("approval_flow", {})
