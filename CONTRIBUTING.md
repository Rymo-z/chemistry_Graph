# 贡献指南

感谢参与「化工安全生产合规智能体」。请遵循以下约定，让协作更顺畅。

## 开发环境

```bash
git clone <repo-url>
cd chemistry_Graph
pip install -r requirements.txt          # Python 3.10+
cp .env.example .env                     # 填入 LLM_API_KEY 等密钥
python scripts/download_models.py        # 拉取 bge + yolov8n 到 models/
```

## 测试

- 全量测试：`python -m pytest -q`（当前 91 passed + 2 skipped）。
- CI 以 `USE_SAMPLE_DATA=true` 跑全量（用仓库内 `sample_data/`，无需完整数据）。
- 新增功能请同步补测试；数据缺失导致的跳过用 `pytest.skip` 明确标注原因。

## 代码约定

- 遵循仓库既有风格：`from __future__ import annotations`、模块级 docstring 含「职责/用法/坑」。
- 所有外部依赖（LLM / Neo4j / 模型 / 目录）走 `common/config.py`（`.env`），**禁止硬编码路径/密钥**。
- 新脚本放 `scripts/` 并同步在 README 或 Makefile 登记用法。
- 提交信息遵循 Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:` …）。

## 分支与 PR

1. 从 `main` 拉分支：`git checkout -b feat/your-change`
2. 提交：`git commit`（参考仓库历史格式）
3. 推送并开 PR，注明改动点、验证结果（测试/启动）与影响范围。
4. 合并前请确认 `.env` 等敏感文件未被 `git add`。

## 数据版权

法规/事故/目录数据版权归发布机关，**不要**把完整爬取产物提交进仓库；
示例数据放 `sample_data/`（由 `scripts/make_sample_data.py` 生成）。
