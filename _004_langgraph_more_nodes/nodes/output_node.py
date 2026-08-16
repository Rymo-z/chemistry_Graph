"""统一输出节点：按意图与可用证据组装 Markdown 回答，并记录来源。

QA 路径：优先用图查询结果，其次向量检索结果，经 LLM 合成通俗答案；
HAZARD/PERMIT 路径：直接渲染定级 / 方案 / 审核结论。
"""
from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer

from common.config import settings
from common.llm import get_llm
from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

# 证据行数封顶：图查询可能返回上千行（match-all 型），超限截断避免证据爆炸
MAX_EVIDENCE_LINES = 30


def _format_graph_row(row: dict[str, Any]) -> str:
    """图查询结果行 → 可读文本。"""
    if "name" in row and "type" in row:
        return f"[{row.get('type')}] {row.get('name')}"
    return "、".join(f"{k}={v}" for k, v in row.items() if v not in (None, "", []))


def _format_rag_item(item: dict[str, Any]) -> str:
    """RAG 命中项 → 可读文本（优先富证据：节点文本 + 1 跳邻居）。"""
    evidence = item.get("evidence_text")
    if evidence:
        return evidence
    node = item.get("node") or {}
    score = item.get("score")
    name = node.get("name") or "未知"
    etype = node.get("type") or ""
    score_text = f"（相似度 {score}）" if score is not None else ""
    return f"[{etype}] {name} {score_text}".strip()


def _synthesize_qa_answer(
    question: str,
    evidence_lines: list[str],
) -> str:
    """基于检索证据用 LLM 合成通俗答案；LLM 失败时返回证据原文。"""
    llm = get_llm()
    prompt = (
        "你是化工安全生产合规助手。请基于以下检索到的法规/知识，用通俗、准确的中文回答工人提问。\n"
        "要求：必须引用检索证据中的法规名称或条款编号，严禁编造证据中不存在的依据。\n\n"
        f"【工人提问】{question}\n"
        f"【检索到的证据】\n{chr(10).join(evidence_lines)[:8000]}\n\n"
        "请直接给出回答。"
    )
    try:
        return llm.complete(prompt, temperature=0.2, max_tokens=1200)
    except Exception as exc:  # noqa: BLE001
        logger.warning("QA 答案合成失败，降级为证据原文: %s", exc)
        return "\n".join(evidence_lines)[:4000] or "未检索到相关内容。"


def _stream_qa_answer(
    question: str,
    evidence_lines: list[str],
    writer: Any,
) -> str:
    """流式合成 QA 答案：逐增量写入 writer，返回拼接文本。"""
    llm = get_llm()
    prompt = (
        "你是化工安全生产合规助手。请基于以下检索到的法规/知识，用通俗、准确的中文回答工人提问。\n"
        "要求：必须引用检索证据中的法规名称或条款编号，严禁编造证据中不存在的依据。\n\n"
        f"【工人提问】{question}\n"
        f"【检索到的证据】\n{chr(10).join(evidence_lines)[:8000]}\n\n"
        "请直接给出回答。"
    )
    buf: list[str] = []
    try:
        for delta in llm.complete_stream(prompt, temperature=0.2, max_tokens=1200):
            if delta:
                writer({"type": "token", "content": delta})
                buf.append(delta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("QA 流式答案生成失败，回退为证据原文: %s", exc)
        fallback = "\n".join(evidence_lines)[:4000] or "未检索到相关内容。"
        writer({"type": "token", "content": fallback})
        return fallback
    return "".join(buf)


def output_node(state: AgentState) -> AgentState:
    """汇总并写回 output / sources / metadata。

    流式模式（`state["stream"]` 为真且为 QA 意图）下，把「标题前缀 →
    LLM 答案增量 → 来源」依次写入 stream writer，由 /chat/stream
    通过 `stream_mode="custom"` 转成 SSE 的 token 事件。
    """
    intent = state.get("intent") or "qa"
    graph_result = state.get("graph_result") or []
    rag_results = state.get("rag_results") or []

    # 流式开关：仅 QA 意图 + /chat/stream 注入 stream=True 时启用；
    # 非流式调用下 get_stream_writer() 返回 None，自动走原路径。
    stream_writer = None
    if intent == "qa" and state.get("stream"):
        stream_writer = get_stream_writer()

    sources: list[str] = []
    evidence_lines: list[str] = []
    for row in graph_result:
        text = _format_graph_row(row)
        evidence_lines.append(text)
        if row.get("name"):
            sources.append(str(row["name"]))
    for item in rag_results:
        text = _format_rag_item(item)
        evidence_lines.append(text)
        node = item.get("node") or {}
        if node.get("name"):
            sources.append(str(node["name"]))

    # 证据封顶：图查询可能返回上千行，超出部分只统计来源、不再进合成提示词
    if len(evidence_lines) > MAX_EVIDENCE_LINES:
        evidence_lines = evidence_lines[:MAX_EVIDENCE_LINES]
        evidence_lines.append(f"……（证据较多，已截取前 {MAX_EVIDENCE_LINES} 条）")

    sections: list[str] = [f"## 🏭 {settings.APP_NAME}"]

    if intent == "hazard":
        sections.append(f"### ⚠️ 隐患定级：{state.get('hazard_level') or '待评估'}")
        reason = state.get("hazard_reason")
        if reason:
            sections.append(f"**定级依据**：{reason}")
        detections = state.get("yolo_detections") or []
        if detections:
            sections.append("**CV 检测目标：**")
            for det in detections:
                sections.append(
                    f"- `{det.get('label')}` 置信度 {det.get('confidence', '-')}"
                )
        if state.get("solution"):
            sections.append("### 🛠️ 整改方案")
            sections.append(state["solution"])

    elif intent == "permit":
        result = state.get("permit_result") or {}
        passed = bool(result.get("passed"))
        sections.append(f"### 📋 作业票审核结论：{'✅ 通过' if passed else '❌ 不通过'}")
        missing = result.get("missing_fields") or []
        issues = result.get("issues") or []
        if missing:
            sections.append("**缺失字段：** " + "、".join(str(m) for m in missing))
        if issues:
            sections.append("**存在问题：**")
            sections.extend(f"- {issue}" for issue in issues)
        if result.get("summary"):
            sections.append(result["summary"])

    else:  # qa
        if evidence_lines:
            sections.append("### 📖 解答")
            if stream_writer is not None:
                # 前缀（标题 + 解答小节）一次性写入，随后流式答案
                stream_writer({"type": "token", "content": "\n\n".join(sections) + "\n\n"})
                body = _stream_qa_answer(state.get("question") or "", evidence_lines, stream_writer)
                sections.append(body)
            else:
                sections.append(_synthesize_qa_answer(state.get("question") or "", evidence_lines))
        else:
            sections.append(
                "未检索到直接相关的法规条目。\n"
                "💡 建议：补充更具体的关键词（如作业类型、设备名称、物质名称）后重试，"
                "或先确认知识库已构建（Neo4j 入库 + FAISS 索引）。"
            )

    unique_sources = list(dict.fromkeys(s for s in sources if s))
    if unique_sources:
        sources_section = "\n---\n📌 **参考来源**：" + "；".join(unique_sources)
        sections.append(sources_section)
        if stream_writer is not None:
            stream_writer({"type": "token", "content": sources_section})

    return {
        "output": "\n\n".join(sections),
        "sources": unique_sources,
        "metadata": {
            "intent": intent,
            "graph_hits": len(graph_result),
            "vector_hits": len(rag_results),
        },
    }
