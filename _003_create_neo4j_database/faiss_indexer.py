"""读取元数据，调用 embedding_model 构建 FAISS 索引。

索引与映射文件均存放于 storage/ 目录：
- {FAISS_INDEX_NAME}: faiss 向量索引
- metadata.json:     与索引一一对应的节点元数据
- id_map.pkl:        位置下标 → 节点字典 的映射（兼容非连续场景）
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from _003_create_neo4j_database.metadata_export import build_node_text
from common.config import settings
from common.embedding_model import EmbeddingModel
from common.logger import get_logger

logger = get_logger(__name__)


class FaissIndexer:
    """基于 EmbeddingModel 构建与加载 FAISS 索引。"""

    def __init__(self) -> None:
        self.embedder: EmbeddingModel = EmbeddingModel()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(
        self,
        *,
        metadata: list[dict[str, Any]] | None = None,
        texts: list[str] | None = None,
        save: bool = True,
    ) -> dict[str, Any]:
        """构建索引。

        Args:
            metadata: 与 texts 一一对应的节点元数据；若不传则仅构建向量索引。
            texts: 待向量化的文本；缺省时由 metadata 自动拼接。
            save: 是否落盘。
        """
        if texts is None:
            texts = [build_node_text(node) for node in (metadata or [])]
        vectors = self.embedder.embed(texts)
        index = self.embedder.build_index(vectors)

        if save:
            self.save(index, metadata=metadata, texts=texts)

        logger.info("FAISS 索引构建完成：%d 条向量，维度 %d", len(texts), self.embedder.dim)
        return {"index": index, "texts": texts}

    def save(
        self,
        index: Any,
        *,
        metadata: list[dict[str, Any]] | None,
        texts: list[str],
    ) -> None:
        """索引与映射一并落盘到 storage/。"""
        settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.embedder.save_index(index, settings.STORAGE_DIR / settings.FAISS_INDEX_NAME)
        with open(settings.STORAGE_DIR / "texts.txt", "w", encoding="utf-8") as fp:
            fp.write("\n".join(texts))
        if metadata is not None:
            with open(settings.STORAGE_DIR / settings.FAISS_META_NAME, "w", encoding="utf-8") as fp:
                json.dump(metadata, fp, ensure_ascii=False, indent=2)
            with open(settings.STORAGE_DIR / settings.FAISS_MAP_NAME, "wb") as fp:
                pickle.dump({i: node for i, node in enumerate(metadata)}, fp)

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load(self) -> dict[str, Any]:
        """加载已构建的索引、元数据与 id_map。

        Raises:
            FileNotFoundError: 索引文件缺失时抛出。
        """
        index_path = settings.STORAGE_DIR / settings.FAISS_INDEX_NAME
        if not index_path.exists():
            raise FileNotFoundError(
                f"FAISS 索引不存在：{index_path}，请先运行本模块构建索引"
            )
        index = self.embedder.load_index(index_path)

        id_map: dict[int, dict[str, Any]] = {}
        map_path = settings.STORAGE_DIR / settings.FAISS_MAP_NAME
        if map_path.exists():
            with open(map_path, "rb") as fp:
                id_map = pickle.load(fp)

        metadata: list[dict[str, Any]] = []
        meta_path = settings.STORAGE_DIR / settings.FAISS_META_NAME
        if meta_path.exists():
            metadata = self.embedder.load_metadata(meta_path)

        return {"index": index, "id_map": id_map, "metadata": metadata}

    # ------------------------------------------------------------------
    # 便捷重建
    # ------------------------------------------------------------------
    def rebuild_from_storage(self) -> None:
        """从 storage/ 中已有的 metadata.json 或 texts.txt 重建索引。"""
        meta_path = settings.STORAGE_DIR / settings.FAISS_META_NAME
        texts_path = settings.STORAGE_DIR / "texts.txt"

        if meta_path.exists():
            metadata = self.embedder.load_metadata(meta_path)
            self.build(metadata=metadata)
            return
        if texts_path.exists():
            texts = texts_path.read_text(encoding="utf-8").splitlines()
            self.build(texts=texts)
            return
        raise FileNotFoundError("storage 目录缺少 metadata.json 或 texts.txt，无法重建")


def main() -> None:
    """CLI 入口：从 storage 现有元数据重建索引。"""
    FaissIndexer().rebuild_from_storage()


if __name__ == "__main__":
    main()
