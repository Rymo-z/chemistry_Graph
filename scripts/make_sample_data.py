"""生成仓库内示例数据集 sample_data/（供 USE_SAMPLE_DATA=1 开箱体验 RAG demo）。

从 `_001_clawler/data/` 精选少量数据写入 `sample_data/`：
- chemicals/chemicals.jsonl   20 种常用危化品（含剧毒样例，沿用官方目录 schema）
- regulations.jsonl           10 部法规（标题/文号/日期 + 摘要，不含全文）
- work_permits.json           八大特殊作业完整副本（GB 30871-2022，共 8 类）
- extract/*.json              mini 抽取结果（实体结构，离线建索引/图导入用）
- faiss/*                     FAISS 种子索引（regulation_index + metadata + id_map + texts）

用法：
    python scripts/make_sample_data.py

前置：本机已有完整数据（_001_clawler/data/，由爬虫/整理脚本生成）且 embedding 模型
就绪（scripts/download_models.py）。重新生成前会保留既有文件，用 --force 覆盖。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# 项目根 = scripts/ -> 项目根；确保 `python scripts/xxx.py` 能 import common
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 必须在导入 common 之前设置：settings 在 import 期缓存，置 1 后
# STORAGE_DIR / EXTRACT_OUTPUT_DIR 指向 sample_data/，导出与建索引直接落盘。
os.environ["USE_SAMPLE_DATA"] = "1"

# 真实数据源（显式绝对路径，不受运行模式影响）
SRC_CHEMICALS = BASE_DIR / "_001_clawler" / "data" / "chemicals" / "chemicals.jsonl"
SRC_RECORDS = BASE_DIR / "_001_clawler" / "data" / "all_records.jsonl"
SRC_WORK_PERMITS = BASE_DIR / "_001_clawler" / "data" / "work_permits.json"

SAMPLE_DIR = BASE_DIR / "sample_data"
CHEMICALS_OUT = SAMPLE_DIR / "chemicals" / "chemicals.jsonl"
RECORDS_OUT = SAMPLE_DIR / "regulations.jsonl"
PERMITS_OUT = SAMPLE_DIR / "work_permits.json"
EXTRACT_DIR = SAMPLE_DIR / "extract"
README_OUT = SAMPLE_DIR / "README.md"

N_CHEMICALS = 20
N_RECORDS = 10
SUMMARY_LEN = 600

# 精选化学品品名（优先，未命中则顺延取目录前部）
CURATED_CHEMICALS = [
    "甲醇", "乙醇[无水]", "甲醛溶液", "氨", "一氧化碳", "二氧化碳",
    "氰化钾", "三氧化二砷", "砷化氢", "磷化氢", "氯", "液氯",
    "硫化氢", "二氧化硫", "氢气", "苯", "甲苯", "二甲苯",
    "氢氧化钠", "硫酸", "盐酸", "硝酸", "氮", "氧",
]

# 优先选取的法规标题关键词
CURATED_TITLES = [
    "安全生产法", "危险化学品安全管理条例", "生产安全事故报告和调查处理条例",
    "特种设备安全法", "消防法", "工贸企业", "动火作业", "有限空间",
]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"缺少真实数据源: {path}\n请先运行爬虫/整理（organize_data）后再生成示例集。")
    with open(path, encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def _pick_chemicals(chemicals: list[dict], n: int) -> list[dict]:
    by_name = {c["name"]: c for c in chemicals}
    picked = [by_name[name] for name in CURATED_CHEMICALS if name in by_name]
    for c in chemicals:  # 顺延补齐
        if len(picked) >= n:
            break
        if c not in picked:
            picked.append(c)
    return picked[:n]


def _pick_records(records: list[dict], n: int) -> list[dict]:
    def score(r: dict) -> int:
        title = r.get("title", "")
        return next((100 - i for i, kw in enumerate(CURATED_TITLES) if kw in title), 0)
    ordered = sorted(records, key=score, reverse=True)
    return ordered[:n]


def _chemical_extract_entities(chemicals: list[dict]) -> list[dict]:
    entities = []
    for c in chemicals:
        toxic = bool(c.get("is_toxic"))
        entities.append({
            "name": c.get("name", ""),
            "type": "Material",  # 与 _002_extract_information.schema.EntityType 对齐
            "aliases": c.get("aliases") or [],
            "attributes": {
                "cas_no": c.get("cas_no", ""),
                "category": "剧毒化学品" if toxic else "危险化学品",
                "summary": (
                    f"{c.get('name','')}（CAS {c.get('cas_no','') or '—'}），"
                    f"{'剧毒化学品，按剧毒目录管理。' if toxic else '危险化学品。'}"
                ),
            },
        })
    return entities


def _record_extract_entities(records: list[dict]) -> list[dict]:
    entities = []
    for r in records:
        content = r.get("content", "")
        summary = " ".join(content.split())[:SUMMARY_LEN]
        entities.append({
            "name": r.get("title", ""),
            "type": "Document",
            "aliases": [],
            "attributes": {
                "doc_no": r.get("doc_no", ""),
                "publish_date": r.get("publish_date", ""),
                "implement_date": r.get("implement_date", ""),
                "category": r.get("category", ""),
                "status": r.get("status", ""),
                "summary": summary,
            },
        })
    return entities


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        for r in records:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 sample_data/ 示例数据集")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的输出文件")
    args = parser.parse_args()

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # 只以最终产物（FAISS 索引）判断是否已生成；空目录（如测试 mkdir）不算
    if (SAMPLE_DIR / "faiss" / "regulation_index.faiss").is_file() and not args.force:
        print(f"[sample] 示例索引已存在，跳过（--force 可重新生成）: {SAMPLE_DIR}")
        return 0

    chemicals = _load_jsonl(SRC_CHEMICALS)
    records = _load_jsonl(SRC_RECORDS)
    if not SRC_WORK_PERMITS.is_file():
        raise SystemExit(f"缺少真实数据源: {SRC_WORK_PERMITS}")

    picked_chemicals = _pick_chemicals(chemicals, N_CHEMICALS)
    picked_records = _pick_records(records, N_RECORDS)
    print(f"[sample] 精选化学品 {len(picked_chemicals)} 种、法规 {len(picked_records)} 部")

    # 1. 数据文件
    _write_jsonl(CHEMICALS_OUT, picked_chemicals)
    _write_jsonl(RECORDS_OUT, picked_records)
    shutil.copyfile(SRC_WORK_PERMITS, PERMITS_OUT)
    print(f"[sample] 写入化学品/法规/作业票 -> {SAMPLE_DIR}")

    # 2. mini 抽取结果（实体结构）
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    for fname, payload in (
        ("chemicals.json", {"source": "sample_chemicals", "entities": _chemical_extract_entities(picked_chemicals)}),
        ("regulations.json", {"source": "sample_regulations", "entities": _record_extract_entities(picked_records)}),
    ):
        with open(EXTRACT_DIR / fname, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
    print(f"[sample] 写入 mini 抽取结果 -> {EXTRACT_DIR}")

    # 3. 离线导出元数据 + 构建 FAISS 种子索引
    from _003_create_neo4j_database.faiss_indexer import FaissIndexer
    from _003_create_neo4j_database.metadata_export import export_from_json

    export_from_json(EXTRACT_DIR)          # -> sample_data/faiss/{metadata.json,texts.txt,id_map.pkl}
    FaissIndexer().rebuild_from_storage()  # -> sample_data/faiss/regulation_index.faiss
    print(f"[sample] FAISS 种子索引构建完成 -> {SAMPLE_DIR / 'faiss'}")

    # 4. 目录说明
    README_OUT.write_text(
        "# sample_data — 示例数据集（开箱 demo）\n\n"
        f"由 `scripts/make_sample_data.py` 从完整数据精选生成，共 {len(picked_chemicals)} 种化学品、"
        f"{len(picked_records)} 部法规、八大特殊作业 8 类。\n\n"
        "- `chemicals/chemicals.jsonl`：危化品样例（官方目录 schema，含剧毒标记）\n"
        "- `regulations.jsonl`：法规元数据 + 摘要（**不含全文**，版权归发布机关）\n"
        "- `work_permits.json`：GB 30871-2022 八大特殊作业完整副本\n"
        "- `extract/`：mini 抽取结果（实体结构，离线建索引/图导入用）\n"
        "- `faiss/`：FAISS 种子索引（RAG 检索直接加载，无需 Neo4j）\n\n"
        "在 `.env` 设 `USE_SAMPLE_DATA=true` 后启动服务即用。完整数据请运行 "
        "`scripts/rebuild_pipeline.py`。\n",
        encoding="utf-8",
    )

    print("[sample] 完成。在 .env 设 USE_SAMPLE_DATA=true 即可用示例数据启动服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
