"""根据意图和实体生成 Cypher 查询。

仅允许生成只读查询（MATCH / WHERE / RETURN 等），写操作由下游 check_cypher_node 再次拦截。
"""
from __future__ import annotations

import json
from typing import Any

from common.llm import get_llm
from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

CYPHER_GENERATION_PROMPT = """你是 Neo4j 图数据库查询专家。数据库结构如下：
- 节点统一标签 `Entity`，属性：`name`(实体名)、`type`(实体类型)。
- 实体类型枚举：Regulation(法规)、Standard(标准)、Hazard(隐患)、Equipment(设备)、
  Operation(作业)、Material(物质)、Location(场所)、PersonRole(岗位)、
  Qualification(资质)、Permit(作业票)、Process(工艺)、Accident(事故)、Document(制度文件)。
- 关系类型：REGULATES(规范)、REQUIRES(要求/需要)、HAS_PERMIT(需要作业票)、
  INVOLVES(涉及)、PROHIBITS(禁止)、HAS_HAZARD(存在隐患)、LOCATED_IN(位于)、
  CAUSED_BY(由...导致)、RESULTS_IN(导致)、REQUIRES_QUALIFICATION(需要资质)、
  VIOLATES(违反)、PREVENTS(预防)、MENTIONS(提及)、BELONGS_TO(属于)。

请根据【用户问题】与【已抽取实体】生成一条**只读** Cypher 查询。
硬性要求：
1. 只允许使用 MATCH / OPTIONAL MATCH / WHERE / RETURN / ORDER BY / LIMIT，禁止一切写操作。
2. 实体名必须来自【已抽取实体】或常识性的规范名称，使用 `CONTAINS`/精确匹配均可，不要编造明显无关的名称。
3. 问题问「需要什么手续/资质」时：沿 REQUIRES / HAS_PERMIT / REQUIRES_QUALIFICATION 关系查找许可证与资质节点。
4. RETURN 至少返回相关节点的 name 与 type，示例：
   MATCH (e:Entity) WHERE e.name CONTAINS $kw
   OPTIONAL MATCH (e)-[:REQUIRES|HAS_PERMIT]->(need:Entity)
   RETURN e.name AS name, e.type AS type, need.name AS target_name, need.type AS target_type
5. 只允许使用以下参数（下游会按此字典提供值），避免硬编码大量中文文本：
   `$kw`(主关键词，从 equipment/operation/material/regulation/location 中取)、
   `$op`(作业类型)、`$eq`(设备)、`$mat`(物质)、`$loc`(场所)、`$reg`(法规)。

只返回一个 JSON 对象：{{"cypher": "完整的只读 Cypher 语句"}}

【用户问题】{question}
【已抽取实体】{entities}
"""


# 提示词允许的参数名 → 从实体字典取值（未命中给空串，下游传参不会报 ParameterMissing）
_PARAM_SOURCES: dict[str, tuple[str, ...]] = {
    "kw": ("equipment", "operation", "material", "regulation", "location"),
    "op": ("operation",),
    "eq": ("equipment",),
    "mat": ("material",),
    "loc": ("location",),
    "reg": ("regulation",),
}


def _build_cypher_params(entities: dict[str, Any]) -> dict[str, str]:
    """按提示词约定的参数名，从实体抽取构造参数字典。"""
    params: dict[str, str] = {}
    for name, sources in _PARAM_SOURCES.items():
        value = ""
        for source in sources:
            vals = entities.get(source) or []
            if vals:
                value = str(vals[0])
                break
        params[name] = value
    return params


def generate_cypher_node(state: AgentState) -> AgentState:
    """生成并写回 cypher_query 与 cypher_params（默认 cypher_valid=False，等待校验）。"""
    question = state.get("question") or ""
    entities = state.get("entities") or {}
    prompt = CYPHER_GENERATION_PROMPT.format(
        question=question,
        entities=json.dumps(entities, ensure_ascii=False),
    )
    try:
        result: dict[str, Any] = get_llm().chat_json(
            [{"role": "user", "content": prompt}], temperature=0.0
        )
        cypher = str(result.get("cypher") or "").strip()
        if not cypher:
            raise ValueError("LLM 未返回 Cypher")
        logger.info("生成 Cypher：\n%s", cypher)
        return {
            "cypher_query": cypher,
            "cypher_params": _build_cypher_params(entities),
            "cypher_valid": False,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Cypher 生成失败: %s", exc)
        return {"cypher_query": None, "cypher_valid": False, "error": f"Cypher 生成失败: {exc}"}
