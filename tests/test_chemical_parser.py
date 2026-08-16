"""chemical_parser.py 离线单元测试（不发网络请求）。

覆盖：单元格行切分、别名/CAS 拆分、序号重编号纠正官方 doc 笔误、
变体行（纵向合并单元格）序号与 CAS 继承、剧毒标记、CAS 格式校验、
输出文件生成。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from _001_clawler.chemical_parser import (
    OUT_JSONL,
    RAW_TXT,
    parse_chemicals,
    split_aliases,
    split_cas,
)

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _load():
    if not RAW_TXT.is_file():
        pytest.skip(f"危化品目录源文件缺失（gitignored）: {RAW_TXT}")
    return parse_chemicals()


# ---------- 纯函数 ----------

def test_split_aliases():
    """别名按全/半角分号拆分，化学名内部逗号不拆分。"""
    assert split_aliases("鸦片") == ["鸦片"]
    assert split_aliases("液氨；氨气") == ["液氨", "氨气"]
    # 化学名内部英文逗号（如 3,3,5-三甲基）不算分隔符
    assert split_aliases("3,3,5-三甲基-4,6-二氨基-2-烯环己酮") == [
        "3,3,5-三甲基-4,6-二氨基-2-烯环己酮"
    ]
    assert split_aliases("") == []


def test_split_cas():
    """单个/多个 CAS（原表以「；+换行」分隔）均拆分干净。"""
    assert split_cas("67-56-1") == ["67-56-1"]
    assert split_cas("22259-30-9；\n23422-53-9") == ["22259-30-9", "23422-53-9"]
    assert split_cas("15120-21-5；\n7632-04-4；\n11138-47-9") == [
        "15120-21-5", "7632-04-4", "11138-47-9",
    ]
    assert split_cas("") == []


# ---------- 全表解析 ----------

def test_total_entries_and_contiguous_serials():
    """官方目录 2828 种，序号严格连续 1..2828（无缺失/重复）。"""
    recs = _load()
    serials = sorted({r["serial_no"] for r in recs})
    assert serials == list(range(1, 2829))


def test_toxic_count_matches_official():
    """备注标"剧毒"共 148 种，与官方《剧毒化学品目录》数量一致。"""
    recs = _load()
    toxic = [r for r in recs if r["is_toxic"]]
    assert len(toxic) == 148
    for r in toxic:
        assert r["hazard_category"] == "剧毒"
        assert r["note"] == "剧毒"


def test_known_cas_spot_check():
    """抽查常见危化品：品名 + CAS 号对应正确。"""
    recs = _load()
    by_name = {r["name"]: r for r in recs}
    assert by_name["甲醇"]["cas_no"] == "67-56-1"
    assert by_name["甲醛溶液"]["cas_no"] == "50-00-0"
    assert by_name["氨"]["cas_no"] == "7664-41-7"
    assert by_name["一氧化碳"]["cas_no"] == "630-08-0"
    assert by_name["乙醇[无水]"]["cas_no"] == "64-17-5"


def test_known_toxic_chemicals_marked():
    """典型剧毒化学品均正确标记。"""
    recs = _load()
    toxic_names = {r["name"] for r in recs if r["is_toxic"]}
    for name in ("氰化钾", "砷化氢", "叠氮化钠", "三氧化二砷", "碳酰氯", "磷化氢"):
        assert name in toxic_names, f"{name} 应标记为剧毒"
    # 非剧毒对照：普通酒精类不入剧毒集合
    assert "乙醇[无水]" not in toxic_names


def test_variant_row_inherits_serial_and_cas():
    """变体行（纵向合并序号/CAS）继承上一条目的序号与 CAS。"""
    recs = _load()
    by_name = {r["name"]: r for r in recs}
    fe = by_name["三氯化铁"]
    sol = by_name["三氯化铁溶液"]
    assert sol["serial_no"] == fe["serial_no"] == 1850
    assert sol["cas_no"] == fe["cas_no"] == "7705-08-0"


def test_doc_serial_typos_corrected():
    """官方 doc 三处序号笔误被重编号纠正（对照 gov.cn 权威转载核实）。"""
    recs = _load()
    by_name = {r["name"]: r for r in recs}
    assert by_name["二正丙基过氧重碳酸酯[含量≤100%]"]["serial_no"] == 717
    assert by_name["二正丁胺"]["serial_no"] == 718
    assert by_name["十八烷基乙酰胺"]["serial_no"] == 1951
    assert by_name["双过氧化壬二酸[含量≤27%,惰性固体含量≥73%]"]["serial_no"] == 2008
    assert by_name["双过氧化十二烷二酸[含量≤42%,含硫酸钠≥56%]"]["serial_no"] == 2009


def test_multi_cas_split():
    """多 CAS 条目：cas_no 取首个，cas_list 保留全量。"""
    recs = _load()
    by_name = {r["name"]: r for r in recs}
    mg = by_name["硅化镁"]
    assert mg["cas_no"] == "22831-39-6"
    assert mg["cas_list"] == ["22831-39-6", "39404-03-0"]
    assert len([r for r in recs if len(r["cas_list"]) > 1]) == 10


def test_cas_format_and_required_fields():
    """全部 CAS 格式合法；无空品名/空序号；类属条目允许空 CAS。"""
    recs = _load()
    for r in recs:
        assert r["name"], f"serial {r['serial_no']} 品名为空"
        assert r["serial_no"], "存在空序号"
        for c in r["cas_list"]:
            assert CAS_RE.match(c), f"{r['name']} CAS {c!r} 格式非法"
    empty_cas = [r for r in recs if not r["cas_no"]]
    assert empty_cas, "应存在类属条目（无 CAS）"
    # 最后一条为类属条目（闭杯闪点≤60℃ 的制品）
    assert recs[-1]["name"].startswith("含易燃溶剂")


def test_catalog_anchor_entries():
    """目录首尾锚点条目正确。"""
    recs = _load()
    assert recs[0]["serial_no"] == 1
    assert recs[0]["name"] == "阿片"
    assert recs[-1]["serial_no"] == 2828


def test_output_jsonl_written():
    """main() 生成的 chemicals.jsonl 存在且可解析。"""
    if not OUT_JSONL.is_file():
        pytest.skip("chemicals.jsonl 尚未生成")
    with open(OUT_JSONL, encoding="utf-8") as fp:
        lines = [json.loads(line) for line in fp if line.strip()]
    assert len(lines) == len(_load())
    assert {r["serial_no"] for r in lines} == set(range(1, 2829))
