"""【关键】自省校验 Cypher 合法性。

双层校验：
1. 静态规则检查 —— 拦截写操作、限制起始关键字、括号配平；
2. EXPLAIN 语法校验 —— 若 Neo4j 可用，用 EXPLAIN 做真实语法检查（不执行、零写入）。

校验不通过 → 路由到 FAISS 向量兜底（见 graph_builder 条件边）。
"""
from __future__ import annotations

import re
from typing import Any

from common.logger import get_logger
from common.neo4j_manager import Neo4jManager
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

# 禁止出现的写操作关键字
_FORBIDDEN_KEYWORDS: tuple[str, ...] = ("CREATE", "DELETE", "DETACH", "DROP",
                                        "REMOVE", "SET", "MERGE", "FOREACH", "CALL")
# 允许作为语句开头的关键字
_ALLOWED_STARTS: tuple[str, ...] = ("MATCH", "OPTIONAL MATCH", "WITH", "RETURN")


def _basic_check(query: str) -> tuple[bool, str]:
    """静态规则校验，返回 (是否通过, 失败原因)。"""
    if not query or not query.strip():
        return False, "查询为空"
    # 去掉注释行
    cleaned = re.sub(r"//.*", "", query)

    upper = cleaned.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            return False, f"包含禁止的写操作关键字 {keyword}"

    first_token = upper.strip().splitlines()[0].strip()
    if not any(first_token.startswith(prefix) for prefix in _ALLOWED_STARTS):
        return False, "语句必须以 MATCH/OPTIONAL MATCH/WITH/RETURN 开头"

    for open_char, close_char in (("(", ")"), ("[", "]"), ("{", "}")):
        if query.count(open_char) != query.count(close_char):
            return False, f"括号 {open_char}{close_char} 不配对"

    if query.count(";") > 0:
        # 允许末尾分号，但禁止多语句
        if query.rstrip().rstrip(";").count(";") > 0:
            return False, "禁止多条语句"
    return True, ""


def _explain_check(query: str) -> tuple[bool, str]:
    """用 EXPLAIN 在 Neo4j 上做语法校验（不实际执行）。"""
    manager = Neo4jManager()
    if not manager.available:
        logger.warning("Neo4j 不可用，跳过 EXPLAIN 校验")
        return True, ""
    try:
        manager.run(f"EXPLAIN {query}")
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"语法校验失败: {exc}"


def check_cypher_node(state: AgentState) -> AgentState:
    """校验并写回 cypher_valid / cypher_error。"""
    cypher = state.get("cypher_query") or ""
    ok, reason = _basic_check(cypher)
    update: dict[str, Any] = {}

    if not ok:
        update = {"cypher_valid": False, "cypher_error": reason}
        logger.warning("Cypher 静态校验未通过: %s", reason)
    else:
        ok_explain, reason_explain = _explain_check(cypher)
        if ok_explain:
            update = {"cypher_valid": True, "cypher_error": None}
            logger.info("Cypher 校验通过")
        else:
            update = {"cypher_valid": False, "cypher_error": reason_explain}
            logger.warning("Cypher EXPLAIN 校验未通过: %s", reason_explain)
    return update
