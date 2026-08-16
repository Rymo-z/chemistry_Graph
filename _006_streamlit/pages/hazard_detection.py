"""隐患识别页面（图片上传 + 结果展示）。"""
from __future__ import annotations

import streamlit as st

from _006_streamlit.api_client import call_api

ALLOWED_TYPES: tuple[str, ...] = ("jpg", "jpeg", "png", "bmp", "webp")


def render() -> None:
    st.header("📷 拍照识隐患")
    st.caption("上传现场设备照片，AI 识别隐患类型、匹配法规依据、生成整改方案。")

    uploaded = st.file_uploader(
        "上传设备/现场照片",
        type=list(ALLOWED_TYPES),
        help="支持 jpg / png / bmp / webp",
    )
    note = st.text_input(
        "补充描述（可选）",
        placeholder="例如：反应釜顶部法兰有轻微泄漏",
    )

    if uploaded is not None and st.button("🔬 开始识别", type="primary"):
        files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}
        data_form = {"question": note} if note.strip() else None
        with st.spinner("正在识别隐患并生成整改方案..."):
            data = call_api("POST", "/detect_hazard", files=files, data=data_form)

        if data:
            st.image(uploaded, caption="上传图片", width=360)
            st.divider()

            level = data.get("hazard_level")
            if level:
                st.markdown(f"**隐患等级：** `{level}`")

            detections = data.get("detections") or []
            if detections:
                st.markdown("**CV 检测到：**")
                for det in detections:
                    st.markdown(
                        f"- `{det.get('label')}` 置信度 {det.get('confidence', '-')}"
                    )
            st.divider()
            st.markdown(data.get("answer") or "（无结果）")

            sources = data.get("sources") or []
            if sources:
                st.divider()
                st.markdown("**📌 依据来源：** " + "；".join(str(s) for s in sources))
