"""腾讯云 OCR 识别生产适配器模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部供应商解耦；
- 绝密脱敏防泄露：secret_key 严禁明文打印在 repr/str 与日志中；
- 延迟动态导入 tencentcloud SDK，未安装时优雅捕获并抛出 OCRError；
- 指数退避重试（针对限流与网络超时）；
- 异常分类转译为统一业务异常体系 (30004~30006)。
"""

import base64
import contextlib
import json
import time
from typing import Any

from app.core.errors import OCRAuthError, OCRError, OCRTimeoutError
from app.integrations._http_retry import run_with_retry
from app.integrations.ocr.protocol import (
    OCROptions,
    OCRPoint,
    OCRPolygon,
    OCRProtocol,
    OCRResult,
    OCRTextBlock,
)


class TencentOCRAdapter(OCRProtocol):
    """腾讯云通用文字识别适配器。"""

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        region: str = "ap-guangzhou",
        endpoint: str = "ocr.tencentcloudapi.com",
        timeout: float = 20.0,
        max_retries: int = 3,
        client: Any | None = None,
        retry_delay_base: float = 0.5,
    ) -> None:
        """初始化腾讯云 OCR 适配器。

        Args:
            secret_id: 腾讯云 SecretId。
            secret_key: 腾讯云 SecretKey。
            region: 腾讯云地域代码，默认 "ap-guangzhou"。
            endpoint: OCR 服务接入域名，默认 "ocr.tencentcloudapi.com"。
            timeout: 单次请求超时时间（秒），默认 20.0。
            max_retries: 偶发错误最大指数重试次数，默认 3。
            client: 可选外部直接注入的 SDK 客户端实例（测试打桩用）。
            retry_delay_base: 重试基础退避时长（秒），默认 0.5。

        Raises:
            OCRError: 必填配置缺失或 SDK 依赖未安装。
        """
        if not secret_id or not secret_id.strip():
            raise OCRError("secret_id 不能为空")
        if not secret_key or not secret_key.strip():
            raise OCRError("secret_key 不能为空")
        if timeout <= 0:
            raise OCRError("timeout 必须大于 0")
        if max_retries < 0:
            raise OCRError("max_retries 不能小于 0")

        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base

        if client is not None:
            self._client = client
        else:
            self._client = self._init_client()

    def _init_client(self) -> Any:
        """动态加载并初始化腾讯云官方 SDK 客户端。

        Raises:
            OCRError: 当环境中缺少 tencentcloud-sdk-python 库时抛出。
        """
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.ocr.v20181119 import ocr_client
        except ImportError as exc:
            raise OCRError(
                "tencentcloud-sdk-python 库未安装，无法初始化 TencentOCRAdapter"
            ) from exc

        cred = credential.Credential(self.secret_id, self.secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = (
            self.endpoint.replace("https://", "").replace("http://", "").rstrip("/")
        )
        http_profile.reqTimeout = int(self.timeout)
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        return ocr_client.OcrClient(cred, self.region, client_profile)

    def _create_request(
        self,
        image_bytes: bytes | None = None,
        image_url: str | None = None,
        options: OCROptions | None = None,
    ) -> Any:
        """构建腾讯云通用印刷体识别请求对象。"""
        try:
            from tencentcloud.ocr.v20181119 import models

            request_obj = models.GeneralBasicOCRRequest()
        except ImportError:

            class _FallbackRequest:
                ImageBase64: str | None = None
                ImageUrl: str | None = None
                LanguageType: str | None = None

            request_obj = _FallbackRequest()

        if image_bytes is not None:
            request_obj.ImageBase64 = base64.b64encode(image_bytes).decode("ascii")
        if image_url is not None:
            request_obj.ImageUrl = image_url

        if options and options.language_type:
            request_obj.LanguageType = options.language_type

        return request_obj

    @staticmethod
    def _classify_error(exc: Exception) -> tuple[bool, bool, str]:
        """将底层异常分类为（是否认证异常, 是否可重试异常, 错误码字符串）。"""
        code = getattr(exc, "code", "")
        message = str(getattr(exc, "message", str(exc)))
        exc_type_name = type(exc).__name__

        # 1. 认证鉴权失败
        if code.startswith("AuthFailure") or "authfailure" in exc_type_name.lower():
            return (True, False, code or "AuthFailure")

        # 2. 超时异常
        is_timeout = (
            isinstance(exc, TimeoutError)
            or "timeout" in exc_type_name.lower()
            or "timed out" in message.lower()
            or "timeout" in message.lower()
        )
        if is_timeout:
            return (False, True, code or "Timeout")

        # 3. 偶发限流与网络服务不可用
        is_rate_limit = (
            "requestlimitexceeded" in code.lower()
            or "requestlimitexceeded" in message.lower()
            or "resourceunavailable" in code.lower()
        )
        if is_rate_limit:
            return (False, True, code or "RequestLimitExceeded")

        return (False, False, code or "GeneralError")

    def _map_exhausted_error(self, exc: Exception, _attempts: int) -> Exception:
        """将未重试或重试耗尽后的腾讯云异常映射为统一 OCR 业务异常。"""
        is_auth, _, error_code = self._classify_error(exc)
        if is_auth:
            return OCRAuthError(
                message=f"腾讯云OCR服务认证或授权失败: {exc!s}",
                details={"error_code": error_code, "secret_id": self.secret_id},
            )
        if (
            error_code == "Timeout"
            or isinstance(exc, TimeoutError)
            or "timeout" in str(exc).lower()
        ):
            return OCRTimeoutError(
                message=f"腾讯云OCR服务调用超时 (重试 {self.max_retries} 次后失败): {exc!s}",
                details={"error_code": error_code, "retries": self.max_retries},
            )
        return OCRError(
            message=f"腾讯云OCR服务异常: {exc!s}",
            details={"error_code": error_code},
        )

    def _execute_with_retry(self, request_obj: Any) -> OCRResult:
        """执行 API 调用并处理指数退避重试与异常转译。"""

        def _invoke() -> OCRResult:
            start_time = time.perf_counter()
            response = self._client.GeneralBasicOCR(request_obj)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return self._parse_response(response, duration_ms)

        def _should_retry(exc: Exception) -> bool:
            is_auth, is_retryable, _ = self._classify_error(exc)
            return not is_auth and is_retryable

        return run_with_retry(
            _invoke,
            max_retries=self.max_retries,
            retry_delay_base=self.retry_delay_base,
            should_retry=_should_retry,
            map_exhausted=self._map_exhausted_error,
            sleep_fn=lambda delay: time.sleep(delay),
        )

    @staticmethod
    def _read_field(obj: Any, attr: str, default: Any = None) -> Any:
        """统一读取 SDK 结构体属性或字典键。"""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        value = getattr(obj, attr, None)
        return default if value is None else value

    @classmethod
    def _parse_polygon(cls, item: Any) -> OCRPolygon | None:
        """从单条腾讯云 OCR 检测结果中解析多边形坐标。"""
        raw_polygon = cls._read_field(item, "Polygon")
        if raw_polygon is None:
            raw_polygon = cls._read_field(item, "ItemPolygon")
        if not raw_polygon:
            return None

        points: list[OCRPoint] = []
        for pt in raw_polygon:
            coord_x = cls._read_field(pt, "X")
            if coord_x is None:
                coord_x = cls._read_field(pt, "x", 0)
            coord_y = cls._read_field(pt, "Y")
            if coord_y is None:
                coord_y = cls._read_field(pt, "y", 0)
            points.append(
                OCRPoint(
                    x=int(coord_x) if coord_x is not None else 0,
                    y=int(coord_y) if coord_y is not None else 0,
                )
            )
        return OCRPolygon(points=tuple(points)) if points else None

    @classmethod
    def _parse_response(cls, response: Any, duration_ms: float) -> OCRResult:
        """将腾讯云 SDK 响应结构体解析为标准 OCRResult 数据模型。"""
        text_detections = cls._read_field(response, "TextDetections") or []
        image_width = cls._read_field(response, "ImageWidth")
        image_height = cls._read_field(response, "ImageHeight")

        blocks: list[OCRTextBlock] = []
        full_text_lines: list[str] = []
        for index, item in enumerate(text_detections, start=1):
            detected_text = str(cls._read_field(item, "DetectedText", "") or "")
            confidence = float(cls._read_field(item, "Confidence", 0.0) or 0.0)
            if confidence > 1.0:
                confidence = round(confidence / 100.0, 4)
            blocks.append(
                OCRTextBlock(
                    text=detected_text,
                    confidence=confidence,
                    polygon=cls._parse_polygon(item),
                    line_number=index,
                )
            )
            full_text_lines.append(detected_text)

        raw_payload: dict[str, Any] | None = None
        if isinstance(response, dict):
            raw_payload = response
        elif hasattr(response, "to_json_string"):
            with contextlib.suppress(Exception):
                raw_payload = json.loads(response.to_json_string())

        return OCRResult(
            full_text="\n".join(full_text_lines),
            blocks=tuple(blocks),
            duration_ms=round(duration_ms, 2),
            image_width=image_width,
            image_height=image_height,
            provider="tencent",
            raw_payload=raw_payload,
        )

    def recognize_image(
        self,
        image_bytes: bytes,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """通过图片二进制字节流识别。"""
        if not image_bytes:
            raise OCRError("待识别图片二进制数据不能为空")
        request_obj = self._create_request(image_bytes=image_bytes, options=options)
        return self._execute_with_retry(request_obj)

    def recognize_url(
        self,
        image_url: str,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """通过图片网络 URL 识别。"""
        if not image_url or not image_url.strip():
            raise OCRError("待识别图片网络地址不能为空")
        request_obj = self._create_request(image_url=image_url, options=options)
        return self._execute_with_retry(request_obj)

    def __repr__(self) -> str:
        """绝密脱敏字符串表示，掩码 secret_key。"""
        return (
            f"TencentOCRAdapter(secret_id='{self.secret_id}', "
            f"secret_key='******', region='{self.region}', "
            f"endpoint='{self.endpoint}', timeout={self.timeout})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["TencentOCRAdapter"]
