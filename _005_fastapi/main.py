"""FastAPI 应用入口：挂载路由、CORS、生命周期、健康检查。

启动：
    uvicorn _005_fastapi.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from _005_fastapi.routes import ALL_ROUTERS
from common.config import settings
from common.logger import get_logger
from common.neo4j_manager import Neo4jManager

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动日志 / 退出时释放 Neo4j 连接。"""
    logger.info("▶ 启动 %s (v1.0.0)", settings.APP_NAME)
    yield
    Neo4jManager().close()
    logger.info("■ 服务已关闭，Neo4j 连接已释放")


app = FastAPI(
    title=settings.APP_NAME,
    description="化工安全生产合规智能体 API：法规问答 / 隐患识别 / 作业票审核",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：允许内网前端（Streamlit）跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for route in ALL_ROUTERS:
    app.include_router(route)


@app.get("/health", tags=["system"], summary="健康检查")
def health() -> dict[str, object]:
    """返回服务状态与 Neo4j 连通性。"""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "neo4j": Neo4jManager().available,
        "llm_base": settings.LLM_API_BASE,
        "model": settings.LLM_MODEL,
    }
