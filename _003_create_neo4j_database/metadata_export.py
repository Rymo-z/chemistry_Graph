"""导出节点文本和元数据供 FAISS 映射。

把图中每个 Entity 节点拼成一段可向量化的文本（类型 + 名称 + 别名 + 关键属性），
落盘为 metadata.json / texts.txt / id_map.pkl，供 faiss_indexer 与 RAG 检索使用。
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from common.config import settings
from common.logger import get_logger
from common.neo4j_manager import Neo4jManager

logger = get_logger(__name__)

EXPORT_QUERY = """
MATCH (e:Entity)
RETURN e.name AS name, e.type AS type, e.aliases AS aliases, properties(e) AS props
"""

# Neo4j 图导出路径：属性已展开为顶层属性（props）；离线 JSON 路径仍是 attributes map
_SKIP_KEYS = {"name", "type", "aliases", "props", "attributes"}


def build_node_text(node: dict[str, Any]) -> str:
    """把节点拼接为适合向量化的语义文本。"""
    parts = [f"类型：{node.get('type') or ''}", f"名称：{node.get('name') or ''}"]
    aliases = node.get("aliases") or []
    if aliases:
        parts.append("别名：" + "、".join(str(a) for a in aliases))
    attrs = node.get("props") or node.get("attributes") or {}
    for key, value in attrs.items():
        if key in _SKIP_KEYS or value in (None, "", [], {}):
            continue
        parts.append(f"{key}：{value}")
    return "；".join(parts)


def export_metadata(
    neo4j: Neo4jManager | None = None,
    *,
    save: bool = True,
) -> dict[str, Any]:
    """查询全部实体节点，构造 texts / metadata / id_map 并落盘。

    Returns:
        {"texts": list[str], "metadata": list[dict], "id_map": dict[int, dict]}
    """
    manager = neo4j or Neo4jManager()
    rows = manager.run(EXPORT_QUERY)

    texts: list[str] = []
    metadata: list[dict[str, Any]] = []
    id_map: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        node = dict(row)
        texts.append(build_node_text(node))
        metadata.append(node)
        id_map[index] = node

    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if save:
        with open(settings.STORAGE_DIR / settings.FAISS_META_NAME, "w", encoding="utf-8") as fp:
            json.dump(metadata, fp, ensure_ascii=False, indent=2)
        with open(settings.STORAGE_DIR / "texts.txt", "w", encoding="utf-8") as fp:
            fp.write("\n".join(texts))
        with open(settings.STORAGE_DIR / settings.FAISS_MAP_NAME, "wb") as fp:
            pickle.dump(id_map, fp)

    logger.info("元数据导出完成：%d 条 → %s", len(metadata), settings.STORAGE_DIR)
    return {"texts": texts, "metadata": metadata, "id_map": id_map}


def export_from_json(output_dir: str | Path | None = None) -> dict[str, Any]:
    """离线模式：不依赖 Neo4j，直接从抽取 JSON 构造节点元数据。

    用于「无图库环境先建向量索引」的场景，把每个 JSON 的实体视为节点。
    """
    base = Path(output_dir) if output_dir else settings.EXTRACT_OUTPUT_DIR
    metadata: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except json.JSONDecodeError:
            continue
        for entity in payload.get("entities") or []:
            node = {
                "name": str(entity.get("name", "")).strip(),
                "type": entity.get("type") or "Document",
                "aliases": entity.get("aliases") or [],
                "attributes": entity.get("attributes") or {},
                "source": payload.get("source", path.stem),
            }
            if node["name"]:
                metadata.append(node)

    texts = [build_node_text(node) for node in metadata]
    id_map = {index: node for index, node in enumerate(metadata)}

    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(settings.STORAGE_DIR / settings.FAISS_META_NAME, "w", encoding="utf-8") as fp:
        json.dump(metadata, fp, ensure_ascii=False, indent=2)
    with open(settings.STORAGE_DIR / "texts.txt", "w", encoding="utf-8") as fp:
        fp.write("\n".join(texts))
    with open(settings.STORAGE_DIR / settings.FAISS_MAP_NAME, "wb") as fp:
        pickle.dump(id_map, fp)

    logger.info("离线元数据导出完成：%d 条 → %s", len(metadata), settings.STORAGE_DIR)
    return {"texts": texts, "metadata": metadata, "id_map": id_map}


def main() -> None:
    """CLI 入口：优先从 Neo4j 导出，失败则降级离线模式。"""
    manager = Neo4jManager()
    if manager.available:
        export_metadata(manager)
    else:
        logger.warning("Neo4j 不可用，降级为离线模式（从抽取 JSON 导出）")
        export_from_json()


if __name__ == "__main__":
    main()
