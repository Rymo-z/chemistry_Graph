"""Streamlit 主程序（侧边栏导航）。

启动：
    streamlit run _006_streamlit/app.py
"""
from __future__ import annotations

import streamlit as st

from _006_streamlit.api_client import API_BASE


def main() -> None:
    st.set_page_config(
        page_title="化工安全生产合规智能体",
        page_icon="🏭",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    with st.sidebar:
        st.title("🏭 化工安全合规智能体")
        st.caption("面向一线工人的 7×24 安全生产辅助")
        st.divider()
        choice = st.radio(
            "功能导航",
            ["💬 法规制度问答", "📷 拍照识隐患", "📋 作业票智能审核"],
        )
        st.divider()
        st.markdown(f"后端地址：`{API_BASE}`")
        st.caption("数据不出厂 · 可离线部署")

    # 按导航加载对应页面（延迟导入，避免冷启动加载全部依赖）
    if choice == "💬 法规制度问答":
        from _006_streamlit.pages import chat

        chat.render()
    elif choice == "📷 拍照识隐患":
        from _006_streamlit.pages import hazard_detection

        hazard_detection.render()
    else:
        from _006_streamlit.pages import permit_check

        permit_check.render()


if __name__ == "__main__":
    main()
