"""数据整理：把各数据源的 structured.jsonl 合并为统一数据资产。

读取 `data/{govlaws,regulations,accidents}/structured.jsonl`（若存在），
归一化为统一 schema 后输出：
- `data/all_records.jsonl`：合并记录（供下游抽取 / 建图 / 检索直接消费）
- `data/OVERVIEW.md`：人类可读清单（法律/行政法规 + 规范性文件 + 事故报告）

用法：
    python -m _001_clawler.organize_data
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from common.config import BASE_DIR, settings
from common.logger import get_logger

logger = get_logger(__name__)

# 统一 schema：各数据源字段映射到同一套键
GOVLAWS_FIELDS = {
    "law_id": "law_id",
    "title": "title",
    "category": "category",
    "doc_no": "doc_no",
    "publish_date": "publish_date",
    "implement_date": "implement_date",
    "status": "status",
    "source_site": "source_site",
    "url": "url",
    "raw_file": "raw_file",
    "content": "content",
    "note": "note",
}
REGULATION_FIELDS = {
    "title": "title",
    "category": "category",
    "doc_no": "doc_no",
    "publish_date": "publish_date",
    "status": "status",
    "issuing_org": "issuing_org",
    "source_site": "source_site",
    "url": "url",
    "raw_file": "raw_file",
    "content": "content",
}
ACCIDENT_FIELDS = {
    "title": "title",
    "category": "category",
    "doc_no": "doc_no",
    "publish_date": "publish_date",
    "issuing_org": "issuing_org",
    "source_site": "source_site",
    "url": "url",
    "raw_file": "raw_file",
    "content": "content",
    # 事故专有字段直接映射进统一 schema 顶层
    "date": "date",
    "location": "location",
    "enterprise": "enterprise",
    "level": "level",
    "summary": "summary",
    "cause": "cause",
    "responsibility": "responsibility",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        logger.info("数据源不存在，跳过: %s", path)
        return []
    with open(path, encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def _normalize(records: Iterable[dict[str, Any]], field_map: dict[str, str], source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        rec: dict[str, Any] = {"source": source}
        for src_key, dst_key in field_map.items():
            rec[dst_key] = r.get(src_key, "")
        # 统一补充字段
        rec.setdefault("implement_date", "")
        rec.setdefault("issuing_org", rec.get("source_site", ""))
        rec["content_len"] = len(rec.get("content", ""))
        rec["extras"] = {k: v for k, v in r.items() if k not in field_map}
        out.append(rec)
    return out


def _md_table(rows: list[dict[str, Any]]) -> str:
    lines = ["| 标题 | 类别 | 文号 | 发布/施行 | 来源 | 状态 | 字数 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        date = r.get("publish_date") or ""
        impl = r.get("implement_date")
        date_cell = f"{date} / 施行 {impl}" if impl else date
        lines.append(
            f"| {r.get('title','')} | {r.get('category','')} | {r.get('doc_no','') or '-'} "
            f"| {date_cell or '-'} | {r.get('source_site','')} | {r.get('status','')} | {r.get('content_len',0)} |"
        )
    return "\n".join(lines)


def _work_permit_md_table(rows: list[dict[str, Any]]) -> str:
    """八大特殊作业清单（work_permits.json）。"""
    lines = ["| 作业类型 | 分级 | 票有效期 | 审批权限 | 措施数 |", "| --- | --- | --- | --- | --- |"]
    for wp in rows:
        grading = wp.get("grading") or {}
        levels = [lv.get("level", "") for lv in grading.get("levels", [])]
        approvals = [
            f"{lv.get('level', '')}：{lv.get('approver', '')}"
            for lv in (wp.get("approval_flow") or {}).get("levels", [])
        ]
        lines.append(
            f"| {wp.get('work_type', '')} | {'/'.join(levels) if levels else '—'} "
            f"| {wp.get('permit_validity', '')} | {'；'.join(approvals)} "
            f"| {len(wp.get('safety_measures', []))} |"
        )
    return "\n".join(lines)


def _chemical_md_table(rows: list[dict[str, Any]], limit: int = 15) -> str:
    """危化品目录清单（sample 前 limit 行，2828 种全量在 chemicals.jsonl）。"""
    lines = ["| 序号 | 品名 | 别名 | CAS号 | 备注 |", "| --- | --- | --- | --- | --- |"]
    for r in rows[:limit]:
        aliases = "；".join(r.get("aliases") or []) or "-"
        lines.append(
            f"| {r.get('serial_no','')} | {r.get('name','')} | {aliases} "
            f"| {r.get('cas_no','') or '-'} | {r.get('note','') or '-'} |"
        )
    return "\n".join(lines)


def _accident_md_table(rows: list[dict[str, Any]]) -> str:
    lines = ["| 标题 | 类别 | 地点 | 企业 | 等级 | 事发时间 | 来源 | 字数 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(
            f"| {r.get('title','')} | {r.get('category','') or '-'} | {r.get('location','') or '-'} "
            f"| {r.get('enterprise','') or '-'} | {r.get('level','') or '-'} | {r.get('date','') or '-'} "
            f"| {r.get('source_site','')} | {r.get('content_len',0)} |"
        )
    return "\n".join(lines)


def main() -> int:
    data_dir = settings.CLAWLER_DATA_DIR
    govlaws = _normalize(_read_jsonl(data_dir / "govlaws" / "structured.jsonl"), GOVLAWS_FIELDS, "govlaws")
    regs = _normalize(_read_jsonl(data_dir / "regulations" / "structured.jsonl"), REGULATION_FIELDS, "regulations")
    accidents = _normalize(_read_jsonl(data_dir / "accidents" / "structured.jsonl"), ACCIDENT_FIELDS, "accidents")

    wp_file = data_dir / "work_permits.json"
    work_permits = json.loads(wp_file.read_text(encoding="utf-8")).get("work_permits", [])

    chemical_file = data_dir / "chemicals" / "chemicals.jsonl"
    chemicals = _read_jsonl(chemical_file)

    all_records = govlaws + regs + accidents
    out_path = data_dir / "all_records.jsonl"
    with open(out_path, "w", encoding="utf-8") as fp:
        for rec in all_records:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 人类可读清单
    gov_laws = sorted(govlaws, key=lambda x: -x["content_len"])
    md = [
        "# 化工安全生产合规数据清单",
        "",
        f"生成时间：{datetime.now().date()}（整理脚本 `_001_clawler/organize_data.py`）",
        "",
        "## 总览",
        "",
        f"- 法律/行政法规（govlaws）：**{len(govlaws)}** 部",
        f"- 规范性文件（regulations）：**{len(regs)}** 篇",
        f"- 事故调查报告（accidents）：**{len(accidents)}** 份",
        f"- 八大特殊作业（work_permits，GB 30871-2022）：**{len(work_permits)}** 类",
    ]
    if chemicals:
        toxic = sum(1 for c in chemicals if c.get("is_toxic"))
        md.append(
            f"- 危化品目录（chemicals，2015版）：**{len({c.get('serial_no') for c in chemicals})}** 种"
            f"（含变体 {len(chemicals)} 行，剧毒 **{toxic}** 种）"
        )
    md += [
        f"- 合并记录文件：`data/all_records.jsonl`（共 **{len(all_records)}** 条）",
        "",
    ]
    # 章节编号按实际输出顺序连续排列（accidents 为空时不跳号）
    _CN = ["一", "二", "三", "四", "五"]
    idx = 0
    md += [f"## {_CN[idx]}、法律与行政法规（govlaws）", "", _md_table(gov_laws), ""]
    idx += 1
    md += [
        f"## {_CN[idx]}、规范性文件（regulations，应急管理部）",
        "",
        _md_table(sorted(regs, key=lambda x: (x.get("publish_date") or "")[::-1])),
        "",
    ]
    idx += 1
    if accidents:
        md += [
            f"## {_CN[idx]}、事故调查报告（accidents，应急管理部特别重大事故）",
            "",
            _accident_md_table(sorted(accidents, key=lambda x: (x.get("date") or "")[::-1])),
            "",
        ]
        idx += 1
    if work_permits:
        md += [
            f"## {_CN[idx]}、八大特殊作业（work_permits，GB 30871-2022）",
            "",
            _work_permit_md_table(work_permits),
            "",
        ]
        idx += 1
    if chemicals:
        toxic_names = [c["name"] for c in chemicals if c.get("is_toxic")]
        md += [
            f"## {_CN[idx]}、危化品目录（chemicals，2015版）",
            "",
            f"- 全量 **2828** 种（含含量/形态变体共 {len(chemicals)} 行）",
            f"- 剧毒化学品 **{len(toxic_names)}** 种（备注栏标注）",
            f"- 无 CAS 号条目 {sum(1 for c in chemicals if not c.get('cas_no'))} 种（类属条目/混合物）",
            "",
            "### 目录样例（前 15 条，全量见 `data/chemicals/chemicals.jsonl`）",
            "",
            _chemical_md_table(chemicals),
            "",
        ]
        idx += 1
    md.append("---")
    md.append("> 数据仅供个人学习/研究使用。原始页面保留于 `data/{源}/raw/`，文本版权归发布机关。")

    overview = data_dir / "OVERVIEW.md"
    overview.write_text("\n".join(md), encoding="utf-8")

    logger.info(
        "整理完成: all_records=%d (govlaws=%d regulations=%d accidents=%d)",
        len(all_records), len(govlaws), len(regs), len(accidents),
    )
    logger.info("清单: %s", overview)
    logger.info("合并数据: %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
