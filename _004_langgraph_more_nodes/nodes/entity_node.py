"""实体抽取节点：从问题中抽取设备/作业类型/隐患现象/物质/场所等。

LLM 失败时降级为规则关键词抽取，保证离线也能继续后续图查询链路。
"""
from __future__ import annotations

import json
from typing import Any

from common.llm import get_llm
from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

ENTITY_SYSTEM_PROMPT = """你是化工安全生产领域的实体抽取器。从问题中抽取相关实体，只返回一个 JSON 对象：
{
  "equipment": ["设备/设施", ...],
  "operation": ["作业类型，如高处作业/动火作业", ...],
  "hazard": ["隐患/异常现象描述", ...],
  "material": ["危险物质", ...],
  "location": ["场所/区域", ...],
  "permit": ["作业票/许可证类型", ...],
  "regulation": ["法规/标准名称", ...]
}
某一类没有命中就返回空数组，不要编造问题中不存在的实体。
"""

# -------------------- 规则兜底词典 --------------------
_OPERATION_KEYWORDS: dict[str, str] = {
    "登高": "高处作业", "高处": "高处作业", "动火": "动火作业", "受限空间": "受限空间作业",
    "吊装": "吊装作业", "临时用电": "临时用电作业", "盲板": "盲板抽堵作业",
    "断路": "断路作业", "破土": "破土作业", "检维修": "检维修作业", "动土": "动土作业",
}
_EQUIPMENT_KEYWORDS = [
    "反应釜", "储罐", "管道", "压力容器", "锅炉", "阀门", "泵", "塔", "压缩机",
    "电焊机", "行车", "起重", "电梯", "防爆开关", "法兰", "仪表", "报警器", "喷淋",
]
_MATERIAL_KEYWORDS = [
    "氢气", "氯气", "氨", "苯", "甲醇", "液化气", "天然气", "硫酸", "盐酸",
    "硫化氢", "一氧化碳", "乙烯", "丙烯", "汽油", "柴油", "氧气", "乙炔",
]
_HAZARD_KEYWORDS = ["泄漏", "跑冒滴漏", "腐蚀", "超压", "高温", "异味", "起火", "冒烟",
                    "堵塞", "锈蚀", "变形", "振动", "异响", "未接地", "未设围挡"]


def _rule_based_entities(question: str) -> dict[str, list[str]]:
    """基于关键词匹配的实体抽取（离线兜底）。"""
    entities: dict[str, list[str]] = {
        "equipment": [], "operation": [], "hazard": [],
        "material": [], "location": [], "permit": [], "regulation": [],
    }
    for keyword, operation in _OPERATION_KEYWORDS.items():
        if keyword in question:
            entities["operation"].append(operation)
    for keyword in _EQUIPMENT_KEYWORDS:
        if keyword in question:
            entities["equipment"].append(keyword)
    for keyword in _MATERIAL_KEYWORDS:
        if keyword in question:
            entities["material"].append(keyword)
    for keyword in _HAZARD_KEYWORDS:
        if keyword in question:
            entities["hazard"].append(keyword)
    return {k: list(dict.fromkeys(v)) for k, v in entities.items() if v}


def _parse_llm_result(raw: dict[str, Any]) -> dict[str, list[str]]:
    """清洗 LLM 输出为 {字段: [值]}，去重去空。"""
    entities: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(value, list):
            continue
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if cleaned:
            entities[key] = list(dict.fromkeys(cleaned))
    return entities


def entity_node(state: AgentState) -> AgentState:
    """抽取并写回 entities 字段。"""
    question = state.get("question") or ""
    llm = get_llm()
    messages = [
        {"role": "system", "content": ENTITY_SYSTEM_PROMPT},
        {"role": "user", "content": f"问题：{question}"},
    ]
    try:
        raw = llm.chat_json(messages, temperature=0.0)
        entities = _parse_llm_result(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 实体抽取失败，使用规则兜底: %s", exc)
        entities = _rule_based_entities(question)

    if not entities:
        entities = _rule_based_entities(question)
    logger.info("实体抽取：%s", json.dumps(entities, ensure_ascii=False))
    return {"entities": entities}
