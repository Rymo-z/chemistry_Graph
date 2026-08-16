"""config.py 的示例数据模式（USE_SAMPLE_DATA）单元测试。

直接构造独立 `Settings()`（不经 lru_cache 单例，避免环境变量污染全局），
验证目录切换逻辑。注意：Settings.__init__ 会 _ensure_dirs() 真实 mkdir
（与日常 import config 的副作用一致），sample_data/{extract,faiss} 属预期。
"""
from __future__ import annotations

import pytest

from common.config import BASE_DIR, Settings


def test_full_mode_default_dirs(monkeypatch):
    """默认（未设置 USE_SAMPLE_DATA）指向正式数据/抽取/索引目录。"""
    monkeypatch.delenv("USE_SAMPLE_DATA", raising=False)
    s = Settings()
    assert s.USE_SAMPLE_DATA is False
    assert s.CLAWLER_DATA_DIR == BASE_DIR / "_001_clawler" / "data"
    assert s.EXTRACT_OUTPUT_DIR == BASE_DIR / "_002_extract_information" / "output"
    assert s.STORAGE_DIR == BASE_DIR / "_003_create_neo4j_database" / "storage"


def test_sample_mode_dirs(monkeypatch):
    """USE_SAMPLE_DATA=1 指向 sample_data/ 变体目录。"""
    monkeypatch.setenv("USE_SAMPLE_DATA", "1")
    s = Settings()
    assert s.USE_SAMPLE_DATA is True
    assert s.CLAWLER_DATA_DIR == BASE_DIR / "sample_data"
    assert s.EXTRACT_OUTPUT_DIR == BASE_DIR / "sample_data" / "extract"
    assert s.STORAGE_DIR == BASE_DIR / "sample_data" / "faiss"
    # 非数据目录不受运行模式影响
    assert s.LOGS_DIR == BASE_DIR / "logs"
    assert s.TMP_DIR == BASE_DIR / "tmp"


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "True"])
def test_sample_mode_truthy_values(monkeypatch, raw):
    """各种真值写法均解析为 True。"""
    monkeypatch.setenv("USE_SAMPLE_DATA", raw)
    assert Settings().USE_SAMPLE_DATA is True


@pytest.mark.parametrize("raw", ["0", "false", "no", ""])
def test_sample_mode_falsy_values(monkeypatch, raw):
    """假值写法解析为 False。"""
    monkeypatch.setenv("USE_SAMPLE_DATA", raw)
    assert Settings().USE_SAMPLE_DATA is False
