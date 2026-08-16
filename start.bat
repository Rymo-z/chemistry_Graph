@echo off
setlocal
cd /d "%~dp0"

REM ================= 化工安全生产合规智能体 —— Windows 一键启动 =================
REM 检查 .env -> 检查模型 -> 启动后端(8000) + 前端(8501)

REM ---- 1. 生成 .env ----
if not exist .env (
    echo [setup] 未找到 .env，从模板复制...
    copy /y .env.example .env >nul
    echo [setup] 已生成 .env —— 请编辑填入 LLM_API_KEY / NEO4J_PASSWORD 等密钥
    echo.
)

REM ---- 2. 检查模型（缺失则下载，已有文件自动跳过）----
if not exist "models\yolov8n.pt" goto :need_models
if not exist "models\bge-large-zh-v1.5\config.json" goto :need_models
goto :start_services

:need_models
echo [setup] 模型缺失，运行下载脚本（bge ~1.3GB，请耐心等待）...
python scripts\download_models.py
if errorlevel 1 goto :error

:start_services
echo.
echo [start] 启动后端 API   http://127.0.0.1:8000
start "chemistry-graph-api" cmd /c "python -m uvicorn _005_fastapi.main:app --host 0.0.0.0 --port 8000"
echo [start] 启动前端 UI    http://127.0.0.1:8501
start "chemistry-graph-ui" cmd /c "python -m streamlit run _006_streamlit/app.py --server.port 8501"
echo.
echo 已启动：后端 8000 / 前端 8501（各自独立窗口）。
echo 若首次运行示例模式，请在 .env 中设 USE_SAMPLE_DATA=true。
pause
exit /b 0

:error
echo [error] 模型下载失败，请检查网络，或手动运行：python scripts\download_models.py
pause
exit /b 1
