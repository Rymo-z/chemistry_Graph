"""导入抽取 JSON 到 Neo4j（含清库、批量导入实体/关系）。

所有节点统一标签 `Entity`，`type` 属性区分类型；关系类型由 RelationType 枚举限定。
使用 `UNWIND` + `MERGE` 批量写入，保证幂等（重复导入不产生重复实体）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _002_extract_information.schema import EntityType, RelationType
from common.config import settings
from common.logger import get_logger
from common.neo4j_manager import Neo4jManager

logger = get_logger(__name__)

VALID_ENTITY_TYPES: set[str] = {e.value for e in EntityType}
VALID_RELATION_TYPES: set[str] = {r.value for r in RelationType}

# 属性 map 展开为节点顶层属性（Neo4j 不允许 Map 作为属性值，只能存原始类型或数组）。
_ENTITY_MERGE = """
UNWIND $rows AS row
MERGE (e:Entity {name: row.name})
SET e.type = row.etype, e.aliases = row.aliases
SET e += row.attributes
"""

# 与 MERGE 键冲突的保留属性名（同名时展开会覆盖 e.name/e.type/e.aliases）
_RESERVED_KEYS = {"name", "type", "aliases"}


def _flatten_attributes(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """把抽取的 attributes map 规整为可写属性：过滤空键/保留键，
    嵌套 list/dict 序列化为 JSON 字符串（Neo4j 只接受原始类型或数组）。"""
    out: dict[str, Any] = {}
    for k, v in (attrs or {}).items():
        key = str(k).strip()
        if not key or key in _RESERVED_KEYS:
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        elif v is None:
            v = ""
        elif not isinstance(v, (str, int, float, bool)):
            v = str(v)
        out[key] = v
    return out


class GraphImporter:
    """把 _002/output/*.json 的实体关系导入 Neo4j。"""

    def __init__(self) -> None:
        self.neo4j = Neo4jManager()

    # ------------------------------------------------------------------
    # 清库
    # ------------------------------------------------------------------
    def clear_database(self) -> None:
        """清空图数据库（生产环境请谨慎调用）。"""
        self.neo4j.connect()
        self.neo4j.run("MATCH (n) DETACH DELETE n")
        logger.info("图数据库已清空")

    # ------------------------------------------------------------------
    # 导入
    # ------------------------------------------------------------------
    def import_json_file(self, path: str | Path) -> int:
        """导入单个抽取 JSON 文件，返回导入的（实体+关系）数量。"""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        return self.import_payload(payload)

    def import_directory(self, directory: str | Path | None = None) -> int:
        """批量导入 output 目录下全部抽取 JSON。"""
        base = Path(directory) if directory else settings.EXTRACT_OUTPUT_DIR
        files = sorted(base.glob("*.json"))
        total = 0
        for path in files:
            try:
                total += self.import_json_file(path)
            except Exception as exc:  # noqa: BLE001
                logger.error("导入失败 %s: %s", path, exc)
        logger.info("批量导入完成，共导入 %d 个 JSON，累计 %d 条", len(files), total)
        return total

    def import_payload(self, data: dict[str, Any]) -> int:
        """导入单份抽取结果。"""
        entities: list[dict[str, Any]] = data.get("entities") or []
        relations: list[dict[str, Any]] = data.get("relations") or []
        entity_count = self.batch_import_entities(entities)
        relation_count = self.batch_import_relations(relations)
        logger.info("导入完成：实体=%d 关系=%d", entity_count, relation_count)
        return entity_count + relation_count

    # ------------------------------------------------------------------
    # 批量写入
    # ------------------------------------------------------------------
    def batch_import_entities(self, entities: list[dict[str, Any]]) -> int:
        """批量 MERGE 实体（UNWIND，单次事务）。"""
        rows: list[dict[str, Any]] = []
        for raw in entities:
            etype = raw.get("type") or EntityType.DOCUMENT.value
            if etype not in VALID_ENTITY_TYPES:
                etype = EntityType.DOCUMENT.value
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "etype": etype,
                    "aliases": raw.get("aliases") or [],
                    "attributes": _flatten_attributes(raw.get("attributes")),
                }
            )
        if not rows:
            return 0
        self.neo4j.connect()
        self.neo4j.run(_ENTITY_MERGE, {"rows": rows})
        return len(rows)

    def batch_import_relations(self, relations: list[dict[str, Any]]) -> int:
        """按关系类型分组批量 MERGE（关系类型不可参数化，需逐类型写语句）。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for raw in relations:
            rtype = raw.get("relation") or RelationType.MENTIONS.value
            if rtype not in VALID_RELATION_TYPES:
                rtype = RelationType.MENTIONS.value
            grouped.setdefault(rtype, []).append(raw)

        total = 0
        self.neo4j.connect()
        for rtype, items in grouped.items():
            rows = []
            for raw in items:
                source = str(raw.get("source", "")).strip()
                target = str(raw.get("target", "")).strip()
                if not source or not target:
                    continue
                rows.append(
                    {
                        "source": source,
                        "target": target,
                        "attributes": _flatten_attributes(raw.get("attributes")),
                    }
                )
            if not rows:
                continue
            query = f"""
            UNWIND $rows AS row
            MATCH (a:Entity {{name: row.source}})
            MATCH (b:Entity {{name: row.target}})
            MERGE (a)-[r:{rtype}]->(b)
            SET r += row.attributes
            """
            self.neo4j.run(query, {"rows": rows})
            total += len(rows)
        return total


def main() -> None:
    """CLI 入口：清库并导入全部抽取结果。"""
    importer = GraphImporter()
    importer.clear_database()
    count = importer.import_directory()
    logger.info("全部完成，共写入 %d 条", count)


if __name__ == "__main__":
    main()
