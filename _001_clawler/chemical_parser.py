"""解析《危险化学品目录（2015版）》→ `data/chemicals/chemicals.jsonl`。

数据流：应急管理部官网公告附件（WPS OLE2 `.doc`，安监总局公告2015年第5号）经
Word COM 提取 `Content.Text` 得到 `data/chemicals/raw/weixianhuaxuepin_mulu_2015.txt`
（单元格以 `\\x07` 分隔、内容以 `\\n` 结尾）。本模块从该文本重建表格行。

官方表格为 5 列：**序号 | 品名 | 别名 | CAS号 | 备注**（正文后另附「注：」说明，
标注条目 2828 类属条目的 A/B 型稀释剂退敏规则，非目录数据）。

关键坑：
1. Word 线性化里每物理行 = 6 个连续单元格（序号/品名/别名/CAS号/备注 + 恒空尾列）。
2. 同一序号下的变体行（不同含量/形态，如「二正丙基过氧重碳酸酯[含量≤100%]」与
   「[含量≤77%,含B型稀释剂≥23%]」）的「序号」「CAS号」单元格被纵向合并，
   `Content.Text` 呈现为空字符串 → 视作上一条目的延续，继承序号与 CAS。
3. 官方 doc 存在 3 处序号笔误（717→718、1951→1851、2008→2009，已对照 gov.cn 权威
   转载核实，如《危险化学品目录（2015版）》序号 717 确为二正丙基过氧重碳酸酯）。
   因目录序号严格连续 1..2828，按出现顺序重编号即可自动纠正。

用法：
    python -m _001_clawler.chemical_parser
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RAW_TXT = (
    Path(__file__).resolve().parent
    / "data" / "chemicals" / "raw" / "weixianhuaxuepin_mulu_2015.txt"
)
OUT_JSONL = Path(__file__).resolve().parent / "data" / "chemicals" / "chemicals.jsonl"

ROW_CELLS = 6  # 序号 品名 别名 CAS号 备注 (恒空尾列)
HEADER_SIGNATURE = "序号\n\x07品名\n\x07别名\n\x07CAS号\n\x07备注"

# 备注列取值（官方目录仅标注剧毒化学品，其余为空）
NOTE_TOXIC = "剧毒"


def _read_cell_rows() -> list[list[str]]:
    """读取 .txt 并按物理行（6 单元格）切分，截掉表尾「注：」说明。"""
    text = RAW_TXT.read_text(encoding="utf-8")
    start = text.find(HEADER_SIGNATURE)
    if start < 0:
        raise ValueError(f"未找到目录表头 {HEADER_SIGNATURE!r}，请检查 {RAW_TXT}")
    cells = text[start:].split("\x07")
    cells = [c.strip("\n\x0c ") for c in cells]
    # 表尾注释（条目2828 之后的 A/B 型稀释剂说明），截断
    end = next((i for i, c in enumerate(cells) if c.startswith("注：")), len(cells))
    cells = cells[:end]
    if len(cells) % ROW_CELLS != 0:
        raise ValueError(f"单元格数 {len(cells)} 不能被 {ROW_CELLS} 整除，表格结构异常")
    return [cells[i:i + ROW_CELLS] for i in range(0, len(cells), ROW_CELLS)]


def split_aliases(alias: str) -> list[str]:
    """别名按全/半角分号拆分（化学名内部逗号如 3,3,5-三甲基 不算分隔符）。"""
    return [a.strip() for a in re.split(r"[；;]", alias) if a.strip()]


def split_cas(cas: str) -> list[str]:
    """CAS 号拆分。个别条目含多个 CAS（同分异构/盐类），原表以「；+换行」分隔。

    返回去空白后的 CAS 列表（空输入返回空列表）。
    """
    if not cas:
        return []
    return [p for p in (x.strip(" \n\t\r") for x in re.split(r"[；;]", cas)) if p]


def parse_chemicals() -> list[dict]:
    """解析全表，返回化学品记录列表（含变体行，序号为纠正后的官方序号）。"""
    entries: list[dict] = []
    cur_serial = 0
    cur_cas = ""  # 当前条目首个 CAS（供变体行继承；新条目时重置，避免串到上一条目）
    for cells in _read_cell_rows():
        serial_raw, name, alias, cas, note, _trailing = cells
        if serial_raw == "序号":
            continue  # 表头行（表尾「注：」已由 _read_cell_rows 截断）
        if serial_raw:
            cur_serial += 1
            cur_cas = ""
        if not cas:
            cas = cur_cas  # 变体行 / 无 CAS 条目：继承当前条目首个 CAS
        if cas:
            cur_cas = cas
        toxic = note == NOTE_TOXIC
        cas_list = split_cas(cas)
        entries.append({
            # 官方目录字段
            "serial_no": cur_serial,
            "name": name,
            "aliases": split_aliases(alias),
            "cas_no": cas_list[0] if cas_list else "",
            "cas_list": cas_list,
            "note": note,
            "is_toxic": toxic,
            "hazard_category": NOTE_TOXIC if toxic else "",
            # 数据计划 §3.3 预留字段（目录未提供，待 GHS 分类 / MSDS 等后续补全）
            "in_catalog": True,
            "un_number": "",
            "hazard_class": "",
            "msds": "",
            "flash_point": "",
            "toxicity": "",
            "storage_req": "",
        })
    return entries


def main() -> int:
    entries = parse_chemicals()
    toxic = [e for e in entries if e["is_toxic"]]
    n_serial = len({e["serial_no"] for e in entries})
    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSONL, "w", encoding="utf-8") as fp:
        for e in entries:
            fp.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(
        f"已写入 {OUT_JSONL}：{len(entries)} 行（{n_serial} 个唯一序号，"
        f"剧毒 {len(toxic)} 条）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
