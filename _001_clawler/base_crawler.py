"""通用爬虫基类：请求重试、HTML/JSON 解析、礼貌等待、robots 合规。

子类只需实现 `crawl()` 并复用 `fetch/save_*` 即可完成采集，
统一内置：指数退避重试、随机间隔限速、编码探测、robots.txt 合规、请求数安全阀。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from _001_clawler.robots import get_robots_guard
from common.logger import get_logger

logger = get_logger(__name__)


class BaseCrawler:
    """所有爬虫的基类。"""

    def __init__(
        self,
        *,
        base_url: str = "",
        timeout: int = 30,
        max_retries: int = 3,
        min_interval: float = 1.0,
        max_interval: float = 3.0,
        headers: Optional[dict[str, str]] = None,
        max_requests: int = 0,  # 0 = 不限制；>0 = 单次运行请求数上限（安全阀）
        respect_robots: bool = True,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.max_requests = max_requests
        self.request_count = 0
        self.respect_robots = respect_robots
        self.robots = get_robots_guard()
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (compatible; ChemSafetyAgent/1.0; +data-collection)",
            "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        self.session = self._build_session(max_retries)

    # ------------------------------------------------------------------
    # 基础设施
    # ------------------------------------------------------------------
    def _build_session(self, max_retries: int) -> requests.Session:
        """构建带指数退避重试的 HTTP 会话。"""
        retry = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _wait(self) -> None:
        """礼貌等待：随机间隔，避免对目标服务器造成压力。"""
        import random
        import time

        time.sleep(random.uniform(self.min_interval, self.max_interval))

    # ------------------------------------------------------------------
    # 请求与保存
    # ------------------------------------------------------------------
    def fetch(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        as_json: bool = False,
        encoding: str | None = None,
    ) -> Any:
        """GET 请求，返回 HTML 文本或 JSON 对象。失败时抛 requests 异常。

        合规内建：
        - robots.txt 拦截：目标 URL 不在允许范围时抛 `PermissionError`。
        - 请求数安全阀：`max_requests > 0` 且已达上限时抛 `StopIteration`。
        """
        if self.request_count >= self.max_requests > 0:
            raise StopIteration(f"已达本次运行请求数上限 {self.max_requests}")

        if self.respect_robots and not self.robots.is_allowed(url):
            logger.warning("robots.txt 禁止访问，跳过: %s", url)
            raise PermissionError(f"robots.txt 禁止访问: {url}")

        self._wait()
        self.request_count += 1
        response = self.session.get(
            url, params=params, timeout=self.timeout, headers=self.headers
        )
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        else:
            response.encoding = response.apparent_encoding or "utf-8"
        logger.debug("GET %s -> %s", response.url, response.status_code)
        return response.json() if as_json else response.text

    def fetch_bytes(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> bytes:
        """GET 二进制响应（PDF 等附件下载）。合规控制与 `fetch` 一致。

        返回 `resp.content`（bytes），不设置 encoding。
        失败时抛 requests 异常；robots 拦截抛 `PermissionError`；安全阀抛 `StopIteration`。
        """
        if self.request_count >= self.max_requests > 0:
            raise StopIteration(f"已达本次运行请求数上限 {self.max_requests}")

        if self.respect_robots and not self.robots.is_allowed(url):
            logger.warning("robots.txt 禁止访问，跳过: %s", url)
            raise PermissionError(f"robots.txt 禁止访问: {url}")

        self._wait()
        self.request_count += 1
        response = self.session.get(
            url, params=params, timeout=self.timeout, headers=self.headers
        )
        response.raise_for_status()
        logger.debug("GET(binary) %s -> %s (%d bytes)", response.url, response.status_code, len(response.content))
        return response.content

    def save_text(self, content: str, path: str | Path) -> Path:
        """保存原始文本（法规原文/事故报告正文）。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("文本已保存: %s (%d 字符)", path, len(content))
        return path

    def save_json(self, data: dict[str, Any], path: str | Path) -> Path:
        """保存结构化数据。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        logger.info("JSON 已保存: %s", path)
        return path

    # ------------------------------------------------------------------
    # 子类实现入口
    # ------------------------------------------------------------------
    def crawl(self) -> list[dict[str, Any]]:
        """子类实现的采集入口，返回结构化记录列表。"""
        raise NotImplementedError("子类必须实现 crawl()")
