"""法规标准爬取 —— 应急管理部官网（mem.gov.cn）实现。

抓取范围：`规范性文件` 栏目（https://www.mem.gov.cn/fw/flfgbz/gfxwj/）。

数据特征（2026-08 探查确认）：
- 列表 8 页（分页 URL：`index.shtml`、`index_N.shtml`），每页约 20 条。
- 文章页有两种模板：
  1. **政府信息公开** `/gk/zfxxgkpt/fdzdgknr/...shtml`
     正文 `<div id='content'>`，元数据 `.scy_main_detail` 表格。
  2. **通知公告** `/gk/tzgg/...shtml`
     正文 `<div class='TRS_Editor'>`，元数据 `.youbiaodc_ind01`。

合规/健壮性（继承 BaseCrawler）：
- robots.txt 拦截、随机间隔限速、指数退避重试。
- 断点续爬 + 去重（checkpoint 文件 + 原始文件存在性双保险）。
- 单条失败不中断，记日志继续；汇总成功率。

输出：
- `data/regulations/raw/{article_id}.html`   原始页面（保留取证）
- `data/regulations/structured.jsonl`        规范化记录（每行一条 JSON）
- `data/regulations/crawl_state.json`         断点状态
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from _001_clawler.base_crawler import BaseCrawler
from _001_clawler.checkpoint import CrawlState
from common.config import BASE_DIR, settings
from common.logger import get_logger

logger = get_logger(__name__)

SOURCE_SITE = "mem.gov.cn"
CATEGORY = "规范性文件"

# 机关文号：应急〔2020〕84号 / 安委办﹝2018﹞15号 / 应急厅函﹝2019﹞548号
# 兼容：全角括号 ﹝﹞、序号内空格（如 "3 1 号"）、机关名与括号间换行（正文每段一行，
# 文号常被 <p>/<br> 拆行，如 "安委办\n﹝\n2018\n﹞\n15\n号"）
_DOC_NO_RE = re.compile(
    r"([^\s，。；、]{1,15}?)\s*([〔﹝(\[])\s*(\d{4})\s*([〕﹞)\]])\s*([\d\s　]{1,8}?)\s*号"
)
# 公告文号：应急管理部公告（2019年 第11号），容忍机关名/字间空格（"公 告"）
_GAOGAO_RE = re.compile(
    r"([一-龥]{2,25}?)\s*公\s*告\s*[（(]?\s*(\d{4})\s*年?\s*第\s*(\d{1,3})\s*号"
)
_DATE_RE = re.compile(r"(\d{4})年?[-/年](\d{1,2})[-/月](\d{1,2})日?")


class RegulationCrawler(BaseCrawler):
    """抓取应急管理部官网规范性文件。"""

    LIST_BASE = "https://www.mem.gov.cn/fw/flfgbz/gfxwj/"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            base_url=self.LIST_BASE,
            min_interval=kwargs.pop("min_interval", 1.5),
            max_interval=kwargs.pop("max_interval", 3.5),
            **kwargs,
        )
        self.data_dir: Path = settings.CLAWLER_DATA_DIR / "regulations"
        self.raw_dir: Path = self.data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.structured_path: Path = self.data_dir / "structured.jsonl"
        self.state = CrawlState(self.data_dir / "crawl_state.json")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def crawl(
        self,
        *,
        max_pages: int = 0,
        limit: int = 0,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """批量抓取规范性文件。

        Args:
            max_pages: 最多抓取列表页数（0 = 全部）。
            limit: 最多抓取文章条数（0 = 不限）。
            force: True 时忽略断点，重新抓取（会覆盖原始文件）。
        Returns:
            本次成功抓取的规范化记录列表。
        """
        if force:
            # 强制重抓：清空断点与结构化产物，避免重复追加
            for p in self.raw_dir.glob("*.html"):
                p.unlink(missing_ok=True)
            if self.structured_path.exists():
                self.structured_path.unlink()
            self.state.reset()

        urls = self._discover_article_urls(max_pages=max_pages)
        logger.info("发现候选法规 %d 条（限抓 %s 条）", len(urls), limit or "不限")

        records: list[dict[str, Any]] = []
        for url in urls:
            if limit and len(records) >= limit:
                logger.info("已达 limit=%d，停止", limit)
                break
            article_id = self._article_id(url)
            raw_path = self.raw_dir / f"{article_id}.html"
            if not force and (self.state.is_done(url) or raw_path.exists()):
                logger.debug("跳过已抓取: %s", article_id)
                continue

            try:
                html = self.fetch(url)
            except PermissionError:
                logger.warning("robots 拦截，中止本次运行: %s", url)
                break
            except StopIteration:
                logger.warning("已达请求数安全阀，中止本次运行")
                break
            except Exception as exc:
                logger.error("抓取失败 %s: %s", url, exc)
                self.state.mark_failed(url, str(exc))
                continue

            record = self._parse_article(url, html)
            if record is None:
                logger.warning("解析失败，跳过 %s", url)
                self.state.mark_failed(url, "parse returned None")
                continue

            self._store(record, html, raw_path)
            self.state.mark_done(url)
            records.append(record)
            logger.info(
                "已保存 [%d] %s | %s", len(records), record.get("doc_no") or "-", record["title"][:40]
            )

        ok = len(records)
        fail = self.state.failed_count
        logger.info("抓取完成：成功 %d，失败 %d，已抓取累计 %d", ok, fail, self.state.done_count)
        return records

    # ------------------------------------------------------------------
    # 列表页发现
    # ------------------------------------------------------------------
    def _discover_article_urls(self, *, max_pages: int = 0) -> list[str]:
        """从列表页收集文章 URL（含分页）。"""
        urls: list[str] = []
        first = self._fetch_list_page(self.LIST_BASE)
        urls.extend(first["urls"])
        total_pages = first["total_pages"]

        pages = min(total_pages, max_pages) if max_pages else total_pages
        for page in range(2, pages + 1):
            page_url = self.LIST_BASE if page == 1 else f"{self.LIST_BASE}index_{page}.shtml"
            info = self._fetch_list_page(page_url)
            urls.extend(info["urls"])
        # 去重保序
        return list(dict.fromkeys(urls))

    def _fetch_list_page(self, url: str) -> dict[str, Any]:
        """抓取单个列表页，返回 {urls, total_pages}。"""
        try:
            html = self.fetch(url)
        except PermissionError:
            logger.warning("robots 拦截列表页: %s", url)
            return {"urls": [], "total_pages": 1}
        except Exception as exc:
            logger.error("列表页抓取失败 %s: %s", url, exc)
            return {"urls": [], "total_pages": 1}

        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        for a in soup.find_all("a", href=lambda h: h and "/gk/" in h and ".shtml" in h):
            href = urljoin(url, a["href"])
            if "/gk/" in href and href not in urls:
                urls.append(href)
        total_pages = self._parse_total_pages(html)
        logger.info("列表页 %s -> 文章 %d 条, 共 %d 页", url.split("/")[-1], len(urls), total_pages)
        return {"urls": urls, "total_pages": total_pages}

    @staticmethod
    def _parse_total_pages(html: str) -> int:
        """从列表页 JS 中解析 `countPage = N`。"""
        m = re.search(r"countPage\s*=\s*(\d+)", html)
        return int(m.group(1)) if m else 1

    # ------------------------------------------------------------------
    # 文章解析（双模板）
    # ------------------------------------------------------------------
    def _parse_article(self, url: str, html: str) -> Optional[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        record: dict[str, Any] = {
            "title": "",
            "doc_no": "",
            "category": CATEGORY,
            "publish_date": "",
            "issuing_org": "",
            "index_no": "",
            "doc_type": "",
            "sign_date": "",
            "belong_org": "",
            "topic_category": "",
            "status": "现行",
            "content": "",
            "url": url,
            "source_site": SOURCE_SITE,
        }

        if "/fdzdgknr/" in url:
            self._parse_fdzdgknr(soup, record)
        elif "/tzgg/" in url:
            self._parse_tzgg(soup, record)
        else:
            # 兜底：title + 任意大文本容器
            record["title"] = self._clean_title(soup.title.get_text(strip=True) if soup.title else "")
            body = soup.find(id="content") or soup.select_one(".TRS_Editor") or soup.body
            record["content"] = self._clean_text(body.get_text("\n")) if body else ""

        # 归一化标题：去掉站点后缀
        record["title"] = self._clean_title(record["title"])
        record["content"] = record["content"].strip()
        if not record["title"] or len(record["content"]) < 10:
            logger.warning("文章内容过短或标题缺失: %s", url)
            return None
        return record

    def _parse_fdzdgknr(self, soup: BeautifulSoup, record: dict[str, Any]) -> None:
        """政府信息公开模板：#content + .scy_main_detail 表格。"""
        body = soup.find(id="content") or soup.select_one(".scy_detail_bottom")
        if body:
            record["content"] = self._clean_text(body.get_text("\n"))

        meta = soup.select_one(".scy_main_detail")
        if meta:
            label_to_key = {
                "标题": "title",
                "索引号": "index_no",
                "发文字号": "doc_no",
                "发文单位": "issuing_org",
                "所属机构": "belong_org",
                "主题分类": "topic_category",
                "公文种类": "doc_type",
                "成文日期": "sign_date",
                "发布日期": "publish_date",
            }
            for tr in meta.find_all("tr"):
                cells = [c.get_text(strip=True).rstrip("：:") for c in tr.find_all("td")]
                # 表格为成对单元格：标签 | 值（可能一行多对）
                for i in range(0, len(cells) - 1, 2):
                    key = label_to_key.get(cells[i])
                    if key and cells[i + 1]:
                        record[key] = cells[i + 1]
            # 有的模板用 font 标注标签而非 td
            for lab in meta.find_all("font"):
                text = lab.get_text(strip=True).rstrip("：:")
                key = label_to_key.get(text)
                if key and not record.get(key):
                    val = lab.parent.get_text(strip=True).replace(text, "", 1).lstrip("：:")
                    if val:
                        record[key] = val

        # 标题优先取 <title> 标签（完整），元数据表格的标题单元格有时不完整
        if soup.title and soup.title.get_text(strip=True):
            record["title"] = self._clean_title(soup.title.get_text(strip=True))
        # 日期归一化：2026年05月22日 -> 2026-05-22
        record["publish_date"] = self._normalize_date(record.get("publish_date", ""))
        record["sign_date"] = self._normalize_date(record.get("sign_date", ""))
        # 元数据表格的文号偶尔自带空格（如「应急厅函〔2022〕317 号」），去空白统一格式
        record["doc_no"] = self._normalize_doc_no(record.get("doc_no", ""))
        # 发文字号兜底：从正文提取
        if not record["doc_no"]:
            record["doc_no"] = self._extract_doc_no(record["content"], record.get("title", ""))

    def _parse_tzgg(self, soup: BeautifulSoup, record: dict[str, Any]) -> None:
        """通知公告模板：.TRS_Editor + .youbiaodc_ind01。"""
        body = soup.select_one(".TRS_Editor") or soup.select_one(".zhenwen_neir")
        if body:
            record["content"] = self._clean_text(body.get_text("\n"))

        head = soup.select_one(".youbiaodc_ind01") or soup.select_one(".cont")
        if head:
            head_text = head.get_text(" ", strip=True)
            m = _DATE_RE.search(head_text)
            if m:
                record["publish_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            src = re.search(r"来源[:：]\s*([^\s|]+)", head_text)
            if src:
                record["issuing_org"] = src.group(1).strip()

        if not record["title"] and soup.title:
            record["title"] = self._clean_title(soup.title.get_text(strip=True))
        record["doc_no"] = self._extract_doc_no(record["content"], record.get("title", ""))
        if not record["publish_date"]:
            m = _DATE_RE.search(record["content"])
            if m:
                record["publish_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------
    def _store(self, record: dict[str, Any], html: str, raw_path: Path) -> None:
        """写原始 HTML + 追加结构化 JSONL（幂等）。"""
        raw_path.write_text(html, encoding="utf-8")
        record["raw_file"] = str(raw_path.relative_to(BASE_DIR)).replace("\\", "/")
        with open(self.structured_path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _article_id(url: str) -> str:
        m = re.search(r"t(\d{8})_\d+", url)
        if m:
            return m.group(1)
        return re.sub(r"[^0-9a-zA-Z]+", "_", url)[-40:]

    @staticmethod
    def _clean_title(title: str) -> str:
        """去掉站点后缀、规整空白（仅清理结尾，避免误删标题正文中的部门名）。"""
        for suffix in (
            "--中华人民共和国应急管理部",
            "_中华人民共和国应急管理部",
            "--应急管理部",
            "---应急管理部",
        ):
            if title.endswith(suffix):
                title = title[: -len(suffix)]
                break
        # 规整 \xa0 /   / 连续空格 等空白字符
        title = re.sub(r"[\xa0  　]+", " ", title)
        title = re.sub(r"\s{2,}", " ", title)
        return title.strip()

    @staticmethod
    def _clean_text(text: str) -> str:
        """清洗正文：压缩空白、去掉空行。"""
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    @staticmethod
    def _normalize_doc_no(value: str) -> str:
        """去掉文号中的空白（元数据表格常带多余空格，如「317 号」）。"""
        return re.sub(r"[\s　]+", "", value)

    @staticmethod
    def _normalize_date(value: str) -> str:
        """2026年05月22日 -> 2026-05-22；无法识别返回原值。"""
        if not value:
            return ""
        m = _DATE_RE.search(value)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return value.strip()

    @staticmethod
    def _extract_doc_no(content: str, title: str = "") -> str:
        """从正文开头提取发文字号；公告类从标题兜底。

        文号紧跟标题出现（规范性文件惯例），故只搜正文前 150 字，
        避免误抓正文引用的其他文件文号（如 引用的《...》国办发〔2018〕47号）。
        """
        if not content:
            return ""
        head = content[:150]

        # 1) 公告文号：如 应急管理部公告（2019年 第11号）
        m = _GAOGAO_RE.search(head) or _GAOGAO_RE.search(title)
        if m:
            return f"{m.group(1)}公告（{m.group(2)}年 第{m.group(3)}号）"

        # 2) 机关文号：如 应急〔2020〕84号 / 应急厅函﹝2019﹞548号
        m = _DOC_NO_RE.search(head)
        if m:
            org, left, year, right, num = m.groups()
            num = re.sub(r"[\s　]+", "", num)  # 序号内空格 → 去掉（如 "3 1" → "31"）
            return f"{org}{left}{year}{right}{num}号"
        return ""

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------
    def crawl_regulation_by_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """按关键词抓取（当前为全量抓取后过滤，后续可对接站内搜索）。"""
        records = self.crawl()
        if not keyword:
            return records
        matched = [r for r in records if keyword in r["title"] or keyword in r["content"]]
        logger.info("关键词 %s 命中 %d 条", keyword, len(matched))
        return matched
