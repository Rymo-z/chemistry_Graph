"""查 FAISS 向量库 + 1 跳图邻居扩展（并行混合检索的向量分支）。

对用户问题做语义检索，返回 top-k 节点（含元数据），并对每个命中节点在
Neo4j 取其 1 跳关系与相邻节点，构造富文本 evidence_text，供 QA 合成答案引用。
"""
from __future__ import annotations

from typing import Any

from _003_create_neo4j_database.faiss_indexer import FaissIndexer
from _003_create_neo4j_database.metadata_export import build_node_text
from common.embedding_model import get_embedding_model
from common.logger import get_logger
from common.neo4j_manager import Neo4jManager
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)

DEFAULT_TOP_K = 5
MAX_NEIGHBORS = 6

# 出/入向 1 跳查询（参数化，仅返回 name/type/关系类型）
_NEIGHBOR_QUERIES = (
    "MATCH (e:Entity {name:$name})-[r]->(n:Entity) "
    "RETURN '出' AS dir, type(r) AS rel, n.name AS name, n.type AS type LIMIT $limit",
    "MATCH (n:Entity)-[r]->(e:Entity {name:$name}) "
    "RETURN '入' AS dir, type(r) AS rel, n.name AS name, n.type AS type LIMIT $limit",
)


def _expand_neighbors(name: str, limit: int = MAX_NEIGHBORS) -> list[dict[str, Any]]:
    """在 Neo4j 取节点 1 跳邻居；图不可用/未命中时返回空列表。"""
    manager = Neo4jManager()
    if not manager.available:
        return []
    try:
        rows: list[dict[str, Any]] = []
        for query in _NEIGHBOR_QUERIES:
            rows.extend(manager.run(query, {"name": name, "limit": limit}))
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("1 跳邻居扩展失败（忽略）: %s", str(exc)[:100])
        return []


def _build_evidence_text(node: dict[str, Any], neighbors: list[dict[str, Any]]) -> str:
    """节点文本 + 1 跳邻居 → 富文本证据。"""
    lines = [build_node_text(node)]
    for nb in neighbors:
        rel = nb.get("rel") or ""
        nb_name = nb.get("name") or ""
        nb_type = nb.get("type") or ""
        if not nb_name:
            continue
        lines.append(f"- 关联[{rel}]：{nb_name} [{nb_type}]")
    return "\n".join(lines)


def _retrieve(query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """加载索引检索，返回 [{score, node, neighbors, evidence_text}]；索引缺失返回空。"""
    try:
        loader = FaissIndexer().load()
    except FileNotFoundError as exc:
        logger.warning("向量索引未就绪，跳过 RAG 检索: %s", exc)
        return []

    hits = get_embedding_model().search(loader["index"], query, k=top_k)
    results: list[dict[str, Any]] = []
    for score, position in hits:
        node: dict[str, Any] = {}
        metadata = loader.get("metadata") or []
        if position < len(metadata) and metadata[position]:
            node = metadata[position]
        else:
            node = loader.get("id_map", {}).get(position, {})
        name = str(node.get("name") or "").strip()
        neighbors = _expand_neighbors(name) if name else []
        results.append(
            {
                "score": round(score, 4),
                "node": node,
                "neighbors": neighbors,
                "evidence_text": _build_evidence_text(node, neighbors),
            }
        )
    return results


def rag_retrieval_node(state: AgentState) -> AgentState:
    """对问题做向量检索 + 1 跳图扩展并写回 rag_results。"""
    query = state.get("question") or ""
    if not query:
        return {"rag_results": []}
    results = _retrieve(query)
    logger.info(
        "FAISS 检索完成，命中 %d 条（问题：%s）", len(results), query[:50]
    )
    return {"rag_results": results}
