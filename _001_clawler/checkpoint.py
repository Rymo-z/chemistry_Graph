"""断点续爬（checkpoint）模块。

把已抓取的 URL 集合持久化到本地 JSON 文件，配合爬虫实现：
- **断点续爬**：中断后重跑，已完成的条目自动跳过，只补抓增量。
- **去重**：同一 URL 不重复抓取（幂等）。
- **统计**：已处理 / 成功 / 失败计数，便于监控进度。

约定：checkpoint 文件与数据同目录，`data/{category}/crawl_state.json`。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from common.logger import get_logger

logger = get_logger(__name__)


class CrawlState:
    """基于 JSON 的断点续爬状态（线程安全）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.done: set[str] = set()      # 已成功保存的 URL
        self.failed: dict[str, str] = {}  # 失败 URL -> 错误信息
        self._load()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def is_done(self, url: str) -> bool:
        return url in self.done

    @property
    def done_count(self) -> int:
        return len(self.done)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------
    def mark_done(self, url: str) -> None:
        with self._lock:
            self.done.add(url)
            self.failed.pop(url, None)
            self._save()

    def mark_failed(self, url: str, error: str) -> None:
        with self._lock:
            if url not in self.done:  # 已成功的不用再记失败
                self.failed[url] = error
            self._save()

    def reset(self) -> None:
        """清空所有状态（配合 --force 强制重抓）。"""
        with self._lock:
            self.done.clear()
            self.failed.clear()
            self._save()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.done = set(raw.get("done", []))
            self.failed = raw.get("failed", {})
            logger.info(
                "加载断点状态: %s (done=%d failed=%d)",
                self.path, len(self.done), len(self.failed),
            )
        except Exception as exc:
            logger.warning("断点文件读取失败(%s)，从零开始: %s", self.path, exc)

    def _save(self) -> None:
        """每次变更立即落盘，最大化断点可靠性。"""
        try:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "done": sorted(self.done),
                        "failed": self.failed,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as exc:
            logger.error("断点状态保存失败: %s", exc)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CrawlState done={len(self.done)} failed={len(self.failed)}>"
