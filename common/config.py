"""统一配置模块：读取 .env，提供 BASE_DIR 及所有路径（单例）。

一切外部依赖（LLM / Neo4j / Embedding / YOLO / 服务端口）的取值均集中于此，
切换环境只需修改 `.env`，业务代码零改动。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：common/config.py -> 项目根
BASE_DIR: Path = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


class Settings:
    """集中管理全部环境变量与目录路径。"""

    def __init__(self) -> None:
        # ---------- 大模型 LLM ----------
        self.LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        self.LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        self.LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))
        # deepseek 等推理模型会把输出 token 全部烧在 reasoning_content 上，导致
        # content 为空（抽取等任务必然触发）。默认关闭思考以获得确定性的直接输出。
        self.LLM_DISABLE_THINKING: bool = os.getenv("LLM_DISABLE_THINKING", "true").lower() in (
            "1", "true", "yes",
        )

        # ---------- Neo4j ----------
        self.NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
        self.NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "please-change-me")
        self.NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")

        # ---------- Embedding + FAISS ----------
        self.EMBEDDING_MODEL: str = os.getenv(
            "EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
        )
        self.FAISS_INDEX_NAME: str = os.getenv("FAISS_INDEX_NAME", "regulation_index.faiss")
        self.FAISS_META_NAME: str = os.getenv("FAISS_META_NAME", "metadata.json")
        self.FAISS_MAP_NAME: str = os.getenv("FAISS_MAP_NAME", "id_map.pkl")

        # ---------- CV (YOLOv8) ----------
        self.YOLO_MODEL_PATH: str = os.getenv("YOLO_MODEL_PATH", "")
        self.YOLO_MODEL_NAME: str = os.getenv("YOLO_MODEL_NAME", "yolov8n.pt")

        # ---------- 服务 ----------
        self.API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
        self.API_PORT: int = int(os.getenv("API_PORT", "8000"))
        self.STREAMLIT_PORT: int = int(os.getenv("STREAMLIT_PORT", "8501"))
        self.API_BASE: str = os.getenv("API_BASE", "http://127.0.0.1:8000")
        self.APP_NAME: str = "化工安全生产合规智能体"

        # ---------- 运行模式 ----------
        # 示例数据模式（USE_SAMPLE_DATA=1）：数据/抽取/索引目录指向 sample_data/，
        # 新用户 clone 后无需完整爬取数据即可体验 RAG demo（见 scripts/make_sample_data.py）。
        self.USE_SAMPLE_DATA: bool = os.getenv("USE_SAMPLE_DATA", "false").lower() in (
            "1", "true", "yes",
        )

        # ---------- 目录路径 ----------
        if self.USE_SAMPLE_DATA:
            self.CLAWLER_DATA_DIR: Path = BASE_DIR / "sample_data"
            self.EXTRACT_OUTPUT_DIR: Path = BASE_DIR / "sample_data" / "extract"
            self.STORAGE_DIR: Path = BASE_DIR / "sample_data" / "faiss"
        else:
            self.CLAWLER_DATA_DIR: Path = BASE_DIR / "_001_clawler" / "data"
            self.EXTRACT_OUTPUT_DIR: Path = BASE_DIR / "_002_extract_information" / "output"
            self.STORAGE_DIR: Path = BASE_DIR / "_003_create_neo4j_database" / "storage"
        self.LOGS_DIR: Path = BASE_DIR / "logs"
        self.TMP_DIR: Path = BASE_DIR / "tmp"

        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """确保关键目录存在，避免运行期 FileNotFoundError。"""
        for directory in (
            self.CLAWLER_DATA_DIR,
            self.EXTRACT_OUTPUT_DIR,
            self.STORAGE_DIR,
            self.LOGS_DIR,
            self.TMP_DIR,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级单例。"""
    return Settings()


settings: Settings = get_settings()
