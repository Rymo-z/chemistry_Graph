"""测试 Neo4j 连通性与基础读写。

运行：
    python -m unittest tests.test_neo4j -v
"""
from __future__ import annotations

import unittest

from common.neo4j_manager import Neo4jManager


class TestNeo4j(unittest.TestCase):
    """Neo4j 连接与基础查询测试（跳过式：未启动则跳过）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manager = Neo4jManager()
        if not cls.manager.available:
            raise unittest.SkipTest("Neo4j 未启动，跳过 Neo4j 相关测试")

    def test_connectivity(self) -> None:
        """基础连通性：RETURN 1。"""
        result = self.manager.run("RETURN 1 AS value")
        self.assertEqual(result[0]["value"], 1)

    def test_simple_node_write_and_read(self) -> None:
        """写入并读取一个临时节点（测试后清理）。"""
        self.manager.run("MERGE (n:Entity {name: '__unit_test_node__'}) SET n.type = 'Test'")
        result = self.manager.run(
            "MATCH (n:Entity {name: '__unit_test_node__'}) RETURN n.type AS type"
        )
        self.assertEqual(result[0]["type"], "Test")
        self.manager.run("MATCH (n:Entity {name: '__unit_test_node__'}) DETACH DELETE n")


if __name__ == "__main__":
    unittest.main()
