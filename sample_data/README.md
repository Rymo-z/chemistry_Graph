# sample_data — 示例数据集（开箱 demo）

由 `scripts/make_sample_data.py` 从完整数据精选生成，共 20 种化学品、10 部法规、八大特殊作业 8 类。

- `chemicals/chemicals.jsonl`：危化品样例（官方目录 schema，含剧毒标记）
- `regulations.jsonl`：法规元数据 + 摘要（**不含全文**，版权归发布机关）
- `work_permits.json`：GB 30871-2022 八大特殊作业完整副本
- `extract/`：mini 抽取结果（实体结构，离线建索引/图导入用）
- `faiss/`：FAISS 种子索引（RAG 检索直接加载，无需 Neo4j）

在 `.env` 设 `USE_SAMPLE_DATA=true` 后启动服务即用。完整数据请运行 `scripts/rebuild_pipeline.py`。
