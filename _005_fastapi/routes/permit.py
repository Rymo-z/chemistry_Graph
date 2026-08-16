"""POST /check_permit 作业票审核。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from _005_fastapi.dependencies import get_graph_app
from _005_fastapi.models.request_response import PermitCheckRequest, PermitResponse
from common.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["permit"])


@router.post("/check_permit", response_model=PermitResponse, summary="作业票智能审核")
def check_permit(req: PermitCheckRequest, app=Depends(get_graph_app)) -> PermitResponse:
    """调用 PERMIT 子链路，校验缺项与资质合规性。"""
    logger.info("收到 /check_permit 请求，字段数=%d", len(req.permit_data))
    try:
        state = {
            "question": req.question or "请审核该作业票的完整性与合规性",
            "permit_data": req.permit_data,
        }
        result = app.invoke(state)
        permit_result = result.get("permit_result") or {}
        return PermitResponse(
            answer=result.get("output") or "",
            passed=permit_result.get("passed"),
            missing_fields=permit_result.get("missing_fields") or [],
            issues=permit_result.get("issues") or [],
            permit_info=permit_result.get("permit_info"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("/check_permit 处理异常")
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc
