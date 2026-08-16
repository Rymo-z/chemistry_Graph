"""Neo4j 驱动单例封装。

提供线程安全的查询入口：`run(query, params) -> list[dict]`，
并统一处理连接校验、异常日志与资源释放。
"""
from __future__ import annotations

from typing import Any, Optional

from neo4j import Driver, GraphDatabase

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)


class Neo4jManager:
    """管理单一 Neo4j Driver（进程级单例）。"""

    _instance: Optional["Neo4jManager"] = None

    def __new__(cls) -> "Neo4jManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.driver: Optional[Driver] = None
        return cls._instance

    def connect(self) -> "Neo4jManager":
        """建立连接（懒加载，幂等）。连接失败抛出异常由调用方处理。"""
        if self.driver is None:
            self.driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            self.driver.verify_connectivity()
            logger.info("Neo4j 连接成功: %s", settings.NEO4J_URI)
        return self

    @property
    def available(self) -> bool:
        """探测 Neo4j 是否可用（不可用时不抛异常）。"""
        try:
            self.connect()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j 不可用: %s", exc)
            return False

    def run(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """执行 Cypher 查询并返回字典列表（每次自动提交事务）。

        Args:
            query: Cypher 语句。
            params: 参数化查询的参数字典。
        """
        self.connect()
        with self.driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(query, params or {})
            return [dict(record) for record in result]

    def close(self) -> None:
        """释放驱动连接（应用退出时调用）。"""
        if self.driver is not None:
            self.driver.close()
            self.driver = None
            logger.info("Neo4j 连接已关闭")


def get_neo4j() -> Neo4jManager:
    """获取全局 Neo4j 管理器单例。"""
    return Neo4jManager()
