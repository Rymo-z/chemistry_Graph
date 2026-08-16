# Docker 部署指南（可选交付）

本仓库以 **脚本优先**（`start.bat` / `start.sh`）为主交付，`docker-compose.yml` 作为「一键体验」备选。
本文件说明 Docker 编排的细节。

## 前置

- 安装 Docker Engine + Docker Compose v2。
- 仓库根目录存在 `.env`（从 `.env.example` 复制，至少填入 `LLM_API_KEY`）。
- 模型权重就绪：本机运行 `python scripts/download_models.py`，产物在 `models/`。
  （Docker 运行时以只读卷挂载 `./models:/app/models`，不入镜像。）

## 一键启动

```bash
docker compose up -d --build
```

| 服务 | 端口 | 说明 |
|------|------|------|
| neo4j | 7687 (Bolt) / 7474 (Browser) | Neo4j 4.4 Community，数据在 named volume |
| api   | 8000 | FastAPI，文档 http://127.0.0.1:8000/docs |
| streamlit | 8501 | 前端 http://127.0.0.1:8501 |

`api` 默认 `USE_SAMPLE_DATA=true`：问答走 `sample_data/` 的 FAISS 种子索引（无需建图）。
`streamlit` 通过 `API_BASE=http://api:8000` 访问后端（容器网络内服务名互指）。

## 完整数据模式

1. 把 `api` 服务的 `USE_SAMPLE_DATA` 改为 `false`。
2. 导入数据到 Neo4j（示例或全量抽取结果均可）：
   ```bash
   docker compose run --rm api python -m _003_create_neo4j_database.graph_importer
   ```
   > 全量数据需先在本机跑 `scripts/rebuild_pipeline.py`（或已挂载 `./_003_create_neo4j_database/storage`）。
3. 重建 FAISS 索引：
   ```bash
   docker compose run --rm api python -m _003_create_neo4j_database.faiss_indexer
   ```
4. 重启 api：`docker compose up -d api`。

## 卷与数据

| 卷/挂载 | 说明 |
|---------|------|
| `neo4j_data` / `neo4j_logs` | Neo4j 数据与日志持久化 |
| `./models:/app/models:ro` | 模型权重只读挂载 |
| `./sample_data:/app/sample_data:ro` | 示例数据只读挂载 |
| `./_003_create_neo4j_database/storage:/app/_003_create_neo4j_database/storage` | FAISS 索引/元数据（读写，供导入/重建） |

清理：`docker compose down`（保留卷）；彻底删除卷：`docker compose down -v`。

## 常见问题

- **构建失败 `libGL.so.1`**：`Dockerfile` 已装 `libgl1 libglib2.0-0`；若自改镜像记得保留。
- **首次构建慢**：`torch` / `ultralytics` / `sentence-transformers` 较大（镜像 ~4GB），依赖层已做缓存，改代码不重装依赖。
- **api 连不上 Neo4j**：确认 `.env` 的 `NEO4J_PASSWORD` 与 compose 内 `NEO4J_AUTH` 一致（compose 会自动读取项目根 `.env` 插值）；容器内连接走 `bolt://neo4j:7687`。
- **端口冲突**：改 `ports` 映射（如 `"8501:8501"` 左侧为宿主机端口）。
- **Windows 上 wget 不可用**：healthcheck 运行在容器内（Debian 镜像自带 wget），与宿主机无关。
