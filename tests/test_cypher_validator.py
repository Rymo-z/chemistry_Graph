"""测试 check_cypher_node 的静态规则校验（无需 Neo4j）。

运行：
    python -m unittest tests.test_cypher_validator -v
"""
from __future__ import annotations

import unittest

from _004_langgraph_more_nodes.nodes.check_cypher_node import _basic_check


class TestCypherValidator(unittest.TestCase):
    """Cypher 静态校验规则测试。"""

    def test_valid_read_query(self) -> None:
        query = (
            "MATCH (e:Entity) WHERE e.name CONTAINS $kw "
            "OPTIONAL MATCH (e)-[:REQUIRES]->(n:Entity) "
            "RETURN e.name AS name, n.name AS target"
        )
        ok, reason = _basic_check(query)
        self.assertTrue(ok, reason)

    def test_reject_write_operations(self) -> None:
        for bad in (
            "CREATE (n:Entity {name:'x'})",
            "MATCH (n) DELETE n",
            "MATCH (n) DETACH DELETE n",
            "MATCH (n) MERGE (n)-[:R]->(m)",
            "MATCH (n) SET n.type = 'x'",
        ):
            ok, reason = _basic_check(bad)
            self.assertFalse(ok, f"应拦截写操作: {bad} ({reason})")

    def test_reject_wrong_start(self) -> None:
        ok, reason = _basic_check("DROP INDEX index")
        self.assertFalse(ok, reason)

    def test_reject_unbalanced_brackets(self) -> None:
        ok, _ = _basic_check("MATCH (n WHERE n.name = 'x' RETURN n")
        self.assertFalse(ok)

    def test_reject_empty(self) -> None:
        ok, _ = _basic_check("   ")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
