"""SentenceTransformer 向量化 + FAISS 索引封装（单例）。

职责边界：
- 本模块负责「模型加载 / 向量化 / 索引读写 / 检索」；
- 具体索引的构建流程（读元数据 → 向量化 → 落盘）在 `_003` 的 faiss_indexer 中编排。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

# bge 系列 zh 模型的查询侧指令前缀（官方推荐，显著提升 s2p 检索质量）
BGE_ZH_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class EmbeddingModel:
    """本地 embedding 模型单例（离线可用，数据不出厂）。"""

    _instance: Optional["EmbeddingModel"] = None

    def __new__(cls) -> "EmbeddingModel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model: Any = None
            cls._instance._dim: int = 0
        return cls._instance

    # ------------------------------------------------------------------
    # 模型懒加载
    # ------------------------------------------------------------------
    @property
    def model(self) -> Any:
        """SentenceTransformer 实例（首次访问才真正加载）。"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("加载 embedding 模型: %s", settings.EMBEDDING_MODEL)
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
            dim_fn = getattr(self._model, "get_embedding_dimension", None) or getattr(
                self._model, "get_sentence_embedding_dimension"
            )
            self._dim = int(dim_fn())
        return self._model

    @property
    def dim(self) -> int:
        """向量维度。"""
        self.model
        return self._dim

    # ------------------------------------------------------------------
    # 向量化
    # ------------------------------------------------------------------
    def embed(self, texts: list[str]) -> np.ndarray:
        """批量向量化并 L2 归一化，返回 float32 二维数组。"""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self.model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """单条查询向量化（同样归一化，便于点积相似度）。

        对 bge 中文模型应用官方查询侧指令前缀（s2p 检索推荐），
        提升 query 与候选文本的语义对齐。
        """
        if "bge" in settings.EMBEDDING_MODEL.lower() and not text.startswith(BGE_ZH_QUERY_PREFIX):
            text = BGE_ZH_QUERY_PREFIX + text
        return self.embed([text])[0]

    # ------------------------------------------------------------------
    # FAISS 索引读写
    # ------------------------------------------------------------------
    def build_index(self, vectors: np.ndarray) -> faiss.Index:
        """构建内积相似度索引（配合归一化向量即余弦相似度）。"""
        index = faiss.IndexFlatIP(self.dim)
        index.add(vectors)
        return index

    def save_index(self, index: faiss.Index, path: str | Path) -> None:
        faiss.write_index(index, str(path))
        logger.info("FAISS 索引已保存: %s", path)

    def load_index(self, path: str | Path) -> faiss.Index:
        return faiss.read_index(str(path))

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, index: faiss.Index, query: str, k: int = 5) -> list[tuple[float, int]]:
        """返回 [(score, position), ...]，position 即该条在 metadata/id_map 中的下标。"""
        vec = self.embed_query(query).reshape(1, -1)
        scores, indices = index.search(vec, k)
        return [
            (float(score), int(pos))
            for score, pos in zip(scores[0], indices[0])
            if pos >= 0
        ]

    # ------------------------------------------------------------------
    # 元数据辅助
    # ------------------------------------------------------------------
    def load_metadata(self, path: str | Path) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)


def get_embedding_model() -> EmbeddingModel:
    """获取全局 embedding 模型单例。"""
    return EmbeddingModel()
