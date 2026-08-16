"""robots.txt 合规守卫。

基于标准库 `urllib.robotparser`，为每个域名缓存 robots.txt 解析结果：
- 站点存在 robots.txt 时严格按其 Disallow 规则放行/拦截；
- 站点不存在 robots.txt（如 mem.gov.cn）时启用保守默认：允许但建议限速，
  并记录「无规则」状态供调用方做更保守的节奏控制。

设计目标：**零违规操作** —— 爬虫绝不访问 robots.txt 明确禁止的路径。
"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from common.logger import get_logger

logger = get_logger(__name__)

# 统一的爬虫身份标识（合规：自报身份，便于站点联系）
CRAWLER_UA = (
    "ChemSafetyDataCollector/1.0 "
    "(data collection for safety-regulation QA research; "
    "contact: https://github.com/<your-repo>)"
)


class RobotsTxtGuard:
    """按域名缓存 robots.txt，提供路径放行判断。"""

    def __init__(self, user_agent: str = CRAWLER_UA, *, fetch_timeout: int = 10) -> None:
        self.user_agent = user_agent
        self.fetch_timeout = fetch_timeout
        self._cache: dict[str, RobotFileParser] = {}
        self._known_missing: set[str] = set()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def is_allowed(self, url: str) -> bool:
        """判断给定 URL 是否允许抓取。

        - 有 robots.txt：严格按其规则放行（.can_fetch）。
        - 无 robots.txt：默认放行（标记 missing），由限速层兜底。
        """
        host = self._host_of(url)
        parser = self._get_parser(host)
        if parser is None:  # 站点无 robots.txt，默认放行
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:  # 解析异常时保守处理：禁止抓取
            logger.warning("robots 判断异常，保守拒绝: %s", url)
            return False

    def has_robots(self, url: str) -> bool:
        """该站点是否提供了 robots.txt。"""
        return self._get_parser(self._host_of(url)) is not None

    def missing_robots_hosts(self) -> set[str]:
        """无 robots.txt 的域名集合，供调用方决定是否加强限速。"""
        return set(self._known_missing)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _host_of(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _get_parser(self, host: str) -> RobotFileParser | None:
        """获取域名对应的 RobotFileParser；无 robots.txt 返回 None（缓存结果）。"""
        if host in self._cache:
            return self._cache[host]
        if host in self._known_missing:
            return None

        parser = RobotFileParser()
        robots_url = f"https://{host}/robots.txt"
        try:
            import urllib.request

            req = urllib.request.Request(
                robots_url,
                headers={"User-Agent": self.user_agent},
            )
            with urllib.request.urlopen(req, timeout=self.fetch_timeout) as resp:
                if resp.status == 200:
                    parser.parse(resp.read().decode("utf-8", errors="replace").splitlines())
                    self._cache[host] = parser
                    logger.info("已缓存 robots.txt: %s (%s 条规则)", robots_url, len(parser.allow_entry) + len(parser.disallow_entry))
                    return parser
                # 非 200（如 404）视为无规则
                self._known_missing.add(host)
                logger.info("站点无 robots.txt 或不可解析: %s", robots_url)
                return None
        except Exception as exc:  # 网络异常等：视为无规则，不阻断采集，但记录
            self._known_missing.add(host)
            logger.debug("robots.txt 获取失败(%s)，按无规则处理: %s", exc, robots_url)
            return None


# 进程级单例，避免重复请求各站点 robots.txt
@lru_cache(maxsize=1)
def get_robots_guard() -> RobotsTxtGuard:
    return RobotsTxtGuard()
