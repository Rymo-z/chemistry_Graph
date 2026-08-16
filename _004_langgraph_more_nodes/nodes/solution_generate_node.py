"""生成整改方案节点：结合隐患等级、检测结果与检索到的法规依据输出整改措施。"""
from __future__ import annotations

import json
from typing import Any

from _004_langgraph_more_nodes.agent_state import AgentState
from _004_langgraph_more_nodes.nodes.rag_retrieval_node import _retrieve
from common.llm import get_llm
from common.logger import get_logger

logger = get_logger(__name__)

SOLUTION_PROMPT = """你是化工安全工程师，请为以下隐患生成整改方案。
只返回一个 JSON 对象：
{{
  "rectification_measures": "具体整改措施（分条列明，含应急处置与工艺处置）",
  "deadline": "整改期限",
  "responsible": "责任部门/责任人",
  "regulation_basis": "法规依据（引用下方检索证据中相关的法规名称与条款，没有则写'依据检索证据暂无直接条款'）",
  "recheck": "整改验收与复查要求"
}}

【隐患等级】{level}
【隐患描述】{question}
【图像检测】{detections}
【检索到的法规证据】{evidence}
"""


def _retrieve_evidence(query: str) -> list[dict[str, Any]]:
    """检索法规依据，失败返回空列表。"""
    try:
        return _retrieve(query, top_k=3)
    except Exception as exc:  # noqa: BLE001
        logger.warning("整改方案检索法规依据失败: %s", exc)
        return []


def _format_solution(result: dict[str, Any]) -> str:
    """把 LLM 结构化输出渲染为 Markdown。"""
    lines = [
        f"- **整改措施**：{result.get('rectification_measures') or '未生成'}",
        f"- **整改期限**：{result.get('deadline') or '未指定'}",
        f"- **责任部门/人**：{result.get('responsible') or '未指定'}",
        f"- **法规依据**：{result.get('regulation_basis') or '暂无'}",
        f"- **复查要求**：{result.get('recheck') or '未生成'}",
    ]
    return "\n".join(lines)


def solution_generate_node(state: AgentState) -> AgentState:
    """生成整改方案并写回 solution。"""
    question = state.get("question") or ""
    level = state.get("hazard_level") or "一般隐患"
    detections = state.get("yolo_detections") or []

    evidence = _retrieve_evidence(question or "化工安全隐患整改")
    evidence_text = json.dumps(evidence, ensure_ascii=False)[:4000]

    prompt = SOLUTION_PROMPT.format(
        level=level,
        question=question or "（无文字描述）",
        detections=json.dumps(detections, ensure_ascii=False),
        evidence=evidence_text,
    )
    try:
        result = get_llm().chat_json([{"role": "user", "content": prompt}], temperature=0.0)
        solution = _format_solution(result)
    except Exception as exc:  # noqa: BLE001
        logger.error("整改方案生成失败: %s", exc)
        solution = (
            f"- **整改措施**：因服务异常未能生成完整方案，建议现场先隔离危险源并上报安全部门。\n"
            f"- **整改期限**：按隐患等级 {level} 执行\n"
            f"- **责任部门/人**：安全环保部"
        )
    return {"solution": solution}
