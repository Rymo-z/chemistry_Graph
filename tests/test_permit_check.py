"""permit_check_node.py + permit_data.py 离线单元测试（不发网络请求）。

覆盖：work_permits 数据加载、作业类型别名匹配、数据驱动的监护人/气体检测/
资质校验、特级动火影像提示、未匹配类型回退、时间合法性。
"""
from __future__ import annotations

from _004_langgraph_more_nodes.nodes.permit_check_node import permit_check_node
from _004_langgraph_more_nodes.permit_data import (
    all_work_types,
    find_work_permit,
    load_work_permits,
)

# 一份"基本齐全"的作业票（缺 operation_type，按用例补）
BASE = {
    "ticket_no": "T-001",
    "location": "反应釜区",
    "start_time": "2026-08-15 09:00",
    "end_time": "2026-08-15 11:00",
    "applicant": "张工",
    "responsible": "李工",
    "approver": "王主任",
    "risk_identification": "有易燃易爆介质",
    "safety_measures": ["已隔离"],
}


def _check(operation_type: str, **extra) -> dict:
    return permit_check_node(
        {"permit_data": {**BASE, "operation_type": operation_type, **extra}}
    )["permit_result"]


# ---------- permit_data：加载与匹配 ----------

def test_work_permits_has_8_types():
    """GB 30871 八大特殊作业齐全。"""
    types = all_work_types()
    assert len(types) == 8
    for t in ("动火作业", "受限空间作业", "盲板抽堵作业", "高处作业",
              "吊装作业", "临时用电作业", "动土作业", "断路作业"):
        assert t in types


def test_find_work_permit_by_alias():
    """按别名子串匹配（完整名 / 简称 / 组合名）。"""
    assert find_work_permit("动火作业")["work_type"] == "动火作业"
    assert find_work_permit("动火")["work_type"] == "动火作业"
    assert find_work_permit("一级动火作业")["work_type"] == "动火作业"
    assert find_work_permit("进入受限空间作业")["work_type"] == "受限空间作业"
    assert find_work_permit("登高作业")["work_type"] == "高处作业"
    assert find_work_permit("完全无关的类型") is None


# ---------- permit_check_node：数据驱动校验 ----------

def test_hot_work_missing_guardian_gas_certificate():
    """动火作业缺监护人/气体检测/资质 → 类型专属问题。"""
    pr = _check("动火作业")
    assert not pr["passed"]
    assert pr["permit_info"]["work_type"] == "动火作业"
    joined = "；".join(pr["issues"])
    assert "监护人" in joined and "气体检测" in joined and "资质证书" in joined


def test_hot_work_complete_passes():
    """动火作业要件齐全 → 通过。"""
    pr = _check(
        "动火作业",
        guardian="赵监护",
        gas_test={"O2": "20.8%", "可燃": "0.1%"},
        special_certificates=["电焊操作证"],
    )
    assert pr["passed"] and not pr["missing_fields"] and not pr["issues"]


def test_confined_space_requires_gas_test():
    """受限空间无气体检测 → 明确拦截。"""
    pr = _check("进入受限空间作业", guardian="赵监护", special_certificates=["受限空间作业证"])
    assert any("气体检测" in issue for issue in pr["issues"])


def test_lifting_requires_guardian_and_certificate():
    """吊装作业：监护人 + 起重资质均为强制。"""
    pr = _check("吊装作业")
    joined = "；".join(pr["issues"])
    assert "监护人" in joined and "资质证书" in joined


def test_special_hot_work_video_note():
    """特级动火 → 全过程影像提示。"""
    pr = _check(
        "特级动火作业",
        guardian="赵监护",
        gas_test={"O2": "20.8%"},
        special_certificates=["电焊操作证"],
    )
    assert pr["passed"]
    assert any("影像" in note for note in pr.get("notes", []))


def test_unmatched_type_falls_back():
    """未匹配到数据的类型（检维修）回退内置高风险检查。"""
    pr = _check("检维修作业")
    assert not pr["passed"]
    joined = "；".join(pr["issues"])
    assert "监护人" in joined and "气体检测" in joined


def test_end_before_start_detected():
    """结束时间早于开始时间 → 报错。"""
    pr = _check("动火作业", start_time="2026-08-15 11:00", end_time="2026-08-15 09:00")
    assert any("早于开始时间" in issue for issue in pr["issues"])


def test_missing_common_fields_reported():
    """通用必填字段缺失逐项报告。"""
    pr = permit_check_node({"permit_data": {"operation_type": "动火作业"}})["permit_result"]
    assert not pr["passed"]
    assert "作业票编号" in pr["missing_fields"]
    assert "作业地点" in pr["missing_fields"]
    assert "监护人" in pr["missing_fields"]
