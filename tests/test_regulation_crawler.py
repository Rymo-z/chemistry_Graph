"""RegulationCrawler 解析逻辑单元测试（离线，不访问网络）。

覆盖：fdzdgknr / tzgg 两种模板解析、标题清洗、日期归一化、文号提取。

运行：
    python -m unittest tests.test_regulation_crawler -v
"""
from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from _001_clawler.regulation_crawler import RegulationCrawler

# 最小化但保留关键结构的 HTML 样例（结构取自 mem.gov.cn 真实页面）
FDZDGKNR_HTML = """
<html><head><title>应急管理部关于印发《样例规定》的通知--中华人民共和国应急管理部</title></head>
<body>
  <div class="scy_main_detail">
    <table>
      <tr><td>标题：</td><td>应急管理部关于印发《样例规定》的通知</td></tr>
      <tr><td>索引号：</td><td>4/2026-00001</td><td>发文字号：</td><td>应急〔2026〕88号</td><td>发文单位：</td><td>应急管理部</td></tr>
      <tr><td>所属机构：</td><td>安全生产执法和工贸安全监督管理局</td><td>主题分类：</td><td>安全执法</td><td>公文种类：</td><td>通知</td></tr>
      <tr><td>成文日期：</td><td>2026年03月01日</td><td>发布日期：</td><td>2026年03月05日</td></tr>
    </table>
  </div>
  <div id="content"><p>应急管理部关于印发《样例规定》的通知</p><p>应急〔2026〕88号</p><p>第一条 为加强安全管理，制定本规定。</p></div>
</body></html>
"""

TZGG_HTML = """
<html><head><title>应急管理部关于印发危险化学品企业安全分类整治目录（2020年）的通知--中华人民共和国应急管理部</title></head>
<body>
  <div class="youbiaodc_ind01">2020-11-03 16:35 来源：危险化学品安全监管司</div>
  <div class="TRS_Editor">
    <p>应急管理部关于印发危险化学品企业安全分类整治目录（2020年）的通知</p>
    <p>应急〔2020〕84号</p>
    <p>现将《危险化学品企业安全分类整治目录（2020年）》印发给你们。</p>
  </div>
</body></html>
"""


class TestRegulationParser(unittest.TestCase):
    def setUp(self) -> None:
        self.crawler = RegulationCrawler(max_requests=0)

    # ------------------------------------------------------------------
    def test_parse_fdzdgknr(self) -> None:
        record = self.crawler._parse_article(
            "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202603/t20260301_600000.shtml",
            FDZDGKNR_HTML,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["title"], "应急管理部关于印发《样例规定》的通知")
        self.assertEqual(record["doc_no"], "应急〔2026〕88号")
        self.assertEqual(record["publish_date"], "2026-03-05")
        self.assertEqual(record["sign_date"], "2026-03-01")
        self.assertEqual(record["issuing_org"], "应急管理部")
        self.assertEqual(record["index_no"], "4/2026-00001")
        self.assertEqual(record["doc_type"], "通知")
        self.assertEqual(record["belong_org"], "安全生产执法和工贸安全监督管理局")
        self.assertIn("第一条", record["content"])
        self.assertEqual(record["source_site"], "mem.gov.cn")

    def test_parse_tzgg(self) -> None:
        record = self.crawler._parse_article(
            "https://www.mem.gov.cn/gk/tzgg/tz/202011/t20201103_371291.shtml",
            TZGG_HTML,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["title"], "应急管理部关于印发危险化学品企业安全分类整治目录（2020年）的通知")
        self.assertEqual(record["doc_no"], "应急〔2020〕84号")
        self.assertEqual(record["publish_date"], "2020-11-03")
        self.assertEqual(record["issuing_org"], "危险化学品安全监管司")
        self.assertIn("整治目录", record["content"])

    def test_reject_short_or_empty(self) -> None:
        record = self.crawler._parse_article(
            "https://www.mem.gov.cn/gk/tzgg/tz/202011/t20201103_371291.shtml",
            "<html><head><title>x</title></head><body></body></html>",
        )
        self.assertIsNone(record)

    # ------------------------------------------------------------------
    def test_clean_title_keeps_leading_department(self) -> None:
        raw = "应急管理部 住房城乡建设部关于印发《样例》的通知--中华人民共和国应急管理部"
        self.assertEqual(self.crawler._clean_title(raw), "应急管理部 住房城乡建设部关于印发《样例》的通知")

    def test_clean_title_normalizes_whitespace(self) -> None:
        raw = "应急管理部 国家矿山安监局 国家发改委关于加强煤矿等安全管理的通知"
        cleaned = self.crawler._clean_title(raw)
        self.assertNotIn(" ", cleaned)
        self.assertNotIn(" ", cleaned)
        self.assertEqual(cleaned, "应急管理部 国家矿山安监局 国家发改委关于加强煤矿等安全管理的通知")

    def test_normalize_date(self) -> None:
        self.assertEqual(self.crawler._normalize_date("2026年05月22日"), "2026-05-22")
        self.assertEqual(self.crawler._normalize_date("2020-11-03 16:35"), "2020-11-03")
        self.assertEqual(self.crawler._normalize_date(""), "")

    def test_normalize_doc_no_strips_space(self) -> None:
        # 元数据表格的「317 号」带空格，统一去空白
        self.assertEqual(self.crawler._normalize_doc_no("应急厅函〔2022〕317 号"), "应急厅函〔2022〕317号")
        self.assertEqual(self.crawler._normalize_doc_no("2022年 第8号"), "2022年第8号")
        self.assertEqual(self.crawler._normalize_doc_no(""), "")

    def test_extract_doc_no_multiline(self) -> None:
        content = "应急管理部\n关于印发\x00\n应急〔\n2026〕19号的通知"
        self.assertEqual(self.crawler._extract_doc_no(content), "应急〔2026〕19号")
        self.assertEqual(self.crawler._extract_doc_no("正文不含文号"), "")

    def test_extract_doc_no_fullwidth_bracket(self) -> None:
        # 全角括号 ﹝﹞（原正则未覆盖，导致误抓正文引用文号）
        content = "应急管理部办公厅关于开展抽查工作的通知 应急厅函﹝ 2019 ﹞ 548 号 各省、"
        self.assertEqual(self.crawler._extract_doc_no(content), "应急厅函﹝2019﹞548号")

    def test_extract_doc_no_multiline_fullwidth(self) -> None:
        # 全角括号 + 机关名与括号被换行拆开（每段一行），且正文引用他人文号更靠后。
        # 真实案例：隐患排查治理通知，机关名"安委办"后是 \n﹝\n2018\n﹞\n15\n号。
        content = (
            "国务院安委会办公室关于进一步加强\n"
            "隐患排查治理体系建设示范试点工作的通知\n"
            "安委办\n﹝\n2018\n﹞\n15\n号\n"
            "各省、自治区、直辖市及新疆生产建设兵团安全生产委员会，各有关单位：\n"
            "按照《国务院安委会办公室关于进一步做好隐患排查治理体系建设示范试点工作的通知》"
            "（安委办〔\n2017\n〕\n13\n号）要求，北"
        )
        self.assertEqual(self.crawler._extract_doc_no(content), "安委办﹝2018﹞15号")

    def test_extract_doc_no_spaced_number(self) -> None:
        # 序号内空格（如 "3 1 号" = 31号）
        content = "应急管理部办公厅关于更新烟花爆竹经营许可证式样的通知 应急厅〔 2020 〕3 1 号 各省"
        self.assertEqual(self.crawler._extract_doc_no(content), "应急厅〔2020〕31号")

    def test_extract_doc_no_gaogao_from_title(self) -> None:
        # 公告文号：正文未带文号时从标题兜底，且不误抓正文引用的国办文号
        content = "为贯彻落实党中央部署，根据《国务院办公厅关于做好证明事项清理工作的通知》（国办发〔2018〕47号）精神，现将..."
        title = "应急管理部公告（2019年 第11号）：第二批取消的证明事项"
        self.assertEqual(self.crawler._extract_doc_no(content, title), "应急管理部公告（2019年 第11号）")

    def test_extract_doc_no_gaogao_from_content(self) -> None:
        content = "中华人民共和国应急管理部 公 告 2018 年 第 12 号 根据中共中央机构改革方案..."
        self.assertEqual(self.crawler._extract_doc_no(content), "中华人民共和国应急管理部公告（2018年 第12号）")

    def test_extract_doc_no_ignores_cited_doc(self) -> None:
        # 引用文号出现在正文中部，只搜开头 150 字时不应抓到
        content = "现将有关事项通知如下。" + "加强管理。" * 40 + "（国办发〔2018〕47号）"
        self.assertEqual(self.crawler._extract_doc_no(content), "")

    def test_article_id(self) -> None:
        self.assertEqual(
            self.crawler._article_id("https://www.mem.gov.cn/gk/tzgg/202011/t20201103_371291.shtml"),
            "20201103",
        )


if __name__ == "__main__":
    unittest.main()
