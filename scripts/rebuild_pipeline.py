"""一键重建完整数据链路：组织 → 抽取 → 建图 → 导出元数据 → 构建 FAISS 索引。

按顺序调用各模块 CLI（`python -m ...`）：
    1. organize_data      合并各源 structured.jsonl → data/all_records.jsonl + OVERVIEW.md
    2. run_extract        LLM 抽取实体/关系 → _002_extract_information/output/*.json
    3. graph_importer     清库后全量导入 Neo4j（需 Neo4j 就绪）
    4. metadata_export    从 Neo4j（或降级离线）导出节点元数据 → storage/
    5. faiss_indexer      由元数据构建 FAISS 向量索引 → storage/

前置：
- Neo4j 已启动，账号密码配置于 .env（NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD）
- embedding 模型已就绪（scripts/download_models.py）
- 完整数据已采集（scripts 或 _001_clawler/run_crawler.py）

用法：
    python scripts/rebuild_pipeline.py                 # 全量
    python scripts/rebuild_pipeline.py --skip-extract  # 复用已有 output/，跳过 LLM 抽取
    python scripts/rebuild_pipeline.py --limit 10 --workers 4   # 抽取参数透传
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

STEPS = [
    ("organize_data", ["-m", "_001_clawler.organize_data"]),
    ("run_extract", ["-m", "_002_extract_information.run_extract"]),
    ("graph_importer", ["-m", "_003_create_neo4j_database.graph_importer"]),
    ("metadata_export", ["-m", "_003_create_neo4j_database.metadata_export"]),
    ("faiss_indexer", ["-m", "_003_create_neo4j_database.faiss_indexer"]),
]


def run_step(name: str, args: list[str]) -> None:
    cmd = [sys.executable, *args]
    print(f"\n===== [{name}] {' '.join(cmd)} =====")
    proc = subprocess.run(cmd, cwd=BASE_DIR)
    if proc.returncode != 0:
        raise SystemExit(f"[{name}] 失败，退出码 {proc.returncode}，请修复后重试")


def main() -> int:
    parser = argparse.ArgumentParser(description="一键重建数据链路")
    parser.add_argument("--skip-extract", action="store_true", help="跳过 LLM 抽取（复用已有 output/）")
    parser.add_argument("--limit", type=int, default=0, help="run_extract 最多抽取条数（0=全部）")
    parser.add_argument("--offset", type=int, default=0, help="run_extract 跳过前 N 条")
    parser.add_argument("--source", choices=["govlaws", "regulations", "accidents"],
                        help="run_extract 只抽某数据源")
    parser.add_argument("--force", action="store_true", help="run_extract 强制重抽")
    parser.add_argument("--workers", type=int, default=4, help="run_extract 并发数（默认 4）")
    args = parser.parse_args()

    for name, base in STEPS:
        if name == "run_extract" and args.skip_extract:
            print("\n[skip] 跳过 run_extract（--skip-extract）")
            continue
        extra: list[str] = []
        if name == "run_extract":
            extra = []
            if args.limit:
                extra += ["--limit", str(args.limit)]
            if args.offset:
                extra += ["--offset", str(args.offset)]
            if args.source:
                extra += ["--source", args.source]
            if args.force:
                extra += ["--force"]
            if args.workers:
                extra += ["--workers", str(args.workers)]
        run_step(name, base + extra)

    print("\n数据链路完成：Neo4j 图库 + FAISS 索引均已就绪，可启动服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
