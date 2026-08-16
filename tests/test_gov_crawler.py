"""gov_crawler.py 离线单元测试（不发网络请求）。

覆盖：标题后缀清理、正文多模板容器提取、施行日期提取、
记录组装、白名单完整性。
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from _001_clawler.gov_crawler import (
    CONTENT_SELECTORS,
    TARGET_LAWS,
    GovCrawler,
    _IMPLEMENT_RE,
)

# 模板 1：新版政策库 / 公报（#UCAP-CONTENT 嵌套 div.govdata > td.p1）
HTML_UCAP = """
<html><head><title>生产安全事故报告和调查处理条例_国务院文件_中国政府网</title></head>
<body>
<div class="b12c pages_content" id="UCAP-CONTENT">
  <div class="govdata">
    <p align="center"><strong>中华人民共和国国务院令</strong></p>
    <p align="center">第493号</p>
    <p align="center"><strong>生产安全事故报告和调查处理条例</strong></p>
    <p><strong>第一条</strong>　为了规范生产安全事故的报告和调查处理，落实生产安全事故责任追究制度，防止和减少生产安全事故，根据《中华人民共和国安全生产法》和有关法律，制定本条例。</p>
    <p><strong>第二条</strong>　生产经营活动中发生的造成人身伤亡或者直接经济损失的生产安全事故的报告和调查处理，适用本条例。</p>
    <p><strong>第三条</strong>　根据生产安全事故造成的人员伤亡或者直接经济损失，事故一般分为特别重大事故、重大事故、较大事故和一般事故四个等级。</p>
    <p><strong>第四条</strong>　事故报告应当及时、准确、完整，任何单位和个人对事故不得迟报、漏报、谎报或者瞒报。</p>
    <p>本条例自2007年6月1日起施行。</p>
  </div>
</div>
</body></html>
"""

# 模板 2：旧模板（td.p1 > font#Zoom）
HTML_TD = """
<html><head><title>危险化学品安全管理条例</title></head>
<body>
<table><tr><td class="p1"><font id="Zoom">
<p align="center"><strong>中华人民共和国国务院令</strong></p>
<p align="center">第591号</p>
<p><strong>第一条</strong>　为了加强危险化学品的安全管理，预防和减少危险化学品事故，保障人民群众生命财产安全，保护环境，制定本条例。</p>
<p><strong>第二条</strong>　危险化学品生产、储存、使用、经营和运输的安全管理，适用本条例。</p>
<p><strong>第三条</strong>　本条例所称危险化学品，是指具有毒害、腐蚀、爆炸、燃烧、助燃等性质，对人体、设施、环境具有危害的剧毒化学品和其他化学品。</p>
<p><strong>第四条</strong>　危险化学品安全管理，应当坚持安全第一、预防为主、综合治理的方针，强化和落实企业主体责任。</p>
<p>本条例自2011年12月1日起施行。</p>
</font></td></tr></table>
</body></html>
"""

# 模板 3：地方站通用 CMS（div.v_news_content / div.detaildata）
# 注意：detaildata 内、v_news_content 外放一条面包屑导航，验证专内容容器优先于外层
HTML_VNEWS = """
<html><head><title>中华人民共和国安全生产法（第三次修正版）_应急法规_伊犁哈萨克自治州人民政府</title></head>
<body>
<div class="detaildata">
  <p class="nav">首页 / 政务公开 / 法规文件</p>
  <div class="v_news_content">
    <p><strong>第一条</strong>　为了加强安全生产工作，防止和减少生产安全事故，保障人民群众生命和财产安全，促进经济社会持续健康发展，制定本法。</p>
    <p><strong>第二条</strong>　在中华人民共和国领域内从事生产经营活动的单位的安全生产，适用本法。</p>
    <p><strong>第三条</strong>　安全生产工作坚持中国共产党的领导，以人为本，坚持人民至上、生命至上，把保护人民生命安全摆在首位。</p>
    <p><strong>第四条</strong>　生产经营单位必须遵守本法和其他有关安全生产的法律、法规，加强安全生产管理，建立健全全员安全生产责任制和安全生产规章制度。</p>
    <p><strong>第五条</strong>　生产经营单位的主要负责人是本单位安全生产第一责任人，对本单位的安全生产工作全面负责。</p>
    <p><strong>第一百一十九条</strong>　本法自2002年11月1日起施行。</p>
  </div>
</div>
</body></html>
"""

# 模板 4：TRS 编辑器（div.view.TRS_UEDITOR）
HTML_TRS = """
<html><head><title>中华人民共和国消防法（2021修正）_其他文件_首都之窗_北京市人民政府门户网站</title></head>
<body>
<div class="box"><div class="mainTextBox">
  <div class="view TRS_UEDITOR trs_paper_default trs_web">
    <p><strong>第一条</strong>　为了预防火灾和减少火灾危害，加强应急救援工作，保护人身、财产安全，维护公共安全，制定本法。</p>
    <p><strong>第二条</strong>　消防工作贯彻预防为主、防消结合的方针，按照政府统一领导、部门依法监管、单位全面负责、公民积极参与的原则，实行消防安全责任制。</p>
    <p><strong>第三条</strong>　国务院领导全国的消防工作。地方各级人民政府负责本行政区域内的消防工作。</p>
    <p><strong>第四条</strong>　消防工作由消防救援机构实施监督管理。县级以上地方人民政府消防救援机构依法对机关、团体、企业、事业等单位进行消防监督检查。</p>
    <p><strong>第五条</strong>　任何单位和个人都有维护消防安全、保护消防设施、预防火灾、报告火警的义务。</p>
    <p><strong>第七十四条</strong>　本法自2009年5月1日起施行。</p>
  </div>
</div></div>
</body></html>
"""


def _crawler() -> GovCrawler:
    return GovCrawler(max_requests=0)


def _parse(html: str) -> dict:
    law = {
        "id": "test_law",
        "title": "测试法律",
        "category": "法律",
        "doc_no": "",
        "publish_date": "",
        "implement_date": "2020-01-01",
        "url": "https://example.gov.cn/abc.htm",
        "source_site": "测试",
    }
    return _crawler()._parse_article(law, law["url"], html)


# ------------------------------------------------------------------
# 标题清理
# ------------------------------------------------------------------
def test_clean_page_title_zwgk():
    assert GovCrawler._clean_page_title("生产安全事故报告和调查处理条例_国务院文件_中国政府网") == \
        "生产安全事故报告和调查处理条例"


def test_clean_page_title_tab():
    assert GovCrawler._clean_page_title("中华人民共和国特种设备安全法（主席令第四号）\t法律_法律法规_中国政府网") == \
        "中华人民共和国特种设备安全法（主席令第四号）"


def test_clean_page_title_fullwidth():
    assert GovCrawler._clean_page_title("中华人民共和国国务院令（第493号）　　生产安全事故报告和调查处理条例__2007年第16号") == \
        "中华人民共和国国务院令（第493号）"


def test_clean_page_title_keep_cms_bracket():
    # 标题本身含修正标识，无站点分隔符时整体保留
    assert GovCrawler._clean_page_title("中华人民共和国安全生产法（第三次修正版）") == \
        "中华人民共和国安全生产法（第三次修正版）"


# ------------------------------------------------------------------
# 正文提取（多模板）
# ------------------------------------------------------------------
def test_extract_ucap_template():
    soup = BeautifulSoup(HTML_UCAP, "html.parser")
    text, sel = _crawler()._extract_content(soup)
    assert sel == "#UCAP-CONTENT"
    assert "第一条" in text and "第二条" in text
    assert text.count("第") >= 2


def test_extract_td_p1_template():
    soup = BeautifulSoup(HTML_TD, "html.parser")
    text, sel = _crawler()._extract_content(soup)
    assert sel == "td.p1"
    assert "第一条" in text


def test_extract_v_news_template():
    soup = BeautifulSoup(HTML_VNEWS, "html.parser")
    text, sel = _crawler()._extract_content(soup)
    assert sel == "div.v_news_content"
    assert "第一条" in text and "第一百一十九条" in text
    # 回归：专内容容器优先于外层 detaildata，面包屑导航不得混入正文
    assert "首页" not in text and "政务公开" not in text


def test_extract_trs_template():
    soup = BeautifulSoup(HTML_TRS, "html.parser")
    text, sel = _crawler()._extract_content(soup)
    assert sel == "div.TRS_UEDITOR"
    assert "第一条" in text


def test_content_selectors_present():
    assert len(CONTENT_SELECTORS) >= 6  # 兼容所有已验证模板


# ------------------------------------------------------------------
# 页脚清理
# ------------------------------------------------------------------
def test_trim_footer_removes_editor_noise():
    body = "新华社北京电 中华人民共和国主席令 第四号\n\n第一百零一条　本法自2014年1月1日起施行。"
    noisy = body + "\n责任编辑： 刘笑迪\n相关链接\nhttp://example.gov.cn"
    cleaned = GovCrawler._trim_footer(noisy)
    assert cleaned == body
    assert "责任编辑" not in cleaned and "相关链接" not in cleaned


def test_trim_footer_keeps_body_when_mark_in_forepart():
    # 页脚标记出现在正文前半段时不截断（防止误删法律正文）
    body = "相关链接本条规定了法律责任。\n第一百零二条　本条例自2011年12月1日起施行。"
    assert GovCrawler._trim_footer(body) == body


def test_trim_footer_empty():
    assert GovCrawler._trim_footer("") == ""


# ------------------------------------------------------------------
# 施行日期
# ------------------------------------------------------------------
def test_extract_implement_date():
    assert GovCrawler._extract_implement_date("本条例自2011年12月1日起施行。") == "2011-12-01"
    assert GovCrawler._extract_implement_date("本法自2007年6月1日起施行。") == "2007-06-01"
    assert GovCrawler._extract_implement_date("无施行条款") == ""
    assert _IMPLEMENT_RE.search("自2011年12月1日起施行") is not None


# ------------------------------------------------------------------
# 记录组装
# ------------------------------------------------------------------
def test_parse_article_record_assembly():
    rec = _parse(HTML_UCAP)
    assert rec is not None
    assert rec["title"] == "测试法律"
    assert rec["page_title"] == "生产安全事故报告和调查处理条例"
    assert rec["category"] == "法律"
    assert rec["content_container"] == "#UCAP-CONTENT"
    assert "第一条" in rec["content"]
    # 人工校对优先：白名单已有施行日期时不覆盖
    assert rec["implement_date"] == "2020-01-01"
    assert rec["status"] == "现行"


def test_parse_article_content_too_short():
    rec = _parse("<html><head><title>空</title></head><body><p>很短</p></body></html>")
    assert rec is None


def test_parse_article_extract_implement_fallback():
    law = {
        "id": "x", "title": "X", "category": "行政法规", "doc_no": "",
        "publish_date": "", "implement_date": "",
        "url": "https://example.gov.cn/x.htm", "source_site": "测试",
    }
    rec = _crawler()._parse_article(law, law["url"], HTML_TD)
    assert rec is not None
    assert rec["implement_date"] == "2011-12-01"  # 白名单缺省时从正文提取


# ------------------------------------------------------------------
# 白名单完整性
# ------------------------------------------------------------------
def test_target_laws_integrity():
    assert len(TARGET_LAWS) >= 6
    ids = [law["id"] for law in TARGET_LAWS]
    assert len(ids) == len(set(ids))  # id 唯一
    for law in TARGET_LAWS:
        assert law["url"].startswith("https://")
        assert any(d in law["url"] for d in ("gov.cn", "gov.cn"))
        assert law["title"] and law["doc_no"] and law["category"]
        assert law["category"] in ("法律", "行政法规")
        assert law["id"].replace("_", "").isalnum()  # id 为安全小写 slug
