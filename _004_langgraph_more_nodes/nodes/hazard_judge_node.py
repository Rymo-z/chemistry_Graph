"""隐患定级节点：结合文字描述与 CV 检测结果判定隐患等级（重大/一般）。

依据：参照化工行业重大/一般隐患判定原则，LLM 判定为主，规则关键词兜底。
"""
from __future__ import annotations

import json
from typing import Any

from common.llm import get_llm
from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

# 规则兜底：出现任一关键词即判为重大隐患
_MAJOR_KEYWORDS: tuple[str, ...] = (
    "泄漏", "起火", "着火", "爆炸", "中毒", "窒息", "氨", "氯", "氢气", "硫化氢",
    "可燃气体", "高处", "受限空间", "超压", "高温", "动火", "坍塌", "灼伤",
)

JUDGE_PROMPT = """你是化工安全专家，请基于隐患描述与图像检测结果对隐患定级。
只返回一个 JSON 对象：{{"level": "特别重大隐患" | "重大隐患" | "一般隐患", "reason": "定级依据，引用相关判定原则"}}

【隐患描述】{question}
【图像检测结果】{detections}

定级原则：
- 涉及易燃易爆/有毒有害物质泄漏、可能引发火灾爆炸或人员中毒伤亡 → 特别重大/重大隐患；
- 高处、受限空间、动火等高风险作业违规 → 重大隐患；
- 一般跑冒滴漏、标识缺失、清洁卫生等 → 一般隐患。
"""


def _rule_based_level(question: str, detections: list[dict[str, Any]]) -> str:
    """关键词兜底定级。"""
    text = question + " " + " ".join(
        str(item.get("label", "")) for item in detections
    )
    return "重大隐患" if any(kw in text for kw in _MAJOR_KEYWORDS) else "一般隐患"


def hazard_judge_node(state: AgentState) -> AgentState:
    """定级并写回 hazard_level / hazard_reason。"""
    question = state.get("question") or ""
    detections = state.get("yolo_detections") or []
    prompt = JUDGE_PROMPT.format(
        question=question or "（无文字描述，仅依据图像检测）",
        detections=json.dumps(detections, ensure_ascii=False),
    )
    try:
        result = get_llm().chat_json([{"role": "user", "content": prompt}], temperature=0.0)
        level = str(result.get("level") or "").strip()
        reason = str(result.get("reason") or "").strip()
        if level not in {"特别重大隐患", "重大隐患", "一般隐患"}:
            raise ValueError(f"非法的等级输出: {level}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 定级失败，使用规则兜底: %s", exc)
        level = _rule_based_level(question, detections)
        reason = "规则关键词判定（LLM 定级失败降级）"

    logger.info("隐患定级：%s（依据：%s）", level, reason[:60])
    return {"hazard_level": level, "hazard_reason": reason}
