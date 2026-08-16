"""accident_crawler.py 离线单元测试（不发网络请求，不写生产数据目录）。

覆盖：年份目录发现、新/旧模板详情解析、PDF 链接提取、
PDF 文本清洗、启发式字段切分、schema 组装、PDF 抽取与下载失败兜底。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pypdf
import requests

from _001_clawler.accident_crawler import (
    INDEX_URL,
    AccidentCrawler,
    _YEAR_DIR_RE,
)

# ------------------------------------------------------------------
# fixture：索引页（年份子目录，命名无规律）
# ------------------------------------------------------------------
INDEX_HTML = """
<html><head><title>特别重大事故调查报告</title></head>
<body>
<a href="./2026dcbg/">2026年</a>
<a href="./2025dcbg_6344/">2025年</a>
<a href="./2024dcbg/">2024年</a>
<a href="./2003/">2003年</a>
<a href="./about/">关于我们</a>
<a href="./notice.shtml">通知</a>
</body></html>
"""

# fixture：年份目录页（新模板 + 旧模板详情链接 + 直链 PDF）
YEAR_HTML = """
<html><head><title>2025年特别重大事故调查报告</title></head>
<body>
<a href="../../../zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml">某某特别重大爆炸事故调查评估报告</a>
<a href="./202501/t20250101_654321.shtml">旧模板事故调查报告</a>
<a href="W020250921123456789012.pdf">直链PDF原文</a>
<a href="http://other.example.com/notice">无关链接</a>
</body></html>
"""

# fixture：新模板详情页（.scy_main_detail 元数据表 + W020/P020）
DETAIL_NEW_HTML = """
<html><head><title>某某化工有限公司“9·21”特别重大爆炸事故调查报告_中华人民共和国应急管理部</title></head>
<body>
<div class="scy_main_detail">
<table>
<tr><td>标题</td><td>某某化工公司爆炸事故调查报告</td><td>索引号</td><td>3E001001/2025-00001</td></tr>
<tr><td>发文字号</td><td>应急〔2025〕1号</td><td>成文日期</td><td>2025年09月21日</td></tr>
<tr><td>发布日期</td><td>2025年09月22日</td><td>发文单位</td><td>应急管理部</td></tr>
</table>
</div>
<div class="scy_detail_bottom">
<a href="W020250921123456789012.pdf">下载原文（W020）</a>
<a href="P020250921123456789012.pdf">附件（P020）</a>
</div>
</body></html>
"""

# fixture：旧模板详情页（无元数据表，仅标题 + PDF）
DETAIL_OLD_HTML = """
<html><head><title>某重大事故调查报告</title></head>
<body>
<div class="content"><p>调查报告内容概要。</p>
<a href="W020200101123456789012.pdf">下载报告</a>
</div></body></html>
"""

# fixture：老模板无 PDF 附件，正文内联在 TRS CMS 容器
DETAIL_INLINE_HTML = """
<html><head><title>某特别重大事故调查报告</title></head>
<body>
<div class="TRS_Editor">
<p>2010年11月15日14时15分许，位于上海市静安区某大楼发生火灾事故，造成重大人员伤亡。
经国务院调查组认定，这是一起由于企业违规动火作业引发的生产安全责任事故。</p>
<p>一、事故基本情况</p>
<p>事故造成58人死亡、71人受伤，直接经济损失1.58亿元。</p>
<p>二、直接原因</p>
<p>违规动火作业引燃外墙保温材料并迅速蔓延。</p>
<p>三、间接原因</p>
<p>施工单位安全管理混乱，监理单位未有效履职。</p>
<p>四、责任认定</p>
<p>对事故有关责任人员依法追究刑事责任，对相关企业依法处罚。</p>
</div>
</body></html>
"""

# 合成报告正文：用于启发式字段切分
REPORT_TEXT = """2024年1月24日15时30分许，位于江西省新余市渝水区的某某化工有限公司发生火灾，造成重大人员伤亡。
一、事故基本情况
事故造成39人死亡、9人受伤，直接经济损失4352.84万元。
二、直接原因
现场违规动火作业引燃可燃物。
三、间接原因
企业安全管理混乱。
四、责任认定
对事故有关责任人员提出处理建议。
五、整改防范措施
加强隐患排查治理。"""


def _crawler() -> AccidentCrawler:
    # 注入临时数据目录，避免单测污染 data/accidents 生产数据与断点状态
    tmp = Path(tempfile.mkdtemp(prefix="accident_test_"))
    return AccidentCrawler(max_requests=0, data_dir=tmp / "accidents")


# ------------------------------------------------------------------
# 年份目录发现
# ------------------------------------------------------------------
def test_year_dir_regex():
    assert _YEAR_DIR_RE.match("./2025dcbg_6344/")
    assert _YEAR_DIR_RE.match("./2026dcbg/")
    assert _YEAR_DIR_RE.match("./2003/")
    assert _YEAR_DIR_RE.match("2024dcbg/")
    assert not _YEAR_DIR_RE.match("./about/")
    assert not _YEAR_DIR_RE.match("./notice.shtml")
    assert not _YEAR_DIR_RE.match("./2025dcbg_6344/extra.html")


def test_discover_report_urls():
    crawler = _crawler()
    calls: list[str] = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        if url == INDEX_URL:
            return INDEX_HTML
        if "2025dcbg_6344" in url:
            return YEAR_HTML
        return "<html><body></body></html>"

    crawler.fetch = fake_fetch  # type: ignore[method-assign]
    urls = crawler._discover_report_urls()

    # 索引页先抓，再抓各年份目录
    assert calls[0] == INDEX_URL
    # 年份目录被解析出来
    assert "https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/2025dcbg_6344/" in calls
    # 新模板详情 URL（相对链接上跳三级）正确绝对化
    assert "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml" in urls
    # 直链 PDF 也被收集
    assert any(u.endswith("W020250921123456789012.pdf") for u in urls)
    # 无关链接不混入
    assert not any("other.example.com" in u for u in urls)
    # 去重保序
    assert len(urls) == len(set(urls))


# ------------------------------------------------------------------
# 详情页解析（新/旧模板）
# ------------------------------------------------------------------
def test_parse_detail_new_template():
    crawler = _crawler()
    url = "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml"
    rec = crawler._parse_detail(url, DETAIL_NEW_HTML)
    assert rec is not None
    # <title> 优先（清理站点后缀）
    assert rec["title"] == "某某化工有限公司“9·21”特别重大爆炸事故调查报告"
    assert rec["index_no"] == "3E001001/2025-00001"
    assert rec["doc_no"] == "应急〔2025〕1号"
    assert rec["sign_date"] == "2025-09-21"
    assert rec["publish_date"] == "2025-09-22"
    assert rec["issuing_org"] == "应急管理部"
    # W020 原文版优先
    assert rec["pdf_url"].endswith("W020250921123456789012.pdf")
    assert rec["source_site"] == "mem.gov.cn"
    # 正文此时为空（待 PDF 填充），不解析失败
    assert rec["content"] == ""


def test_parse_detail_old_template():
    crawler = _crawler()
    rec = crawler._parse_detail("https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/2003/200301/t20030101_111.shtml", DETAIL_OLD_HTML)
    assert rec is not None
    assert rec["title"] == "某重大事故调查报告"
    assert rec["pdf_url"].endswith("W020200101123456789012.pdf")


def test_parse_detail_missing_title_or_pdf_returns_none():
    crawler = _crawler()
    assert crawler._parse_detail("http://x/1.shtml", "<html><body>nothing</body></html>") is None


def test_parse_detail_inline_content_fallback():
    crawler = _crawler()
    url = "https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/2007/200705/t20070511_245258.shtml"
    rec = crawler._parse_detail(url, DETAIL_INLINE_HTML)
    assert rec is not None
    # 无 PDF 链接，但内联正文被提取
    assert rec["pdf_url"] == ""
    assert "上海市静安区" in rec["content"]
    assert rec["content_len"] > 100
    # 启发式字段同时生效
    assert rec["location"] != ""
    assert "违规动火" in rec["cause"]


# ------------------------------------------------------------------
# PDF 链接提取
# ------------------------------------------------------------------
def test_extract_pdf_links_w020_priority():
    from bs4 import BeautifulSoup

    crawler = _crawler()
    soup = BeautifulSoup(DETAIL_NEW_HTML, "lxml")
    pdfs = crawler._extract_pdf_links(soup, "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml")
    assert len(pdfs) == 2
    assert pdfs[0].endswith("W020250921123456789012.pdf")
    assert pdfs[1].endswith("P020250921123456789012.pdf")


# ------------------------------------------------------------------
# PDF 文本清洗
# ------------------------------------------------------------------
def test_clean_pdf_text_cjk_spaces():
    text, ocr = AccidentCrawler._clean_pdf_text("甲 醇 泄 漏\n现 场 处 置 不 当\n")
    assert "甲醇泄漏" in text
    assert "现场处置不当" in text
    assert ocr is False


def test_clean_pdf_text_ocr_flag():
    text, ocr = AccidentCrawler._clean_pdf_text("%%%%###\n@@@ [[[]] 12345")
    assert ocr is True


# ------------------------------------------------------------------
# 启发式字段
# ------------------------------------------------------------------
def test_heuristic_fields_section_split():
    fields = AccidentCrawler._heuristic_fields(REPORT_TEXT, "某某有限公司特别重大火灾事故")
    assert fields["date"] == "2024-01-24"
    assert "39人死亡" in fields["summary"]
    assert "违规动火" in fields["cause"]
    assert "企业安全管理混乱" in fields["cause"]
    assert "对事故有关责任人员" in fields["responsibility"]
    assert fields["level"] == "特别重大"
    assert fields["category"] == "火灾"
    assert fields["is_chemical"] is True


def test_extract_incident_date_title_month_day():
    text = "成文于2025年。\n事故发生……"
    fields = AccidentCrawler._heuristic_fields(text, "某某公司“9·21”爆炸事故")
    assert fields["date"] == "2025-09-21"


def test_extract_location_enterprise_level():
    head = "江苏省南京市六合区某某化工有限公司发生爆炸事故，属于特别重大事故。"
    assert "江苏省" in AccidentCrawler._extract_location(head)
    assert "某某化工有限公司" in AccidentCrawler._extract_enterprise(head)
    assert AccidentCrawler._extract_level("某某特别重大爆炸事故") == "特别重大"
    assert AccidentCrawler._extract_level("无等级标注") == ""


def test_classify_category_priority():
    assert AccidentCrawler._classify_category("车间发生中毒窒息事故") == "中毒窒息"
    assert AccidentCrawler._classify_category("储罐发生爆炸事故") == "爆炸"
    assert AccidentCrawler._classify_category("管道泄漏") == "泄漏"
    assert AccidentCrawler._classify_category("生活小区普通新闻") == ""


def test_extract_section_no_marker():
    assert AccidentCrawler._extract_section("没有章节标记的普通文本", ("直接原因",), ("责任认定",)) == ""


# ------------------------------------------------------------------
# schema 组装
# ------------------------------------------------------------------
def test_schema_assembly_p1_fields():
    crawler = _crawler()
    rec = crawler._parse_detail("https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml", DETAIL_NEW_HTML)
    assert rec is not None
    rec.update(AccidentCrawler._heuristic_fields(REPORT_TEXT, rec["title"]))
    p1_fields = {
        "title", "date", "location", "enterprise", "level", "category",
        "summary", "cause", "responsibility", "content", "url", "source_site",
    }
    assert p1_fields <= set(rec.keys())
    assert rec["url"].startswith("https://")
    assert rec["source_site"] == "mem.gov.cn"


# ------------------------------------------------------------------
# PDF 抽取与下载兜底
# ------------------------------------------------------------------
def test_extract_pdf_text_mocked(monkeypatch):
    class FakePage:
        def extract_text(self, **kwargs):  # noqa: ARG002
            return "第X页正文"

    class FakeReader:
        pages = [FakePage(), FakePage()]

    monkeypatch.setattr(pypdf, "PdfReader", lambda path: FakeReader())
    text = _crawler()._extract_pdf_text(Path("fake.pdf"))
    assert text == "第X页正文\n第X页正文"


def test_download_pdf_failure_does_not_block(monkeypatch):
    crawler = _crawler()
    monkeypatch.setattr(crawler, "fetch_bytes", lambda url: (_ for _ in ()).throw(requests.ConnectionError("down")))

    path = Path(crawler.pdf_dir / "mem_fail.pdf")
    assert crawler._download_pdf("https://example.com/x.pdf", path) is None
    assert not path.exists()
    # 详情页元数据仍可入库：_fill_pdf_content 不抛异常，记录保持元数据态
    rec = crawler._parse_detail("https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml", DETAIL_NEW_HTML)
    assert rec is not None
    rec["url"] = "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_999999.shtml"
    try:
        crawler._fill_pdf_content(rec, "fail999")
    except (requests.ConnectionError, requests.RequestException):
        raise AssertionError("PDF 下载失败不应向上抛异常")
    assert rec["content"] == ""


def test_fill_pdf_content_success(monkeypatch):
    crawler = _crawler()
    monkeypatch.setattr(crawler, "fetch_bytes", lambda url: b"%PDF-1.7 fake")
    monkeypatch.setattr(crawler, "_extract_pdf_text", lambda path: REPORT_TEXT)
    rec = crawler._parse_detail("https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml", DETAIL_NEW_HTML)
    assert rec is not None
    crawler._fill_pdf_content(rec, "ok123")
    assert "违规动火" in rec["content"]
    assert rec["content_len"] > 100
    assert rec["ocr_needed"] is False
    assert rec["cause"] != ""
    assert rec["pdf_file"].endswith(".pdf")


# ------------------------------------------------------------------
# 工具
# ------------------------------------------------------------------
def test_clean_title_strips_site_suffix():
    # mem.gov.cn 真实分隔符：下划线 / 双连字符
    assert AccidentCrawler._clean_title("某某事故调查报告_中华人民共和国应急管理部") == "某某事故调查报告"
    assert AccidentCrawler._clean_title("某某事故调查报告--中华人民共和国应急管理部") == "某某事故调查报告"
    # 无后缀原样保留
    assert AccidentCrawler._clean_title("某某事故调查报告") == "某某事故调查报告"


def test_normalize_date():
    assert AccidentCrawler._normalize_date("2025年09月22日") == "2025-09-22"
    assert AccidentCrawler._normalize_date("") == ""
    assert AccidentCrawler._normalize_date("无日期") == "无日期"


def test_article_id():
    # 详情页：完整 token，同一天多报告不冲突
    assert AccidentCrawler._article_id("https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123456.shtml") == "t20250921_123456"
    assert AccidentCrawler._article_id("https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202509/t20250921_123457.shtml") == "t20250921_123457"
    # 直链 PDF：文件 token
    assert AccidentCrawler._article_id("https://www.mem.gov.cn/x/W020250921123456789012.pdf") == "W020250921123456789012"
