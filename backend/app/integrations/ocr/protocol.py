"""OCR 适配器抽象协议与数据传输模型定义模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部供应商解耦；
- 纯协议与原生强类型模型定义，零框架与业务依赖；
- 遵守 8 个缩写白名单 (api, id, url, ocr, llm, db, config, env)。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class OCRPoint:
    """图像二维平面坐标点。"""

    x: int
    y: int


@dataclass(frozen=True)
class OCRPolygon:
    """文字区块多边形外包围框。"""

    points: tuple[OCRPoint, ...]

    def __post_init__(self) -> None:
        """支持传入任意序列并转换为不可变元组。"""
        if not isinstance(self.points, tuple):
            object.__setattr__(self, "points", tuple(self.points))

    @classmethod
    def from_coordinates(cls, coordinates: Sequence[tuple[int, int]]) -> "OCRPolygon":
        """从坐标元组序列构建多边形对象。"""
        return cls(points=tuple(OCRPoint(x=point[0], y=point[1]) for point in coordinates))


@dataclass(frozen=True)
class OCRTextBlock:
    """OCR 单行/单段文本识别结果块。"""

    text: str
    confidence: float
    polygon: OCRPolygon | None = None
    line_number: int = 0


@dataclass(frozen=True)
class OCRResult:
    """OCR 识别完整结果数据模型。"""

    full_text: str
    blocks: tuple[OCRTextBlock, ...] = field(default_factory=tuple)
    duration_ms: float = 0.0
    image_width: int | None = None
    image_height: int | None = None
    provider: str = "fake"
    raw_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """支持传入任意分块序列并转换为不可变元组。"""
        if not isinstance(self.blocks, tuple):
            object.__setattr__(self, "blocks", tuple(self.blocks))


@dataclass(frozen=True)
class OCROptions:
    """OCR 识别控制参数选项。"""

    language_type: str = "zh"
    need_location: bool = True
    timeout: float = 20.0

    def __post_init__(self) -> None:
        """防御性参数合法性校验。"""
        if self.timeout <= 0.0:
            raise ValueError("timeout must be greater than 0")


@runtime_checkable
class OCRProtocol(Protocol):
    """OCR 识别适配器抽象协议契约。

    定义与具体云厂商或底层模型解耦的通用 OCR 文本识别接口。
    """

    def recognize_image(
        self,
        image_bytes: bytes,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """识别上传的本地/内存图片二进制字节数据。

        Args:
            image_bytes: 图片文件完整二进制字节流。
            options: 可选的识别配置选项。

        Returns:
            OCRResult: 结构化解析结果对象。

        Raises:
            OCRError: 识别失败或服务异常。
            OCRTimeoutError: 识别调用响应超时。
            OCRAuthError: 凭证鉴权拒绝或授权失效。
        """
        ...

    def recognize_url(
        self,
        image_url: str,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """通过图片公网或预签名 URL 进行识别。

        Args:
            image_url: 可访问的图片资源网络链接。
            options: 可选的识别配置选项。

        Returns:
            OCRResult: 结构化解析结果对象。

        Raises:
            OCRError: 识别失败或服务异常。
            OCRTimeoutError: 识别调用响应超时。
            OCRAuthError: 凭证鉴权拒绝或授权失效。
        """
        ...


__all__ = [
    "OCROptions",
    "OCRPoint",
    "OCRPolygon",
    "OCRProtocol",
    "OCRResult",
    "OCRTextBlock",
]
