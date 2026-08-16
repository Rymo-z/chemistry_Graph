"""RAGAS 指标评估：对 build_eval_dataset.py 产出的数据集跑四项标准指标。

用法（建议在隔离 venv 中运行，避免向应用环境引入 ragas/langchain 依赖）：
    python scripts/eval_ragas.py [--dataset tmp/eval_dataset.jsonl] [--output docs/eval/ragas_report.md]

- judge LLM：读取项目 .env 的 LLM_API_BASE / LLM_API_KEY / LLM_MODEL（OpenAI 兼容，
  默认 deepseek），经 ragas.llm_factory 构建。
- embedding：读取 .env 的 EMBEDDING_MODEL（本地 bge-large-zh-v1.5，sentence-transformers
  加载），供 answer_relevancy 使用；embedding 不可用时自动跳过该指标。
- 指标：faithfulness / answer_relevancy / context_precision / context_recall。
- 输出：markdown 报告（总览 + 逐条明细）+ JSON 原始数据。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> dict[str, str]:
    """极简 .env 解析（不引入 python-dotenv 依赖）。"""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS 指标评估")
    parser.add_argument(
        "--dataset",
        default=str(BASE_DIR / "tmp" / "eval_dataset.jsonl"),
    )
    parser.add_argument(
        "--output",
        default=str(BASE_DIR / "docs" / "eval" / "ragas_report.md"),
    )
    args = parser.parse_args()

    env = load_env(BASE_DIR / ".env")
    llm_model = env.get("LLM_MODEL", "deepseek-v4-flash")
    llm_base = env.get("LLM_API_BASE", "https://api.deepseek.com")
    llm_key = env.get("LLM_API_KEY", "")
    emb_model = env.get("EMBEDDING_MODEL", "")

    if not llm_key:
        print("错误：.env 缺少 LLM_API_KEY")
        sys.exit(1)

    # ---------- 数据 ----------
    rows = [
        json.loads(line)
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"加载 {len(rows)} 条评估样本")

    # ---------- judge LLM ----------
    # ragas 0.4 的 llm_factory 要求传入 OpenAI 兼容 client 实例
    from openai import OpenAI
    from ragas.llms import llm_factory

    client = OpenAI(api_key=llm_key, base_url=llm_base)
    # max_tokens：结构化输出默认 1024 可能截断，调高到 4096。
    # extra_body：关闭 deepseek 思考（否则推理 token 会烧掉预算导致 content 为空，
    # 与应用内 common/llm.py 的 LLM_DISABLE_THINKING 行为一致）。
    llm = llm_factory(
        llm_model,
        client=client,
        max_tokens=4096,
        extra_body={"thinking": {"type": "disabled"}},
    )
    print(f"judge LLM: {llm_model} ({llm_base})")

    # ---------- embedding（可选） ----------
    embeddings = None
    try:
        if emb_model:
            from langchain_community.embeddings import HuggingFaceBgeEmbeddings
            from ragas.embeddings import LangchainEmbeddingsWrapper

            bge = HuggingFaceBgeEmbeddings(
                model_name=emb_model,
                query_instruction="为这个句子生成表示以用于检索相关文章：",
                encode_kwargs={"normalize_embeddings": True},
            )
            embeddings = LangchainEmbeddingsWrapper(bge)
            print(f"embedding: {emb_model}")
        else:
            print("警告：未配置 EMBEDDING_MODEL，跳过 answer_relevancy")
    except Exception as exc:  # noqa: BLE001
        print(f"警告：embedding 初始化失败，跳过 answer_relevancy: {exc}")

    # ---------- 数据集 ----------
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

    samples = []
    for row in rows:
        samples.append(
            SingleTurnSample(
                user_input=row["question"],
                response=row.get("answer") or "",
                retrieved_contexts=row.get("contexts") or [],
                reference=row.get("ground_truth") or "",
            )
        )
    dataset = EvaluationDataset(samples=samples)

    # ---------- 指标 ----------
    from ragas import evaluate
    from ragas.metrics import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    metrics = [
        Faithfulness(llm=llm),
        ContextPrecision(llm=llm),
        ContextRecall(llm=llm),
    ]
    if embeddings is not None:
        metrics.append(AnswerRelevancy(llm=llm, embeddings=embeddings))

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=True,
        show_progress=True,
    )

    # ---------- 结果 ----------
    df = result.to_pandas()
    metric_cols = [m.name for m in metrics]
    out_dir = Path(args.output).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = {
        "config": {"judge_llm": llm_model, "embedding": emb_model},
        "overall": {c: round(float(df[c].mean()), 4) for c in metric_cols},
        "per_sample": [],
    }
    for row, r in zip(rows, df.to_dict("records")):
        raw["per_sample"].append(
            {
                "id": row["id"],
                "question": row["question"],
                "vector_hits": row["metadata"]["vector_hits"],
                "graph_hits": row["metadata"]["graph_hits"],
                "metrics": {c: round(float(r.get(c, 0) or 0), 4) for c in metric_cols},
            }
        )

    # 汇总报告
    lines = ["# RAGAS 评估报告", ""]
    lines.append(f"- 样本数：{len(rows)}")
    lines.append(f"- judge LLM：{llm_model}")
    lines.append(f"- embedding：{emb_model or '（未启用，无 answer_relevancy）'}")
    lines.append("")
    lines.append("## 总体指标（均值）")
    lines.append("")
    lines.append("| 指标 | 得分 | 含义 |")
    lines.append("|------|------|------|")
    desc = {
        "faithfulness": "答案是否忠实于检索上下文（越低越可能幻觉）",
        "answer_relevancy": "答案与问题的相关度",
        "context_precision": "检索上下文是否相关且排位靠前",
        "context_recall": "真值信息是否被检索上下文覆盖",
    }
    for c in metric_cols:
        lines.append(f"| {c} | **{round(float(df[c].mean()), 4)}** | {desc.get(c, '')} |")
    lines.append("")
    lines.append("## 逐条明细")
    lines.append("")
    lines.append("| 样本 | 问题 | 向量命中 | 图谱命中 | " + " | ".join(metric_cols) + " |")
    lines.append("|------|------|:---:|:---:|" + "|".join([":---:"] * len(metric_cols)) + "|")
    for row, r in zip(rows, df.to_dict("records")):
        cells = [
            row["id"],
            (row["question"][:28] + "…" if len(row["question"]) > 28 else row["question"]),
            str(row["metadata"]["vector_hits"]),
            str(row["metadata"]["graph_hits"]),
        ] + [f"{round(float(r.get(c, 0) or 0), 3)}" for c in metric_cols]
        lines.append("| " + " | ".join(cells) + " |")

    (Path(args.output)).write_text("\n".join(lines), encoding="utf-8")
    raw_path = out_dir / "ragas_report.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== 总体指标 ===")
    for c in metric_cols:
        print(f"  {c}: {df[c].mean():.4f}")
    print(f"\n报告已写入: {args.output}")


if __name__ == "__main__":
    main()
