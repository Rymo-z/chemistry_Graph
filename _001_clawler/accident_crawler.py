"""事故案例爬取 —— 应急管理部「特别重大事故调查报告」实现。

抓取范围：https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/（特别重大事故调查报告）。

数据特征（2026-08 侦察确认）：
- 列表按**年份子目录**分页（命名无规律，如 `2025dcbg_6344/`、`2019tbzdsgcc/`、
  `2003/`），需从索引页 href 动态收集，不能硬编码。
- 详情页两套模板：
  1. 新模板 `/gk/zfxxgkpt/fdzdgknr/{yyyymm}/t{yyyymmdd}_{id}.shtml`
     元数据 `.scy_main_detail` 表格 + PDF 附件链接（`W020…pdf` 原文版 / `P020…pdf` 下载版）。
  2. 旧模板 `./{yyyymm}/t{yyyymmdd}_{id}.shtml`，仅标题 + PDF 链接。
- 报告全文在 **PDF 附件**（FlateDecode 数字文本，非扫描件），用 `pypdf` 抽取。

合规/健壮性（继承 BaseCrawler）：
- robots.txt 拦截、随机间隔限速、指数退避重试、请求数安全阀。
- 断点续爬 + 去重（checkpoint 文件 + 原始文件存在性双保险）。
- 单条失败不中断，记日志继续；PDF 下载失败不阻塞详情页元数据入库。
- 来源为应急管理部官网公开政务信息，无需登录、无 robots 限制。

输出：
- `data/accidents/raw/mem_{article_id}.shtml`   详情页原始 HTML（取证）
- `data/accidents/pdfs/mem_{article_id}.pdf`     报告 PDF 全文
- `data/accidents/structured.jsonl`              规范化记录（P1 schema，每行一条 JSON）
- `data/accidents/crawl_state.json`              断点状态
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
CATEGORY = "事故调查报告"
INDEX_URL = "https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/"

# 年份子目录：href 形如 "./2025dcbg_6344/" 或 "2023dcbg_5532/"（无规律命名）
_YEAR_DIR_RE = re.compile(r"^(?:\./)?\d{4}[a-z0-9_]*/$")
# 详情页：新旧两套路径均含 t{yyyymmdd}_{id}.shtml
_ARTICLE_RE = re.compile(r"t\d{8}_\d+.*\.shtml$")
# PDF 附件：原文版 W020 优先，下载版 P020 次之
_PDF_FILE_RE = re.compile(r"(W020|P020)", re.I)

# 元数据表（新模板 `.scy_main_detail`）标签 → 字段
META_LABEL_MAP: dict[str, str] = {
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

# 化工相关关键词：用于 is_chemical 标记（best-effort，宁宽勿严）
CHEM_KEYWORDS: tuple[str, ...] = (
    "化工", "化学", "石化", "炼油", "焦化", "制药", "化肥", "农药", "涂料", "油漆",
    "危化品", "危险化学品", "燃气", "天然气", "煤气", "液化气", "甲醇", "乙醇", "苯",
    "氯", "氨", "氢", "氰", "硫", "硝", "液氨", "液氯", "乙炔", "乙烯", "丙烯",
    "储罐", "罐车", "油库", "加油站", "加气站", "烟花爆竹", "民爆", "炸药", "反应釜",
)

# 事故类型分类：优先级从高到低（中毒窒息 > 爆炸 > 泄漏 > 火灾 …）
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("中毒窒息", ("中毒", "窒息")),
    ("爆炸", ("爆炸", "爆燃", "闪爆")),
    ("泄漏", ("泄漏", "泄露")),
    ("火灾", ("火灾", "燃爆")),
    ("灼烫", ("灼烫",)),
    ("高处坠落", ("高处坠落",)),
    ("触电", ("触电",)),
    ("机械伤害", ("机械伤害",)),
)

_LEVEL_RE = re.compile(r"特别重大|重大|较大|一般")
_FULL_DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_LOC_SEG_RE = re.compile(
    r"([一-龥]{2,4}?(?:省|自治区|特别行政区))|"
    r"([一-龥]{2,7}?(?:市|州|盟))|"
    r"([一-龥]{2,7}?(?:县|区|旗))"
)
_ENTERPRISE_RE = re.compile(
    r"[一-龥A-Za-z0-9]{2,30}?(?:有限责任公司|股份有限公司|有限公司|公司|化工厂|工厂|集团)"
)

# 从正文提取 cause / responsibility 的章节切分标记
_CAUSE_STARTS = ("直接原因", "间接原因")
_CAUSE_ENDS = ("责任认定", "处理建议", "整改", "防范措施")
_RESP_STARTS = ("责任认定", "对事故有关责任人员")
_RESP_ENDS = ("整改", "防范措施", "附件")

SUMMARY_LEN = 300
MIN_CONTENT_LEN = 100


class AccidentCrawler(BaseCrawler):
    """抓取应急管理部「特别重大事故调查报告」（PDF 全文）。"""

    def __init__(self, **kwargs: Any) -> None:
        # data_dir 允许注入临时目录（单元测试隔离，避免污染生产数据）
        data_dir = kwargs.pop("data_dir", None)
        super().__init__(
            base_url=INDEX_URL,
            min_interval=kwargs.pop("min_interval", 2.0),
            max_interval=kwargs.pop("max_interval", 4.0),
            **kwargs,
        )
        self.data_dir: Path = Path(data_dir or settings.CLAWLER_DATA_DIR / "accidents")
        self.raw_dir: Path = self.data_dir / "raw"
        self.pdf_dir: Path = self.data_dir / "pdfs"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.structured_path: Path = self.data_dir / "structured.jsonl"
        self.state = CrawlState(self.data_dir / "crawl_state.json")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def crawl(
        self,
        *,
        limit: int = 0,
        force: bool = False,
        download_pdf: bool = True,
    ) -> list[dict[str, Any]]:
        """批量抓取特别重大事故调查报告。

        Args:
            limit: 最多抓取条数（0 = 不限）。
            force: True 时忽略断点，重新抓取（会覆盖原始文件与 PDF）。
            download_pdf: False 时仅存详情页元数据与 PDF 链接，不下载 PDF。
        Returns:
            本次成功抓取的规范化记录列表。
        """
        if force:
            self._reset_all()

        urls = self._discover_report_urls()
        logger.info("发现事故调查报告 %d 份（限抓 %s 条）", len(urls), limit or "不限")

        records: list[dict[str, Any]] = []
        for url in urls:
            if limit and len(records) >= limit:
                logger.info("已达 limit=%d，停止", limit)
                break
            article_id = self._article_id(url)
            raw_path = self.raw_dir / f"mem_{article_id}.shtml"
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

            record = self._parse_detail(url, html)
            if record is None:
                logger.warning("解析失败，跳过 %s", url)
                self.state.mark_failed(url, "parse returned None")
                continue

            if download_pdf and record.get("pdf_url"):
                self._fill_pdf_content(record, article_id)

            self._store(record, html, raw_path)
            self.state.mark_done(url)
            records.append(record)
            logger.info(
                "已保存 [%d] %s | %s | %s | %d 字",
                len(records), record["title"][:44], record["level"] or "-",
                record["category"] or "-", record.get("content_len", 0),
            )

        ok = len(records)
        fail = self.state.failed_count
        logger.info("抓取完成：成功 %d，失败 %d，已抓取累计 %d", ok, fail, self.state.done_count)
        return records

    # ------------------------------------------------------------------
    # 报告 URL 发现（索引页 → 年份子目录 → 详情页/直链 PDF）
    # ------------------------------------------------------------------
    def _discover_report_urls(self) -> list[str]:
        """返回全量详情页 URL 与直链 PDF URL（去重保序）。"""
        urls: list[str] = []
        try:
            index_html = self.fetch(INDEX_URL)
        except PermissionError:
            logger.warning("robots 拦截索引页，中止")
            return []
        except StopIteration:
            logger.warning("已达请求数安全阀，中止")
            return []
        except Exception as exc:
            logger.error("索引页抓取失败 %s: %s", INDEX_URL, exc)
            return []

        soup = BeautifulSoup(index_html, "lxml")
        year_dirs = [
            urljoin(INDEX_URL, a["href"])
            for a in soup.find_all("a", href=True)
            if _YEAR_DIR_RE.match(a["href"].strip())
        ]
        logger.info("发现年份子目录 %d 个", len(year_dirs))

        for year_url in year_dirs:
            try:
                html = self.fetch(year_url)
            except PermissionError:
                logger.warning("robots 拦截年份目录，中止: %s", year_url)
                break
            except StopIteration:
                logger.warning("已达请求数安全阀，中止")
                break
            except Exception as exc:
                logger.error("年份目录抓取失败 %s: %s", year_url, exc)
                continue
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = urljoin(year_url, a["href"])
                if _ARTICLE_RE.search(href):
                    urls.append(href)
                elif href.lower().endswith(".pdf"):
                    urls.append(href)
        return list(dict.fromkeys(urls))

    # ------------------------------------------------------------------
    # 详情页解析（双模板）
    # ------------------------------------------------------------------
    def _parse_detail(self, url: str, html: str) -> Optional[dict[str, Any]]:
        """解析详情页 → 元数据记录（正文由 PDF 填充，见 `_fill_pdf_content`）。"""
        soup = BeautifulSoup(html, "lxml")
        record: dict[str, Any] = {
            "title": "",
            "date": "",            # 事发时间（从 PDF 正文启发式提取）
            "location": "",
            "enterprise": "",
            "level": "",
            "category": "",
            "summary": "",
            "cause": "",
            "responsibility": "",
            "content": "",
            "url": url,
            "source_site": SOURCE_SITE,
            "index_no": "",
            "doc_no": "",
            "issuing_org": "",
            "belong_org": "",
            "topic_category": "",
            "doc_type": "",
            "sign_date": "",
            "publish_date": "",
            "pdf_url": "",
            "pdf_file": "",
        }
        if soup.title and soup.title.get_text(strip=True):
            record["title"] = self._clean_title(soup.title.get_text(strip=True))

        # 新模板：元数据表 `.scy_main_detail`
        meta = soup.select_one(".scy_main_detail")
        if meta:
            for tr in meta.find_all("tr"):
                cells = [c.get_text(strip=True).rstrip("：:") for c in tr.find_all("td")]
                for i in range(0, len(cells) - 1, 2):
                    key = META_LABEL_MAP.get(cells[i])
                    if key and cells[i + 1]:
                        record[key] = cells[i + 1]
            # 部分模板用 font 标注标签
            for lab in meta.find_all("font"):
                text = lab.get_text(strip=True).rstrip("：:")
                key = META_LABEL_MAP.get(text)
                if key and not record.get(key):
                    val = lab.parent.get_text(strip=True).replace(text, "", 1).lstrip("：:")
                    if val:
                        record[key] = val

        # 标题优先取 <title> 标签（完整），元数据表「标题」单元格有时不完整
        if soup.title and soup.title.get_text(strip=True):
            record["title"] = self._clean_title(soup.title.get_text(strip=True))
        else:
            record["title"] = self._clean_title(record.get("title", ""))

        # PDF 附件链接（W020 原文版优先）
        pdfs = self._extract_pdf_links(soup, url)
        if pdfs:
            record["pdf_url"] = pdfs[0]
        else:
            # 老模板无 PDF 附件时，正文内联在 HTML（TRS CMS 的 div.TRS_Editor 等）
            inline_text = self._extract_inline_content(soup)
            if inline_text:
                record["content"] = inline_text
                record["content_len"] = len(inline_text)
                record.update(self._heuristic_fields(inline_text, record["title"]))
                logger.info("无 PDF，已提取内联正文 %d 字: %s", len(inline_text), url)

        record["sign_date"] = self._normalize_date(record.get("sign_date", ""))
        record["publish_date"] = self._normalize_date(record.get("publish_date", ""))

        if not record["title"] or (not record["pdf_url"] and not record.get("content")):
            logger.warning("详情页缺标题或全文: %s", url)
            return None
        return record

    @staticmethod
    def _extract_inline_content(soup: BeautifulSoup) -> str:
        """老模板无 PDF 附件时，从 HTML 正文容器提取内联全文（TRS CMS 等）。"""
        for selector in (".TRS_Editor", "div.content", ".content", "#zoom", ".p_content", "#UCAP-CONTENT"):
            el = soup.select_one(selector)
            if not el:
                continue
            text = el.get_text("\n", strip=True)
            if len(text) >= MIN_CONTENT_LEN:
                return text
        return ""

    @staticmethod
    def _extract_pdf_links(soup: BeautifulSoup, base_url: str) -> list[str]:
        """收集详情页 PDF 链接（绝对化、去重），原文版 W020 优先。"""
        pdfs = [
            urljoin(base_url, a["href"])
            for a in soup.find_all("a", href=True)
            if a["href"].lower().endswith(".pdf")
        ]
        pdfs = list(dict.fromkeys(pdfs))

        def sort_key(u: str) -> int:
            name = u.rsplit("/", 1)[-1]
            if _PDF_FILE_RE.search(name):
                return 0 if "W020" in name.upper() else 1
            return 2

        return sorted(pdfs, key=sort_key)

    # ------------------------------------------------------------------
    # PDF 下载与文本抽取
    # ------------------------------------------------------------------
    def _fill_pdf_content(self, record: dict[str, Any], article_id: str) -> None:
        """下载 PDF → 抽取全文 → 启发式字段。PDF 失败不阻塞详情页入库。"""
        pdf_path = self.pdf_dir / f"mem_{article_id}.pdf"
        try:
            if not self._download_pdf(record["pdf_url"], pdf_path):
                return
        except (PermissionError, StopIteration):
            raise  # 交由 crawl() 处理中止
        except Exception as exc:
            logger.error("PDF 下载异常 %s: %s", record["pdf_url"], exc)
            self.state.mark_failed(record["pdf_url"], str(exc))
            return

        record["pdf_file"] = self._rel_path(pdf_path)
        raw_text = self._extract_pdf_text(pdf_path)
        text, ocr_needed = self._clean_pdf_text(raw_text)
        record["content"] = text
        record["ocr_needed"] = ocr_needed
        record["content_len"] = len(text)
        if ocr_needed:
            logger.warning("PDF 文本疑似乱码/扫描件（CJK 占比低），保留原文: %s", pdf_path)
        record.update(self._heuristic_fields(text, record["title"]))

    def _rel_path(self, path: Path) -> str:
        """项目相对路径（生产数据在仓库内）；外部临时目录时回退为 data_dir 相对或绝对路径。"""
        for base in (BASE_DIR, self.data_dir):
            try:
                return str(path.relative_to(base)).replace("\\", "/")
            except ValueError:
                continue
        return str(path).replace("\\", "/")

    def _download_pdf(self, pdf_url: str, path: Path) -> Optional[Path]:
        """下载 PDF 到 path；失败记 mark_failed 并返回 None。"""
        try:
            data = self.fetch_bytes(pdf_url)
        except Exception as exc:
            logger.error("PDF 下载失败 %s: %s", pdf_url, exc)
            self.state.mark_failed(pdf_url, str(exc))
            return None
        path.write_bytes(data)
        logger.info("PDF 已保存: %s (%d bytes)", path, len(data))
        return path

    def _extract_pdf_text(self, path: Path) -> str:
        """用 pypdf 抽取 PDF 全文（layout 模式保留段落布局）。"""
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text(extraction_mode="layout") or "")
        return "\n".join(parts)

    @staticmethod
    def _clean_pdf_text(text: str) -> tuple[str, bool]:
        """清洗 PDF 文本，返回 (text, ocr_needed)。

        - 压缩空白、去空行；
        - 清除 CJK 逐字被插入的空格（CID 字体常见问题，如「甲 醇 泄 漏」→「甲醇泄漏」）；
        - CJK 占比 < 30% 时标记 `ocr_needed`（疑似乱码/扫描件）。
        """
        lines = [ln.strip() for ln in text.splitlines()]
        text = "\n".join(ln for ln in lines if ln)
        text = re.sub(r"(?<=[一-龥])\s+(?=[一-龥])", "", text)
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        ocr_needed = cjk / max(len(text), 1) < 0.3
        return text, ocr_needed

    # ------------------------------------------------------------------
    # 启发式字段（best-effort，空值交下游 _002 LLM 抽取）
    # ------------------------------------------------------------------
    @classmethod
    def _heuristic_fields(cls, text: str, title: str) -> dict[str, Any]:
        head = f"{title or ''}\n{text[:800]}"
        return {
            "date": cls._extract_incident_date(text, title),
            "location": cls._extract_location(head),
            "enterprise": cls._extract_enterprise(head),
            "level": cls._extract_level(f"{title or ''}\n{text[:200]}"),
            "category": cls._classify_category(head),
            "summary": cls._extract_summary(text, title),
            "cause": cls._extract_section(text, _CAUSE_STARTS, _CAUSE_ENDS),
            "responsibility": cls._extract_section(text, _RESP_STARTS, _RESP_ENDS),
            "is_chemical": any(k in head for k in CHEM_KEYWORDS),
        }

    @staticmethod
    def _extract_incident_date(text: str, title: str = "") -> str:
        """事发时间：正文首个完整日期；标题「1·24」月日 + 成文年份兜底。"""
        if text:
            m = _FULL_DATE_RE.search(text[:2000])
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if title:
            m = re.search(r"(\d{1,2})\s*[·.]\s*(\d{1,2})", title)
            if m and text:
                y = re.search(r"(\d{4})年", text[:2000])
                year = y.group(1) if y else ""
                if year:
                    return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        return ""

    @staticmethod
    def _extract_location(text: str) -> str:
        """省市县地名级联（best-effort），如「江苏省南京市六合区」→「江苏省南京市六合区」。

        对同一地区在正文中反复出现，仅保留首次出现的行政区划串，并剥掉
        「对/在/向」等介词粘连，避免输出「对宁夏回族自治区…宁夏回族自治区」。
        """
        parts = [m.group(1) or m.group(2) or m.group(3)
                 for m in _LOC_SEG_RE.finditer(text)]
        if not parts:
            return ""
        # 去重（正文常多次复述同一地名）且保持首次出现顺序；
        # 「对江西省」这类介词粘连在匹配前剥离，避免产生“对江西省…江西省”重复
        seen: list[str] = []
        for p in parts:
            p = re.sub(r"^[对在向从]", "", p)
            if p and p not in seen:
                seen.append(p)
        return "".join(seen)[:40]

    @staticmethod
    def _extract_enterprise(text: str) -> str:
        m = _ENTERPRISE_RE.search(text[:500])
        return m.group(0) if m else ""

    @staticmethod
    def _extract_level(text: str) -> str:
        m = _LEVEL_RE.search(text)
        return m.group(0) if m else ""

    @classmethod
    def _classify_category(cls, text: str) -> str:
        for cat, keys in _CATEGORY_RULES:
            if any(k in text for k in keys):
                return cat
        return ""

    @classmethod
    def _extract_summary(cls, text: str, title: str = "") -> str:
        """摘要：报告开头段落；无则首 SUMMARY_LEN 字。"""
        if not text:
            return ""
        head = text.lstrip()
        for marker in ("一、事故基本情况", "一、事故经过", "事故基本情况", "事故经过"):
            idx = head.find(marker)
            if idx > 0:
                return head[idx + len(marker): idx + len(marker) + SUMMARY_LEN].strip() \
                    or head[:SUMMARY_LEN].strip()
        return head[:SUMMARY_LEN].strip()

    @staticmethod
    def _extract_section(text: str, start_markers: tuple[str, ...], end_markers: tuple[str, ...]) -> str:
        """切取正文两个标记之间的章节文本（best-effort）。"""
        if not text:
            return ""
        start = -1
        for m in start_markers:
            idx = text.find(m)
            if idx >= 0 and (start < 0 or idx < start):
                start = idx
        if start < 0:
            return ""
        seg = text[start:]
        end = len(seg)
        for m in end_markers:
            idx = seg.find(m, len(start_markers[0]))  # 跳过起始标记自身
            if idx >= 0 and idx < end:
                end = idx
        return seg[:end].strip()[:800]

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------
    def _store(self, record: dict[str, Any], html: str, raw_path: Path) -> None:
        """写原始 HTML + 追加结构化 JSONL（幂等）。"""
        raw_path.write_text(html, encoding="utf-8")
        record["raw_file"] = self._rel_path(raw_path)
        record.setdefault("content_len", len(record.get("content", "")))
        record.setdefault("ocr_needed", False)
        with open(self.structured_path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _reset_all(self) -> None:
        """`--force`：清空 accidents 目录下全部产物（不触碰其他数据源）。"""
        for p in self.raw_dir.glob("*.shtml"):
            p.unlink(missing_ok=True)
        for p in self.pdf_dir.glob("*.pdf"):
            p.unlink(missing_ok=True)
        if self.structured_path.exists():
            self.structured_path.unlink()
        self.state.reset()

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _article_id(url: str) -> str:
        """详情页唯一标识。取 `t{日期}_{序号}` 整体（同日多报告不冲突），直链 PDF 用文件 token。"""
        m = re.search(r"t\d{8}_\d+", url)
        if m:
            return m.group(0)
        m = re.search(r"([0-9A-Za-z]{20,40})\.pdf$", url, re.I)
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
        title = re.sub(r"[\xa0  　]+", " ", title)
        title = re.sub(r"\s{2,}", " ", title)
        return title.strip()

    @staticmethod
    def _normalize_date(value: str) -> str:
        """2026年05月22日 -> 2026-05-22；无法识别返回原值。"""
        if not value:
            return ""
        m = re.search(r"(\d{4})年?[-/年](\d{1,2})[-/月](\d{1,2})日?", value)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return value.strip()

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------
    def crawl_by_category(self, category: str, **kwargs: Any) -> list[dict[str, Any]]:
        """按事故类型抓取并过滤（兼容旧接口）。"""
        records = self.crawl(**kwargs)
        if not category:
            return records
        matched = [
            r for r in records if (r.get("category") or "").startswith(category)
        ]
        logger.info("事故类型 %s 命中 %d 条", category, len(matched))
        return matched
