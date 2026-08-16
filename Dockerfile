# 化工安全生产合规智能体 —— API / Streamlit 统一镜像
# 用法见 docker-compose.yml 与 docs/DEPLOYMENT.md
FROM python:3.10-slim

# opencv 运行需要 libGL.so.1；缺系统库会在 import cv2 时报错
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用 Docker 层缓存（依赖体积大：torch/ultralytics/sentence-transformers）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码与示例数据（大体积数据/模型经 .dockerignore 排除，运行时以卷挂载）
COPY . .

EXPOSE 8000 8501

# 默认启动后端 API（前端在 compose 中以 command 覆盖）
CMD ["uvicorn", "_005_fastapi.main:app", "--host", "0.0.0.0", "--port", "8000"]
