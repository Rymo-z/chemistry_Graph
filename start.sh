#!/usr/bin/env bash
# ================= 化工安全生产合规智能体 —— 一键启动（Linux / macOS / Git-Bash）=================
# 检查 .env -> 检查模型 -> 启动后端(8000) + 前端(8501)
set -euo pipefail
cd "$(dirname "$0")"

# ---- 1. 生成 .env ----
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[setup] 已生成 .env —— 请编辑填入 LLM_API_KEY / NEO4J_PASSWORD 等密钥"
fi

# ---- 2. 检查模型（缺失则下载，已有文件自动跳过）----
if [ ! -f models/yolov8n.pt ] || [ ! -f models/bge-large-zh-v1.5/config.json ]; then
    echo "[setup] 模型缺失，运行下载脚本（bge ~1.3GB，请耐心等待）..."
    python scripts/download_models.py
fi

API_PORT="${API_PORT:-8000}"
UI_PORT="${STREAMLIT_PORT:-8501}"

echo "[start] 启动后端 API  http://127.0.0.1:${API_PORT}"
python -m uvicorn _005_fastapi.main:app --host 0.0.0.0 --port "$API_PORT" &
API_PID=$!

echo "[start] 启动前端 UI   http://127.0.0.1:${UI_PORT}"
python -m streamlit run _006_streamlit/app.py --server.port "$UI_PORT" &
UI_PID=$!

trap 'kill $API_PID $UI_PID 2>/dev/null || true' EXIT INT TERM
wait
