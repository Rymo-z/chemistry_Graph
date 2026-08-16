"""API 路由注册。"""

from _005_fastapi.routes.chat import router as chat_router
from _005_fastapi.routes.detect import router as detect_router
from _005_fastapi.routes.permit import router as permit_router

ALL_ROUTERS = [chat_router, detect_router, permit_router]

__all__ = ["ALL_ROUTERS", "chat_router", "detect_router", "permit_router"]
