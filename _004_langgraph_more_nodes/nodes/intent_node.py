"""意图识别节点：区分 QA（法规问答）/ HAZARD（隐患识别）/ PERMIT（作业票审核）。"""
from __future__ import annotations

from common.llm import get_llm
from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

INTENT_SYSTEM_PROMPT = """你是化工安全生产智能体的意图分类器。
根据用户输入判断其意图，只返回一个 JSON 对象（不要 markdown 代码块）：
{{"intent": "qa" | "hazard" | "permit", "reason": "简短判断依据"}}

分类规则：
- "qa"     ：询问法规、制度、流程等知识性问题，如「登高作业需要办理什么手续？」
- "hazard" ：上报/描述现场隐患、设备异常、危险场景，或伴随现场图片，如「反应釜顶部阀门漏气」「储罐区闻到异味」
- "permit" ：作业票/许可证相关审核，如「帮我检查这张动火作业票缺什么」「这张票能不能批」

注意：只允许返回三种意图之一，无法判断时默认 "qa"。
"""


def _build_user_prompt(state: AgentState) -> str:
    """综合 question / 图片 / 作业票字段构造分类依据。"""
    parts = [f"用户输入：{state.get('question') or ''}"]
    if state.get("image_path"):
        parts.append("（附注：用户上传了现场图片，通常属于隐患识别场景）")
    if state.get("permit_data"):
        parts.append("（附注：用户提交了作业票字段，应判断为 permit）")
    return "\n".join(parts)


def intent_node(state: AgentState) -> AgentState:
    """识别并写回 intent 字段。"""
    llm = get_llm()
    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(state)},
    ]
    try:
        result = llm.chat_json(messages, temperature=0.0)
        intent = str(result.get("intent") or "qa").strip().lower()
    except Exception as exc:  # noqa: BLE001
        logger.warning("意图识别失败，默认 qa: %s", exc)
        intent = "qa"

    if intent not in {"qa", "hazard", "permit"}:
        intent = "qa"
    logger.info("意图识别：%s（问题：%s）", intent, (state.get("question") or "")[:50])
    return {"intent": intent}
