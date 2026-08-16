"""作业票智能审核页面。"""
from __future__ import annotations

import streamlit as st

from _006_streamlit.api_client import call_api

OPERATION_TYPES: tuple[str, ...] = (
    "动火作业", "高处作业", "受限空间作业", "吊装作业",
    "临时用电作业", "盲板抽堵作业", "断路作业", "其他",
)


def _collect_form() -> dict[str, str]:
    """从表单收集作业票字段。"""
    return {
        "ticket_no": st.text_input("作业票编号"),
        "operation_type": st.selectbox("作业类型", OPERATION_TYPES),
        "location": st.text_input("作业地点"),
        "start_time": st.text_input("作业开始时间", placeholder="2026-08-06 09:00"),
        "end_time": st.text_input("作业结束时间", placeholder="2026-08-06 17:00"),
        "applicant": st.text_input("申请人"),
        "responsible": st.text_input("作业负责人"),
        "guardian": st.text_input("监护人"),
        "approver": st.text_input("审批人"),
        "risk_identification": st.text_input("风险辨识", placeholder="如：触电、坠落、可燃气体"),
        "safety_measures": st.text_area("安全措施", placeholder="如：气体检测、设置围栏、佩戴防护用品"),
        "gas_test": st.text_input("气体检测记录", placeholder="高风险作业必填，如：氧气20.9% 可燃0%LEL"),
        "special_certificates": st.text_input("特种作业资质", placeholder="如：高处作业证、焊工证"),
    }


def render() -> None:
    st.header("📋 作业票智能审核")
    st.caption("自动校验作业票内容缺项与资质合规性。")

    with st.form("permit_form"):
        st.subheader("作业票信息录入")
        permit_data = _collect_form()
        submitted = st.form_submit_button("🔍 审核作业票", type="primary")

    if submitted:
        with st.spinner("正在审核作业票..."):
            data = call_api(
                "POST",
                "/check_permit",
                json={"permit_data": permit_data, "question": "请审核该作业票的完整性与合规性"},
            )
        if data:
            st.divider()
            passed = data.get("passed")
            st.markdown(
                f"**审核结论：** {'✅ 审核通过' if passed else '❌ 审核不通过'}"
            )

            missing = data.get("missing_fields") or []
            if missing:
                st.warning("**缺失字段：** " + "、".join(str(m) for m in missing))

            issues = data.get("issues") or []
            for issue in issues:
                st.error(issue)

            st.markdown(data.get("answer") or "")
