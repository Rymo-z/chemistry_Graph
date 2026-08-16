"""POST /detect_hazard 上传图片识别隐患。"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from _005_fastapi.dependencies import get_graph_app
from _005_fastapi.models.request_response import DetectResponse
from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["hazard"])


@router.post("/detect_hazard", response_model=DetectResponse, summary="上传图片识别隐患")
async def detect_hazard(
    file: UploadFile = File(..., description="现场设备/场景图片"),
    question: str | None = Form(default=None, description="可选的文字补充描述"),
    app=Depends(get_graph_app),
) -> DetectResponse:
    """保存图片 → 走 HAZARD 子链路（CV 识别 → 定级 → 整改方案）。"""
    try:
        suffix = Path(file.filename or "upload.jpg").suffix or ".jpg"
        save_path = settings.TMP_DIR / f"{uuid.uuid4().hex}{suffix}"
        settings.TMP_DIR.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(await file.read())
        logger.info("收到 /detect_hazard 请求，图片已保存: %s", save_path)

        state = {
            "question": question or "请识别图片中的隐患并给出整改方案",
            "image_path": str(save_path),
        }
        result = app.invoke(state)
        return DetectResponse(
            answer=result.get("output") or "未生成结果",
            hazard_level=result.get("hazard_level"),
            detections=result.get("yolo_detections") or [],
            sources=result.get("sources") or [],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("/detect_hazard 处理异常")
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc
