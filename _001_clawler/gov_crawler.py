"""政府网（gov.cn 域名）法律/行政法规全文抓取实现。

抓取范围：`TARGET_LAWS` 白名单 —— 化工安全生产相关的核心法律与行政法规全文。
来源为中国政府网 www.gov.cn 及各地方政府门户（gov.cn 域名）。

数据特征（2026-08 实测验证）：
- 文章页模板多样，正文容器各不相同：
  1. `#UCAP-CONTENT`（政策库/公报新版，正文嵌套 div.govdata > td.p1 > font#Zoom）
  2. `td.p1`（2011 年前后旧模板，正文在 font#Zoom 内）
  3. `div.v_news_content` / `div.detaildata`（地方站通用 CMS 模板）
  4. `div.view.TRS_UEDITOR` / `div.TRS_Editor`（TRS 编辑器模板）
- 关键陷阱：**lxml 对部分 gov.cn 页面解析树中断**（连 .pages_content 都找不到），
  必须用 stdlib 的 `html.parser` 解析。
- 标题在 `<title>`，带 `__..._中国政府网` / `_首都之窗_...` 等站点后缀，需清理。
- 正文为逐条 `<p>` 段落，条款编号为 `<strong>` 或 `<font face="黑体">`。

合规/健壮性（继承 BaseCrawler）：
- robots.txt 拦截、随机间隔限速、指数退避重试、请求数安全阀。
- **目标 URL 硬编码白名单**：不做站点遍历/搜索，只抓精选法律页。
- 断点续爬 + 去重（checkpoint 文件 + 原始文件存在性双保险）。
- 单条失败不中断，记日志继续；汇总成功率。

输出：
- `data/govlaws/raw/{law_id}.html`    原始页面（保留取证）
- `data/govlaws/structured.jsonl`     规范化记录（每行一条 JSON）
- `data/govlaws/crawl_state.json`     断点状态
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup

from _001_clawler.base_crawler import BaseCrawler
from _001_clawler.checkpoint import CrawlState
from common.config import BASE_DIR, settings
from common.logger import get_logger

logger = get_logger(__name__)

# 目标法律/行政法规白名单（人工精选并逐条验证过全文可达）。
# 注：www.gov.cn 仅公布《安全生产法》2021 修改决定（无合并全文），
#     故现行全文采自伊犁州政府官网；《消防法》采自首都之窗。
TARGET_LAWS: list[dict[str, str]] = [
    {
        "id": "anquanshengchanfa_2021",
        "title": "中华人民共和国安全生产法（2021年第三次修正）",
        "category": "法律",
        "doc_no": "中华人民共和国主席令第八十八号",
        "publish_date": "2021-06-10",
        "implement_date": "2021-09-01",
        "url": "https://www.xjyl.gov.cn/xjylz/c112837/202109/c8ff18865b20425b85f41d5b655cc5f1.shtml",
        "source_site": "伊犁哈萨克自治州人民政府",
        "note": "2021-06-10 第十三届全国人大常委会第二十九次会议第三次修正，2021-09-01 施行。",
    },
    {
        "id": "weixianhuaxuepin_tiaoli",
        "title": "危险化学品安全管理条例（2011年修订）",
        "category": "行政法规",
        "doc_no": "中华人民共和国国务院令第591号",
        "publish_date": "2011-03-02",
        "implement_date": "2011-12-01",
        "url": "https://www.gov.cn/zwgk/2011-03/11/content_1822783.htm",
        "source_site": "www.gov.cn",
        "note": "2011-02-16 国务院第144次常务会议修订通过。",
    },
    {
        "id": "shengchananquanshigu_tiaoli",
        "title": "生产安全事故报告和调查处理条例",
        "category": "行政法规",
        "doc_no": "中华人民共和国国务院令第493号",
        "publish_date": "2007-04-09",
        "implement_date": "2007-06-01",
        "url": "https://www.gov.cn/zhengce/zhengceku/2008-03/28/content_4363.htm",
        "source_site": "www.gov.cn",
        "note": "2007-03-28 国务院第172次常务会议通过。",
    },
    {
        "id": "anquanshengchanxukezheng_tiaoli",
        "title": "安全生产许可证条例（2014年修正）",
        "category": "行政法规",
        "doc_no": "中华人民共和国国务院令第397号",
        "publish_date": "2014-07-29",
        "implement_date": "2014-07-29",
        "url": "https://www.gov.cn/gongbao/content/2016/content_5139525.htm",
        "source_site": "www.gov.cn",
        "note": "2004-01-13 公布；2014-07-29 依《国务院关于修改部分行政法规的决定》修正。",
    },
    {
        "id": "tezhongshebei_anquanfa",
        "title": "中华人民共和国特种设备安全法",
        "category": "法律",
        "doc_no": "中华人民共和国主席令第四号",
        "publish_date": "2013-06-30",
        "implement_date": "2014-01-01",
        "url": "https://www.gov.cn/zhengce/2013-06/30/content_2602288.htm",
        "source_site": "www.gov.cn",
        "note": "2013-06-29 第十二届全国人大常委会第三次会议通过。",
    },
    {
        "id": "xiaofangfa_2021",
        "title": "中华人民共和国消防法（2021年修正）",
        "category": "法律",
        "doc_no": "中华人民共和国主席令第八十一号",
        "publish_date": "2021-04-29",
        "implement_date": "2021-04-29",
        "url": "https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/202307/t20230726_3207767.html",
        "source_site": "北京市人民政府门户网站",
        "note": "2021-04-29 第二次修正（自公布之日起施行）。",
    },
    {
        "id": "weixianhuaxuepin_anquanfa",
        "title": "中华人民共和国危险化学品安全法",
        "category": "法律",
        "doc_no": "中华人民共和国主席令第六十四号",
        "publish_date": "2025-12-27",
        "implement_date": "2026-05-01",
        "url": "https://www.shanwei.gov.cn/swsyjj/gkmlpt/content/1/1249/post_1249406.html",
        "source_site": "汕尾市人民政府",
        "note": "2025-12-27 第十四届全国人大常委会第十九次会议通过，2026-05-01 施行。危化品安全管理核心新法。",
    },
    {
        "id": "shengchananquanshigu_yingji_tiaoli",
        "title": "生产安全事故应急条例",
        "category": "行政法规",
        "doc_no": "中华人民共和国国务院令第708号",
        "publish_date": "2019-02-17",
        "implement_date": "2019-04-01",
        "url": "https://www.gov.cn/zhengce/zhengceku/2019-03/01/content_5369591.htm",
        "source_site": "www.gov.cn",
        "note": "2018-12-05 国务院第33次常务会议通过，2019-04-01 施行。",
    },
    {
        "id": "yanhuabaozhu_anquan_tiaoli",
        "title": "烟花爆竹安全管理条例（2016年修订）",
        "category": "行政法规",
        "doc_no": "中华人民共和国国务院令第455号",
        "publish_date": "2006-01-21",
        "implement_date": "2016-02-06",
        "url": "https://yjgl.gd.gov.cn/gkmlpt/content/2/2982/mpost_2982510.html",
        "source_site": "广东省应急管理厅",
        "note": "2006-01-21 国务院令第455号公布；2016-02-06 依国务院令第666号《国务院关于修改部分行政法规的决定》修订。",
    },
    {
        "id": "tufashijian_yingdui_fa",
        "title": "中华人民共和国突发事件应对法（2024年修订）",
        "category": "法律",
        "doc_no": "中华人民共和国主席令第二十五号",
        "publish_date": "2024-06-28",
        "implement_date": "2024-11-01",
        "url": "https://yjt.zj.gov.cn/col/col1229892450/art/2026/art_5bc65ca31d004ec586b627b0d7556040.html",
        "source_site": "浙江省应急管理厅",
        "note": "2007-08-30 通过；2024-06-28 第十四届全国人大常委会第十次会议修订，2024-11-01 施行。",
    },
]

# 正文容器选择器级联：按「内容特异性优先级」命中第一个实质正文
# （专内容容器在前、包裹层在后，避免取到带面包屑/站点导航的外层 div）
CONTENT_SELECTORS: list[str] = [
    "#UCAP-CONTENT",  # 政策库/公报新版（内容在嵌套 div.govdata > td.p1 内）
    "td.p1",  # 旧模板（危化条例 2011，正文在 font#Zoom）
    "div.v_news_content",  # 地方站通用 CMS 正文（伊犁安法 2021）
    "div.article-content",  # 广东政务 gkmlpt 站群正文（汕尾/广东应急厅：危化品安全法、烟花爆竹条例）
    "div.TRS_UEDITOR",  # TRS 编辑器模板（消防法/首都之窗）
    "div.detaildata",  # 地方站 CMS 外层（仅在无 v_news_content 时兜底）
    "div.doc",  # 浙江政务站群正文（突发事件应对法 2024）
    "div.pages_content",
    "table.pages_content",
    "div.TRS_Editor",
    "div.govdata",
    "div.box",
]

# 视为“实质正文”的最小长度：低于该值视作命中容器非正文（如只有一句简介）
MIN_CONTENT_LEN: int = 200

# 新闻页脚标记：其后内容为站点 UI 噪音（责任编辑 / 相关链接 等），整段截断。
# 仅当标记出现在正文后半段时生效，避免误删法律正文中的同类词。
_FOOTER_MARKS: tuple[str, ...] = (
    "相关链接",
    "责任编辑",
    "（责任编辑",
    "扫一扫在手机打开",
    "页面纠错",
)

# 施行日期：如「本条例自 2011年12月1日 起施行。」
_IMPLEMENT_RE = re.compile(r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起施行")


class GovCrawler(BaseCrawler):
    """抓取 gov.cn 政府网法律/行政法规全文（白名单模式）。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            min_interval=kwargs.pop("min_interval", 2.0),
            max_interval=kwargs.pop("max_interval", 4.0),
            **kwargs,
        )
        self.data_dir: Path = settings.CLAWLER_DATA_DIR / "govlaws"
        self.raw_dir: Path = self.data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.structured_path: Path = self.data_dir / "structured.jsonl"
        self.state = CrawlState(self.data_dir / "crawl_state.json")
        self.targets: list[dict[str, str]] = list(TARGET_LAWS)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def crawl(
        self,
        *,
        limit: int = 0,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """按白名单批量抓取。

        Args:
            limit: 最多抓取条数（0 = 全部）。
            force: True 时忽略断点，重新抓取（会覆盖原始文件）。
        Returns:
            本次成功抓取的规范化记录列表。
        """
        if force:
            for p in self.raw_dir.glob("*.html"):
                p.unlink(missing_ok=True)
            if self.structured_path.exists():
                self.structured_path.unlink()
            self.state.reset()

        logger.info("目标法律白名单 %d 条（限抓 %s 条）", len(self.targets), limit or "全部")
        records: list[dict[str, Any]] = []
        for law in self.targets:
            if limit and len(records) >= limit:
                logger.info("已达 limit=%d，停止", limit)
                break
            url, law_id = law["url"], law["id"]
            raw_path = self.raw_dir / f"{law_id}.html"
            if not force and (self.state.is_done(url) or raw_path.exists()):
                logger.debug("跳过已抓取: %s", law_id)
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

            record = self._parse_article(law, url, html)
            if record is None:
                logger.warning("解析失败，跳过 %s (%s)", law_id, url)
                self.state.mark_failed(url, "parse returned None")
                continue

            self._store(record, html, raw_path)
            self.state.mark_done(url)
            records.append(record)
            logger.info(
                "已保存 [%d] %s | %s | %d 字",
                len(records), record["title"], record["content_container"], record["content_len"],
            )

        ok = len(records)
        fail = self.state.failed_count
        logger.info("抓取完成：成功 %d，失败 %d，已抓取累计 %d", ok, fail, self.state.done_count)
        return records

    # ------------------------------------------------------------------
    # 文章解析（多模板）
    # ------------------------------------------------------------------
    def _parse_article(
        self, law: dict[str, str], url: str, html: str
    ) -> Optional[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        page_title = self._clean_page_title(soup.title.get_text(strip=True) if soup.title else "")
        content, container = self._extract_content(soup)
        if len(content) < 50:
            logger.warning("正文过短(%d 字) %s: %s", len(content), law["id"], url)
            return None

        record: dict[str, Any] = {
            "law_id": law["id"],
            "title": law["title"],  # 白名单人工校对的权威标题
            "page_title": page_title,  # 页面 <title>（清理后缀后），供交叉核对
            "category": law["category"],
            "doc_no": law["doc_no"],
            "publish_date": law.get("publish_date", ""),
            "implement_date": law.get("implement_date", "")
            or self._extract_implement_date(content),
            "status": "现行",
            "source_site": law["source_site"],
            "content_container": container,
            "content_len": len(content),
            "content": content,
            "url": url,
            "note": law.get("note", ""),
        }
        return record

    def _extract_content(self, soup: BeautifulSoup) -> tuple[str, str]:
        """按优先级返回第一个命中「实质正文」的容器。

        返回 (正文文本, 命中选择器)。取最外层最长容器的方案会把
        面包屑/站点导航一并收进正文（实测 detaildata 含「首页 / 政务公开」），
        因此改为：专内容容器优先，首个长度达标者即命中。
        """
        for sel in CONTENT_SELECTORS:
            for el in soup.select(sel):
                text = el.get_text("\n")
                if len(text.strip()) >= MIN_CONTENT_LEN:
                    return self._trim_footer(self._clean_text(text)), sel
        return "", ""

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
    def _clean_page_title(raw: str) -> str:
        """去掉站点后缀：取第一个分隔符（tab/全角空格/下划线）前的标题正文。

        例：
        中华人民共和国安全生产法（第三次修正版）_应急法规_伊犁哈萨克自治州人民政府
            -> 中华人民共和国安全生产法（第三次修正版）
        中华人民共和国国务院令（第493号）　　生产安全事故报告和调查处理条例__...
            -> 中华人民共和国国务院令（第493号）
        """
        for sep in ("\t", "　", "__", "_"):
            idx = raw.find(sep)
            if idx > 0:
                raw = raw[:idx]
                break
        raw = re.sub(r"[\xa0  　]+", " ", raw)
        raw = re.sub(r"\s{2,}", " ", raw)
        return raw.strip()

    @staticmethod
    def _clean_text(text: str) -> str:
        """清洗正文：压缩空白、去掉空行。"""
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    @classmethod
    def _trim_footer(cls, text: str) -> str:
        """截断出现在正文后半段的新闻页脚（责任编辑/相关链接 等站点 UI）。

        多个标记同时存在时取「最早出现者」——页脚自第一个标记起即为噪音。
        仅当标记落在后半段才生效，防止误删法律正文。
        """
        if not text:
            return text
        pos: Optional[int] = None
        for mark in _FOOTER_MARKS:
            idx = text.rfind(mark)
            if idx >= 0 and (pos is None or idx < pos):
                pos = idx
        if pos is not None and pos > len(text) * 0.5:
            return text[:pos].rstrip()
        return text

    @staticmethod
    def _extract_implement_date(content: str) -> str:
        """从正文提取施行日期，如「自2011年12月1日起施行」-> 2011-12-01。"""
        if not content:
            return ""
        m = _IMPLEMENT_RE.search(content)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return ""


if __name__ == "__main__":
    # 直接运行本文件：给出指引 + 列出白名单（不抓取）
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    print("gov_crawler.py 是库模块，请通过 CLI 运行抓取，例如：")
    print("  python -m _001_clawler.run_crawler gov --limit 2   # 先小规模验证链路")
    print("  python -m _001_clawler.run_crawler gov              # 白名单全量（断点续爬）")
    print()
    print("---- 目标法律白名单 ----")
    for law in TARGET_LAWS:
        print(f"  [{law['id']}] {law['title']}")
        print(f"      {law['url']}")
    sys.exit(0)
