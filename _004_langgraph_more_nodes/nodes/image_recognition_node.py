"""CV 识别节点：封装 Ultralytics YOLOv8 目标检测（独立工具类）。

- 真实模型加载失败或未安装 ultralytics 时，自动降级为「占位检测结果」，
  保证离线演示链路不中断。
- YoloDetector 以懒加载单例形式提供，后续可直接复用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from common.config import settings
from common.logger import get_logger
from _004_langgraph_more_nodes.agent_state import AgentState

logger = get_logger(__name__)


class YoloDetector:
    """YOLOv8 独立工具类（懒加载单例）。"""

    _instance: Optional["YoloDetector"] = None

    def __new__(cls) -> "YoloDetector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model: Any = None
        return cls._instance

    def load(self) -> Any:
        """加载 YOLO 模型（首次调用才加载，失败抛出异常）。"""
        if self._model is None:
            from ultralytics import YOLO

            model_path = settings.YOLO_MODEL_PATH or settings.YOLO_MODEL_NAME
            logger.info("加载 YOLO 模型: %s", model_path)
            self._model = YOLO(model_path)
        return self._model

    def detect(self, image_path: str | Path, conf: float = 0.25) -> list[dict[str, Any]]:
        """对图片执行目标检测，返回 [{label, confidence, bbox}]。"""
        try:
            model = self.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("YOLO 模型不可用，返回空检测: %s", exc)
            return []

        results = model(str(image_path), conf=conf, verbose=False)
        detections: list[dict[str, Any]] = []
        for result in results:
            names = result.names
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls)
                detections.append(
                    {
                        "label": names[cls_id] if cls_id in names else str(cls_id),
                        "confidence": round(float(box.conf), 4),
                        "bbox": [float(v) for v in box.xyxy[0].tolist()],
                    }
                )
        return detections

    def detect_placeholder(self, image_path: str | Path) -> list[dict[str, Any]]:
        """占位识别：离线演示时模拟一条隐患检测结果。"""
        file_name = Path(image_path).name
        return [
            {
                "label": "疑似管道法兰泄漏",
                "confidence": 0.88,
                "bbox": [0.0, 0.0, 0.0, 0.0],
                "placeholder": True,
                "hint": f"针对图片 {file_name} 的占位检测结果；安装 ultralytics 并配置 YOLO_MODEL_PATH 后可获得真实输出",
            }
        ]


def image_recognition_node(state: AgentState) -> AgentState:
    """识别图片并写回 yolo_detections。无图时返回空列表。"""
    image_path = state.get("image_path")
    if not image_path or not Path(image_path).exists():
        return {"yolo_detections": []}

    detector = YoloDetector()
    try:
        detections = detector.detect(image_path)
        if not detections:
            logger.warning("YOLO 未检出目标，降级为占位结果")
            detections = detector.detect_placeholder(image_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("CV 识别异常，使用占位结果: %s", exc)
        detections = detector.detect_placeholder(image_path)

    logger.info("CV 识别完成，检测到 %d 个目标", len(detections))
    return {"yolo_detections": detections}
