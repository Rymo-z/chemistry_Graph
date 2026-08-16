"""统一日志配置：同时输出到控制台与 logs/app.log。

用法：`logger = get_logger(__name__)`，无需重复配置 handler。
"""
from __future__ import annotations

import logging
from typing import Optional

from common.config import settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_root_logger: Optional[logging.Logger] = None


def _ensure_handlers() -> logging.Logger:
    """确保根 logger 已挂载 控制台 + 文件 双 handler（幂等）。"""
    global _root_logger
    if _root_logger is not None:
        return _root_logger

    logger = logging.getLogger("chem_safety")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # 避免重复输出

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件 handler（logs/app.log）
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(settings.LOGS_DIR / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _root_logger = logger
    return logger


def get_logger(name: str = "chem_safety") -> logging.Logger:
    """获取（并复用）统一配置的 logger。

    Args:
        name: 模块名，通常传 `__name__`，会作为子 logger 展示。
    """
    root = _ensure_handlers()
    return root.getChild(name) if name and name != "chem_safety" else root
