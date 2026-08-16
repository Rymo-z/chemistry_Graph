"""法规制度问答页面（流式打字机输出）。"""
from __future__ import annotations

import streamlit as st

from _006_streamlit.api_client import stream_chat

SUGGESTIONS: list[str] = [
    "登高作业需要办理什么手续？",
    "动火作业必须配备哪些安全措施？",
    "受限空间作业前需要做哪些气体检测？",
    "压力容器多久检验一次？",
    "化工储罐区有哪些安全规定？",
]


def render() -> None:
    st.header("💬 法规制度问答")
    st.caption("基于知识图谱 + 向量检索，秒级返回法规制度依据。")

    # 快捷提问
    st.markdown("**试试这些问题：**")
    columns = st.columns(len(SUGGESTIONS))
    for col, suggestion in zip(columns, SUGGESTIONS):
        if col.button(suggestion, use_container_width=True):
            st.session_state["chat_question"] = suggestion

    default_question = st.session_state.get("chat_question", "")
    question = st.text_input(
        "输入你的问题",
        value=default_question,
        placeholder="例如：登高作业需要办理什么手续？",
    )

    if st.button("🔍 提问", type="primary") and question.strip():
        answer, sources, intent = "", [], None
        box = st.empty()
        with st.status("正在准备…", expanded=True) as status:
            for event in stream_chat(question.strip()):
                event_type = event.get("type")
                if event_type == "progress":
                    status.update(label=event.get("message", "处理中…"))
                elif event_type == "token":
                    answer += event.get("content", "")
                    box.markdown(answer)  # 打字机逐字渲染
                elif event_type == "done":
                    status.update(label="✅ 完成", state="complete")
                    if not answer:  # 非 QA 意图无 token，用完整 output 兜底
                        answer = event.get("output") or "（无回答）"
                        box.markdown(answer)
                    sources = event.get("sources") or []
                    metadata = event.get("metadata") or {}
                    intent = metadata.get("intent") or event.get("intent")
                elif event_type == "error":
                    status.update(label="❌ 处理失败", state="error")
                    box.markdown(event.get("message", "处理失败"))
        if sources:
            st.divider()
            st.markdown("**📌 参考来源：** " + "；".join(str(s) for s in sources))
        if intent:
            st.caption(f"识别意图：{intent}")
        st.session_state.pop("chat_question", None)
