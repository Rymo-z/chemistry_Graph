# 化工安全生产合规智能体 —— 常用命令
# Windows 无 make 时用 start.bat / scripts/ 下的脚本即可。
PY      ?= python

.PHONY: help setup deps download-models sample data start test docker-up docker-down clean

help: ## 显示可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

setup: ## 初始化：从模板复制 .env
	@if [ ! -f .env ]; then cp .env.example .env && echo "已生成 .env，请填入密钥"; else echo ".env 已存在"; fi

deps: ## 安装运行依赖
	$(PY) -m pip install -r requirements.txt

download-models: ## 下载模型权重到 models/（bge + yolov8n）
	$(PY) scripts/download_models.py

sample: ## 生成示例数据集 sample_data/
	$(PY) scripts/make_sample_data.py

data: ## 一键重建数据链路（需 Neo4j + 模型就绪）
	$(PY) scripts/rebuild_pipeline.py

start: ## 启动后端 API(8000) + 前端 Streamlit(8501)
	$(PY) -m uvicorn _005_fastapi.main:app --host 0.0.0.0 --port 8000 & \
	$(PY) -m streamlit run _006_streamlit/app.py --server.port 8501

test: ## 运行全量测试
	$(PY) -m pytest -q

docker-up: ## Docker 一键起 Neo4j + API + Streamlit
	docker compose up -d --build

docker-down: ## 停止 Docker 服务
	docker compose down

clean: ## 清理临时产物
	rm -rf tmp/ logs/*.log .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
