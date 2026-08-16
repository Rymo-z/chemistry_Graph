"""数据/输出目录快速获取函数。

供各业务层统一获取路径，避免到处拼 Path。
"""
from __future__ import annotations

from pathlib import Path

from common.config import settings


def get_crawler_data_dir(sub_dir: str | None = None) -> Path:
    """原始数据根目录；传 sub_dir 可进入子目录，如 'regulations'。"""
    base = settings.CLAWLER_DATA_DIR
    return base / sub_dir if sub_dir else base


def get_regulations_dir() -> Path:
    """法规原文存放目录。"""
    return get_crawler_data_dir("regulations")


def get_accidents_dir() -> Path:
    """事故案例存放目录。"""
    return get_crawler_data_dir("accidents")


def get_internal_docs_dir() -> Path:
    """企业内部制度文档存放目录。"""
    return get_crawler_data_dir("internal_docs")


def get_extract_output_dir() -> Path:
    """抽取结果 JSON 输出目录。"""
    return settings.EXTRACT_OUTPUT_DIR


def get_storage_dir() -> Path:
    """FAISS 索引 / pkl 映射 / metadata.json 存放目录。"""
    return settings.STORAGE_DIR


def get_logs_dir() -> Path:
    """日志目录。"""
    return settings.LOGS_DIR


def get_tmp_dir() -> Path:
    """临时文件目录（如上传图片缓存）。"""
    return settings.TMP_DIR
