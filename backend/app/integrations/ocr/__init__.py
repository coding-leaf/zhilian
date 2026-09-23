"""OCR 文字识别适配器模块。

导出 OCRProtocol 抽象协议契约、FakeOCRAdapter 内存假实现、
TencentOCRAdapter 腾讯云生产适配器与工厂函数。
"""

from app.integrations.ocr.factory import create_ocr_adapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.ocr.protocol import (
    OCROptions,
    OCRPoint,
    OCRPolygon,
    OCRProtocol,
    OCRResult,
    OCRTextBlock,
)
from app.integrations.ocr.tencent import TencentOCRAdapter

__all__ = [
    "FakeOCRAdapter",
    "OCROptions",
    "OCRPoint",
    "OCRPolygon",
    "OCRProtocol",
    "OCRResult",
    "OCRTextBlock",
    "TencentOCRAdapter",
    "create_ocr_adapter",
]
