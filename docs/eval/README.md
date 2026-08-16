# 评估体系

本项目采用 [RAGAS](https://docs.ragas.io/) 对问答（RAG）链路做量化指标评估，用于回答
「系统效果有多好、改动代码后有没有变差」。

## 流程

```bash
# 1) 构建评估数据集：跑真实 QA 链路，收集答案 + 检索上下文 + 手标真值
python scripts/build_eval_dataset.py        # → tmp/eval_dataset.jsonl（gitignored）

# 2) 跑 RAGAS 指标（建议在隔离 venv，避免污染应用环境）
python scripts/eval_ragas.py                # → docs/eval/ragas_report.md + ragas_report.json
```

- **真值集**：`scripts/golden_qa_set.json`（手标，14 条，覆盖化学品/法规/作业票三类）。
- **judge LLM**：读取 `.env` 的 `LLM_API_*`（默认 deepseek-v4-flash），以 OpenAI 兼容接口调用；
  脚本已注入 `extra_body={"thinking": {"type": "disabled"}}` 关闭思考、`max_tokens=4096`。
- **embedding**：读取 `.env` 的 `EMBEDDING_MODEL`（本地 bge-large-zh-v1.5），供 `answer_relevancy`。

> 隔离 venv 安装参考：
> ```bash
> python -m venv /tmp/chem_ragas_venv
> /tmp/chem_ragas_venv/Scripts/python -m pip install \
>     ragas==0.4.3 "langchain<0.4" "langchain-community<0.4" openai pandas datasets \
>     torch --index-url https://download.pytorch.org/whl/cpu sentence-transformers
> ```
> ragas 0.4 依赖 langchain 0.3.x（`langchain-community.chat_models.vertexai` 在 0.4.x 已移除）。

## 指标口径

| 指标 | 含义 | 越低说明 |
|------|------|---------|
| faithfulness | 答案是否忠实于检索上下文 | 越可能幻觉 |
| answer_relevancy | 答案与问题的相关度 | 答非所问 |
| context_precision | 检索到的上下文是否相关且排位靠前 | 检索噪声多 |
| context_recall | 真值信息是否被检索上下文覆盖 | 检索漏召回 |

## 结果对比（示例数据模式，14 条）

| 指标 | 首轮 2026-08-16 | 二轮 2026-08-16 | 变化 |
|------|:---:|:---:|:---:|
| faithfulness | 0.798 | **0.900** | +0.10 |
| context_precision | 0.643 | **1.000** | +0.36 |
| context_recall | 0.643 | **1.000** | +0.36 |
| answer_relevancy | 0.563 | **0.788** | +0.23 |

### 首轮（2026-08-16）

| 指标 | 得分 |
|------|------|
| faithfulness | 0.798 |
| context_precision | 0.643 |
| context_recall | 0.643 |
| answer_relevancy | 0.563 |

### 首轮解读与问题定位

1. **索引覆盖内（化学品/法规）检索完全可靠**：10 条 context_precision=1.0、context_recall=1.0，
   证明 FAISS 示例索引对已入库内容召回无遗漏。
2. **索引覆盖外（作业票）检索完全失败**：4 条作业票问题 precision/recall 全为 0——作业票数据
   未入示例 FAISS 索引，检索落到无关的化学品/法规向量上。**这是首轮的结构性盲区**。
3. **faithfulness 非全绿暴露幻觉风险**：硫化氢 0.25、甲醇 0.75，即使检索命中，答案仍可能
   掺入模型自身知识；这是 RAGAS 最值得盯的指标。
4. **chem_benzene context_recall=0.0 属真值口径错误**：真值写了常识别名「安息油」，权威目录
   中苯的别名实为「纯苯」，检索本身命中苯。二轮已按权威目录修正真值。

### 二轮修复内容（2026-08-16）

1. **作业票实体入库（真实检索增强）**：`scripts/make_sample_data.py` 新增
   `_permit_extract_entities`，将八大特殊作业（含分级/有效期/气体分析等富属性）写入
   `sample_data/extract/permits.json` 并进入 FAISS 索引（30 条 → 38 条）。作业票问答
   precision/recall 由 0.0 全部修复至 1.0。
2. **答案模板去噪（真实质量改进）**：移除 QA 答案中无来源的「检索路径：图谱命中 X 条 + 向量
   命中 Y 条」调试行，检索命中信息仍保留在返回的 metadata（graph_hits/vector_hits）与
   `sources` 字段，前端展示不受影响。faithfulness 由 0.798 → 0.900。
3. **苯真值按权威目录校准**：golden 集中苯别名「安息油」→「纯苯」，与《危险化学品目录》
   数据一致。chem_benzene precision/recall 由 0.0 → 1.0。

### 二轮剩余短板

- chem_methanol_cas faithfulness 0.667、wp_confined_space_validity faithfulness 0.6：
  非检索问题，答案末尾的「防混淆提醒/通俗比喻」等包装句无证据直接支撑，judge 拆句判为
  不忠实；属 LLM 答案风格可优化点，不影响回答正确性。

### 已知限制

- `answer_relevancy` 生成问题数退化为 1（deepseek 对 `n>1` 返回 1 条），指标稳健性打折。
- judge 与被评模型同为 deepseek，属「自评」，可能存在系统性偏差；样本量仅 14，结论为示意。
- 作业票类问题在示例模式必然低分，不代表完整模式下水平。

## 后续

- 扩充 golden 集到 40+ 条，覆盖三大功能与边界情况。
- 接入 CI：无 LLM 依赖的检索指标（hit@k/MRR）可进 CI 回归；LLM 类指标本地跑、报告留档。
- 完整数据模式跑一轮，对比示例模式的检索覆盖差异。
