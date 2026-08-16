"""构建 RAGAS 评估数据集：跑真实 QA 链路，收集答案与检索上下文。

用法：
    python scripts/build_eval_dataset.py [--output tmp/eval_dataset.jsonl] [--limit N]

- 读取 scripts/golden_qa_set.json（手标真值），对每条 question 调用 run_chat()
  跑完整 QA 链路（FAISS 检索 + 图谱兜底 + LLM 合成）。
- 产出 {id, question, answer, contexts, ground_truth, metadata} 列表，
  contexts 取 rag_results[].evidence_text（检索证据），供 RAGAS 评估。
- 默认在 USE_SAMPLE_DATA=true 模式下运行（示例数据，Neo4j 不依赖）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 让脚本能从项目根导入 common/ 等模块
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ["USE_SAMPLE_DATA"] = "1"

from _004_langgraph_more_nodes.graph_builder import run_chat  # noqa: E402


def build_one(item: dict) -> dict:
    """对单条 golden 问题跑链路，返回评估样本。"""
    qid = item["id"]
    question = item["question"]
    result = run_chat(question)

    rag_results = result.get("rag_results") or []
    contexts = [str(r.get("evidence_text") or "") for r in rag_results]
    metadata = result.get("metadata") or {}
    return {
        "id": qid,
        "question": question,
        "answer": result.get("output") or "",
        "contexts": contexts,
        "ground_truth": item["ground_truth"],
        "metadata": {
            "vector_hits": len(contexts),
            "graph_hits": metadata.get("graph_hits", 0),
            "intent": metadata.get("intent"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 RAGAS 评估数据集")
    parser.add_argument("--output", default=str(BASE_DIR / "tmp" / "eval_dataset.jsonl"))
    parser.add_argument("--limit", type=int, default=0, help="只取前 N 条（默认全部）")
    args = parser.parse_args()

    golden = json.loads(
        (BASE_DIR / "scripts" / "golden_qa_set.json").read_text(encoding="utf-8")
    )
    if args.limit:
        golden = golden[: args.limit]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for item in golden:
        sample = build_one(item)
        rows.append(sample)
        meta = sample["metadata"]
        print(
            f"[{sample['id']}] 向量命中={meta['vector_hits']} "
            f"图谱命中={meta['graph_hits']} 答案长度={len(sample['answer'])}"
        )

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n完成：{len(rows)} 条样本 → {out_path}")


if __name__ == "__main__":
    main()
