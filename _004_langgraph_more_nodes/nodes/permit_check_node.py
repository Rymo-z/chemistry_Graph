"""作业票审核节点：基于 GB 30871-2022 数据驱动校验内容缺项与资质合规性。

规则来源 `_001_clawler/data/work_permits.json`（八大特殊作业），由
permit_data 加载；按作业类型匹配后按该类型的专属要求校验：
- 通用必填字段缺失检查；
- 类型专属要求（监护人 / 气体检测 / 特种作业资质 / 特级动火影像等）；
- 匹配不到类型时回退到内置的高风险作业（动火/受限空间/盲板/检维修）检查。
"""
from __future__ import annotations

from typing import Any, Optional

from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState
from _004_langgraph_more_nodes.permit_data import (
    find_work_permit,
    get_approval_flow,
    get_permit_fields,
    get_requirements,
    get_safety_measures,
)

logger = get_logger(__name__)

# 通用必填字段：字段名 -> 中文标签
BASE_REQUIRED_FIELDS: dict[str, str] = {
    "ticket_no": "作业票编号",
    "operation_type": "作业类型",
    "location": "作业地点",
    "start_time": "作业开始时间",
    "end_time": "作业结束时间",
    "applicant": "申请人",
    "responsible": "作业负责人",
    "guardian": "监护人",
    "approver": "审批人",
    "risk_identification": "风险辨识",
    "safety_measures": "安全措施",
}
# 特种作业资质字段
CERTIFICATES_FIELD = "special_certificates"

# 数据未覆盖时回退的高风险作业（与 GB 30871 高风险作业一致）
_HIGH_RISK_OPERATIONS: tuple[str, ...] = ("动火", "受限空间", "盲板", "检维修")


def _is_empty(value: Any) -> bool:
    """判断字段是否为空（None / 空串 / 空列表 / 空字典）。"""
    return value is None or value == "" or value == [] or value == {}


def _build_permit_info(wp: Optional[dict], operation_type: str) -> Optional[dict[str, Any]]:
    """汇总匹配到的作业票规范，供前端展示依据（未匹配返回 None）。"""
    if not wp:
        return None
    return {
        "work_type": wp["work_type"],
        "definition": wp["definition"],
        "grading": wp.get("grading", {}),
        "permit_validity": wp.get("permit_validity", ""),
        "permit_fields": get_permit_fields(wp),
        "approval_flow": get_approval_flow(wp),
        "safety_measures": get_safety_measures(wp),
        "requirements": get_requirements(wp),
        "source_std": wp.get("source_std", ""),
        "matched_operation": operation_type,
    }


def permit_check_node(state: AgentState) -> AgentState:
    """审核并写回 permit_result。"""
    data = state.get("permit_data") or {}
    operation_type = str(data.get("operation_type") or "")
    wp = find_work_permit(operation_type)

    # 1) 通用缺项检查
    missing_fields: list[str] = [
        label for key, label in BASE_REQUIRED_FIELDS.items() if _is_empty(data.get(key))
    ]

    # 2) 类型专属合规检查（数据驱动）
    issues: list[str] = []
    notes: list[str] = []
    if wp is not None:
        req = get_requirements(wp)
        work_type = wp["work_type"]
        if req.get("guardian_required") and _is_empty(data.get("guardian")):
            issues.append(f"{work_type}必须有现场监护人（GB 30871-2022）")
        if req.get("gas_test_required") and _is_empty(data.get("gas_test")):
            issues.append(f"{work_type}需提供气体检测记录（gas_test）")
        if req.get("certificate_required") and _is_empty(data.get(CERTIFICATES_FIELD)):
            issues.append(f"{work_type}需提供特种作业人员资质证书（{CERTIFICATES_FIELD}）")
        # 特级动火专属：全过程影像
        if wp.get("work_type_key") == "hot_work" and "特级" in operation_type:
            notes.append("特级动火应采集全过程作业影像（防爆摄录设备）")
    else:
        # 未匹配到数据：回退内置高风险逻辑，避免回归
        if any(op in operation_type for op in _HIGH_RISK_OPERATIONS):
            if _is_empty(data.get("guardian")):
                issues.append("高风险作业必须明确现场监护人")
            if _is_empty(data.get("gas_test")):
                issues.append("动火/受限空间/盲板作业需提供气体检测记录（gas_test）")
        if _is_empty(data.get(CERTIFICATES_FIELD)):
            issues.append("未填写特种作业人员资质证书")

    # 3) 时间合法性（粗校验）
    start, end = data.get("start_time"), data.get("end_time")
    if start and end and str(start) > str(end):
        issues.append("作业结束时间早于开始时间")

    passed = not missing_fields and not issues
    summary = (
        "审核通过，各项要件齐全，可正常作业。"
        if passed
        else f"共发现 {len(missing_fields)} 项缺失字段、{len(issues)} 项合规问题，请整改后重新提交。"
    )
    if notes:
        summary += " 提示：" + "；".join(notes)

    logger.info(
        "作业票审核：%s（%s），缺失=%d 问题=%d",
        "通过" if passed else "不通过",
        wp["work_type"] if wp else operation_type or "未知类型",
        len(missing_fields), len(issues),
    )
    return {
        "permit_result": {
            "passed": passed,
            "missing_fields": missing_fields,
            "issues": issues,
            "summary": summary,
            "notes": notes,
            "data": data,
            "permit_info": _build_permit_info(wp, operation_type),
        }
    }
