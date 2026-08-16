"""执行 Cypher 查 Neo4j。

执行失败或返回空结果 → 由 graph_builder 的条件边路由到 FAISS 向量兜底。
"""
from __future__ import annotations

from common.logger import get_logger
from common.neo4j_manager import Neo4jManager
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)


def run_cypher_node(state: AgentState) -> AgentState:
    """执行校验通过的 Cypher（带参数）并写回 graph_result。"""
    cypher = state.get("cypher_query")
    if not cypher:
        return {"graph_result": [], "error": "无 Cypher 可执行"}

    params = state.get("cypher_params") or {}
    try:
        rows = Neo4jManager().run(cypher, params)
        logger.info("Cypher 执行成功，返回 %d 条记录", len(rows))
        return {"graph_result": rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cypher 执行失败，交由向量分支支撑: %s", exc)
        return {"graph_result": [], "error": f"图查询失败: {exc}"}
