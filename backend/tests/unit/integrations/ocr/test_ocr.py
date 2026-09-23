"""OCR 适配器单元测试套件。

严格遵循 AGENTS.md 规范：
- 零外部网络外联红线；
- 单元测试毫秒级运行；
- 覆盖异常继承、不可变数据模型、参数边界；
- 覆盖 FakeOCRAdapter 确定性识别、预置映射、故障与时延注入、多线程并发安全；
- 覆盖 TencentOCRAdapter 绝密凭证脱敏、依赖缺失防御、指数退避重试、各类异常转译；
- 覆盖 create_ocr_adapter 工厂函数。
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.errors import AppError, OCRAuthError, OCRError, OCRTimeoutError
from app.integrations.ocr import (
    FakeOCRAdapter,
    OCROptions,
    OCRPoint,
    OCRPolygon,
    OCRProtocol,
    OCRResult,
    OCRTextBlock,
    TencentOCRAdapter,
    create_ocr_adapter,
)


class MockPoint:
    """模拟腾讯云 SDK 坐标点结构。"""

    def __init__(self, x: int, y: int) -> None:
        self.X = x
        self.Y = y


class MockTextDetection:
    """模拟腾讯云 SDK 单行识别项。"""

    def __init__(
        self,
        detected_text: str,
        confidence: float,
        polygon: list[Any] | None = None,
        item_polygon: list[dict[str, int]] | None = None,
    ) -> None:
        self.DetectedText = detected_text
        self.Confidence = confidence
        self.Polygon = polygon
        self.ItemPolygon = item_polygon


class MockOCRResponse:
    """模拟腾讯云 SDK 返回响应对象。"""

    def __init__(
        self,
        text_detections: list[MockTextDetection],
        image_width: int = 1000,
        image_height: int = 800,
    ) -> None:
        self.TextDetections = text_detections
        self.ImageWidth = image_width
        self.ImageHeight = image_height

    def to_json_string(self) -> str:
        return json.dumps(
            {
                "TextDetections": [
                    {
                        "DetectedText": item.DetectedText,
                        "Confidence": item.Confidence,
                    }
                    for item in self.TextDetections
                ],
                "ImageWidth": self.ImageWidth,
                "ImageHeight": self.ImageHeight,
            }
        )


class MockTencentCloudSDKError(Exception):
    """模拟 TencentCloudSDKException。"""

    def __init__(self, code: str, message: str = "Tencent Cloud Error") -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


# ============================================================================
# 1. 异常层次结构与错误码测试
# ============================================================================


def test_ocr_errors_hierarchy() -> None:
    """测试 OCR 业务异常继承关系、状态码及别名属性。"""
    err = OCRError()
    assert issubclass(OCRError, AppError)
    assert err.error_code == 30004
    assert err.code == 30004
    assert err.status_code == 502
    assert err.message == "OCR服务异常"
    assert err.to_dict()["code"] == 30004

    timeout_err = OCRTimeoutError()
    assert issubclass(OCRTimeoutError, OCRError)
    assert timeout_err.error_code == 30005
    assert timeout_err.code == 30005
    assert timeout_err.status_code == 504
    assert timeout_err.message == "OCR服务响应超时"

    auth_err = OCRAuthError()
    assert issubclass(OCRAuthError, OCRError)
    assert auth_err.error_code == 30006
    assert auth_err.code == 30006
    assert auth_err.status_code == 502
    assert auth_err.message == "OCR服务认证或授权失败"

    custom_err = OCRError(
        message="自定义错误",
        details={"hint": "测试"},
        error_code=30004,
        status_code=502,
    )
    assert custom_err.message == "自定义错误"
    assert custom_err.details == {"hint": "测试"}
    assert custom_err.detail == {"hint": "测试"}


# ============================================================================
# 2. 强类型数据模型与不可变性测试
# ============================================================================


def test_ocr_data_structures() -> None:
    """测试数据模型的不可变性、类型转换与边界防御。"""
    point = OCRPoint(x=10, y=20)
    assert point.x == 10
    assert point.y == 20
    with pytest.raises(FrozenInstanceError):
        point.x = 99  # type: ignore[misc]

    polygon_from_seq = OCRPolygon.from_coordinates([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert len(polygon_from_seq.points) == 4
    assert isinstance(polygon_from_seq.points, tuple)
    assert polygon_from_seq.points[0] == OCRPoint(x=0, y=0)

    # 验证传入 list 自动转为 tuple
    polygon_from_list = OCRPolygon(points=[point, point])  # type: ignore[arg-type]
    assert isinstance(polygon_from_list.points, tuple)
    assert len(polygon_from_list.points) == 2

    block = OCRTextBlock(
        text="第一行",
        confidence=0.99,
        polygon=polygon_from_seq,
        line_number=1,
    )
    assert block.text == "第一行"
    assert block.confidence == 0.99
    assert block.line_number == 1
    assert block.polygon == polygon_from_seq

    result = OCRResult(
        full_text="第一行",
        blocks=[block],  # type: ignore[arg-type]
        duration_ms=12.5,
        image_width=640,
        image_height=480,
        provider="fake",
    )
    assert isinstance(result.blocks, tuple)
    assert result.duration_ms == 12.5
    assert result.provider == "fake"
    with pytest.raises(FrozenInstanceError):
        result.full_text = "新文本"  # type: ignore[misc]

    options = OCROptions()
    assert options.language_type == "zh"
    assert options.need_location is True
    assert options.timeout == 20.0

    with pytest.raises(ValueError, match="timeout must be greater than 0"):
        OCROptions(timeout=0.0)

    with pytest.raises(ValueError, match="timeout must be greater than 0"):
        OCROptions(timeout=-5.0)


# ============================================================================
# 3. FakeOCRAdapter 纯内存假实现测试
# ============================================================================


def test_fake_ocr_default_recognition() -> None:
    """测试 FakeOCRAdapter 默认确定性解析与返回结构。"""
    adapter = FakeOCRAdapter()
    assert isinstance(adapter, OCRProtocol)

    result_bytes = adapter.recognize_image(b"sample_test_bytes")
    assert isinstance(result_bytes, OCRResult)
    assert "智练" in result_bytes.full_text
    assert len(result_bytes.blocks) == 3
    assert result_bytes.image_width == 800
    assert result_bytes.image_height == 600
    assert result_bytes.provider == "fake"
    assert result_bytes.duration_ms >= 0.0

    result_url = adapter.recognize_url("https://example.com/test.jpg")
    assert isinstance(result_url, OCRResult)
    assert result_url.full_text == result_bytes.full_text
    assert len(result_url.blocks) == len(result_bytes.blocks)


def test_fake_ocr_empty_input_defense() -> None:
    """测试 FakeOCRAdapter 对空输入图片与 URL 的防御拦截。"""
    adapter = FakeOCRAdapter()

    with pytest.raises(OCRError, match="待识别图片二进制数据不能为空"):
        adapter.recognize_image(b"")

    with pytest.raises(OCRError, match="待识别图片网络地址不能为空"):
        adapter.recognize_url("")

    with pytest.raises(OCRError, match="待识别图片网络地址不能为空"):
        adapter.recognize_url("   ")


def test_fake_ocr_canned_result_match() -> None:
    """测试 FakeOCRAdapter 预置结果匹配与哈希映射。"""
    adapter = FakeOCRAdapter()

    canned_result = OCRResult(
        full_text="自定义预置文本",
        blocks=(),
        duration_ms=1.0,
        provider="canned",
    )

    test_bytes = b"my_specific_image_payload"
    adapter.set_canned_result(test_bytes, canned_result)

    hit_result = adapter.recognize_image(test_bytes)
    assert hit_result.full_text == "自定义预置文本"
    assert hit_result.provider == "canned"

    miss_result = adapter.recognize_image(b"another_image_bytes")
    assert miss_result.full_text != "自定义预置文本"
    assert miss_result.provider == "fake"

    # 针对字符串 Key 进行匹配（通过 image_bytes.decode("utf-8") 命中）
    string_key_result = OCRResult(full_text="按字符串Key匹配", provider="canned_str")
    adapter.set_canned_result("sample_str_key", string_key_result)
    hit_by_str_bytes = adapter.recognize_image(b"sample_str_key")
    assert hit_by_str_bytes.full_text == "按字符串Key匹配"


def test_fake_ocr_inject_failure_and_latency() -> None:
    """测试 FakeOCRAdapter 异常注入、时延注入及 clear 重置。"""
    adapter = FakeOCRAdapter()

    adapter.inject_failure("recognize_image", OCRTimeoutError("模拟超时故障"))
    with pytest.raises(OCRTimeoutError, match="模拟超时故障"):
        adapter.recognize_image(b"test_bytes")

    normal_url_result = adapter.recognize_url("https://example.com/url.png")
    assert normal_url_result is not None

    adapter.inject_failure("recognize_url", OCRAuthError("模拟认证失败"))
    with pytest.raises(OCRAuthError, match="模拟认证失败"):
        adapter.recognize_url("https://example.com/url.png")

    adapter.inject_failure("*", OCRError("全局故障"))
    with pytest.raises(OCRError, match="全局故障"):
        adapter.recognize_image(b"test_bytes")

    adapter.clear()
    recovered = adapter.recognize_image(b"test_bytes")
    assert recovered is not None

    adapter.inject_latency(0.02)
    start_time = time.perf_counter()
    lat_result = adapter.recognize_image(b"test_bytes")
    elapsed = time.perf_counter() - start_time
    assert elapsed >= 0.015
    assert lat_result.duration_ms >= 10.0


def test_fake_ocr_concurrency() -> None:
    """测试 FakeOCRAdapter 在多线程并发调用下的安全性。"""
    adapter = FakeOCRAdapter()

    def worker(worker_id: int) -> bool:
        sample_bytes = f"thread_worker_sample_{worker_id}".encode()
        res = adapter.recognize_image(sample_bytes)
        return len(res.full_text) > 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(30)]
        results = [f.result() for f in futures]

    assert all(results)


def test_fake_ocr_repr() -> None:
    """测试 FakeOCRAdapter 的 repr 与 str 脱敏安全。"""
    adapter = FakeOCRAdapter()
    adapter.set_canned_result("sample", OCRResult(full_text="机密文本"))
    adapter.inject_latency(0.1)

    repr_str = repr(adapter)
    str_val = str(adapter)

    assert "FakeOCRAdapter" in repr_str
    assert "canned_count=1" in repr_str
    assert "机密文本" not in repr_str
    assert repr_str == str_val


# ============================================================================
# 4. TencentOCRAdapter 生产适配器与 Mock 测试
# ============================================================================


def test_tencent_ocr_validation() -> None:
    """测试 TencentOCRAdapter 参数边界校验。"""
    with pytest.raises(OCRError, match="secret_id 不能为空"):
        TencentOCRAdapter(secret_id="", secret_key="valid_key", client=MagicMock())  # noqa: S106

    with pytest.raises(OCRError, match="secret_key 不能为空"):
        TencentOCRAdapter(secret_id="valid_id", secret_key="  ", client=MagicMock())  # noqa: S106

    with pytest.raises(OCRError, match="timeout 必须大于 0"):
        TencentOCRAdapter(
            secret_id="id",  # noqa: S106
            secret_key="key",  # noqa: S106
            timeout=0.0,
            client=MagicMock(),
        )

    with pytest.raises(OCRError, match="max_retries 不能小于 0"):
        TencentOCRAdapter(
            secret_id="id",  # noqa: S106
            secret_key="key",  # noqa: S106
            max_retries=-1,
            client=MagicMock(),
        )


def test_tencent_ocr_secret_masking() -> None:
    """测试 TencentOCRAdapter 的 repr 与 str 绝密脱敏。"""
    real_secret = "sensitive_production_secret_key_999888"  # noqa: S105
    adapter = TencentOCRAdapter(
        secret_id="AKIDtest12345",  # noqa: S106
        secret_key=real_secret,
        region="ap-beijing",
        client=MagicMock(),
    )

    repr_output = repr(adapter)
    str_output = str(adapter)

    assert "AKIDtest12345" in repr_output
    assert "secret_key='******'" in repr_output
    assert real_secret not in repr_output
    assert real_secret not in str_output


def test_tencent_ocr_missing_sdk_raises_error() -> None:
    """测试在缺少 tencentcloud-sdk-python 时抛出清晰的 OCRError。"""
    with pytest.raises(OCRError, match="tencentcloud-sdk-python 库未安装"):
        TencentOCRAdapter(
            secret_id="test_id",  # noqa: S106
            secret_key="test_key",  # noqa: S106
            client=None,
        )


def test_tencent_ocr_empty_input_defense() -> None:
    """测试 TencentOCRAdapter 对空图像与 URL 的防御。"""
    adapter = TencentOCRAdapter(
        secret_id="test_id",  # noqa: S106
        secret_key="test_key",  # noqa: S106
        client=MagicMock(),
    )

    with pytest.raises(OCRError, match="待识别图片二进制数据不能为空"):
        adapter.recognize_image(b"")

    with pytest.raises(OCRError, match="待识别图片网络地址不能为空"):
        adapter.recognize_url("")

    with pytest.raises(OCRError, match="待识别图片网络地址不能为空"):
        adapter.recognize_url("   ")


def test_tencent_ocr_mock_success_recognition() -> None:
    """测试通过 Mock SDK 客户端解析成功返回（含多边形坐标与选项）。"""
    mock_client = MagicMock()

    mock_resp = MockOCRResponse(
        text_detections=[
            MockTextDetection(
                detected_text="第一题: 请简述操作系统内核态与用户态区别",
                confidence=99.0,
                polygon=[
                    MockPoint(10, 10),
                    MockPoint(200, 10),
                    MockPoint(200, 30),
                    MockPoint(10, 30),
                ],
            ),
            MockTextDetection(
                detected_text="第二题: 简述TCP三次握手机制",
                confidence=0.96,
                item_polygon=[{"X": 10, "Y": 40}, {"X": 180, "Y": 40}],
            ),
            MockTextDetection(
                detected_text="参考答案见教材附录",
                confidence=85.0,
                polygon=None,
            ),
        ],
        image_width=1200,
        image_height=900,
    )
    mock_client.GeneralBasicOCR.return_value = mock_resp

    adapter = TencentOCRAdapter(
        secret_id="test_id",  # noqa: S106
        secret_key="test_key",  # noqa: S106
        client=mock_client,
    )

    result_image = adapter.recognize_image(
        b"mock_jpg_binary_stream",
        options=OCROptions(language_type="zh"),
    )

    assert mock_client.GeneralBasicOCR.call_count == 1
    call_req = mock_client.GeneralBasicOCR.call_args[0][0]
    assert call_req.ImageBase64 is not None
    assert call_req.LanguageType == "zh"

    assert len(result_image.blocks) == 3
    assert "第一题" in result_image.full_text
    assert result_image.provider == "tencent"
    assert result_image.image_width == 1200
    assert result_image.image_height == 900
    assert result_image.raw_payload is not None

    block1 = result_image.blocks[0]
    assert block1.line_number == 1
    assert block1.confidence == 0.99
    assert block1.polygon is not None
    assert len(block1.polygon.points) == 4
    assert block1.polygon.points[0] == OCRPoint(x=10, y=10)

    block2 = result_image.blocks[1]
    assert block2.confidence == 0.96
    assert block2.polygon is not None
    assert len(block2.polygon.points) == 2

    block3 = result_image.blocks[2]
    assert block3.confidence == 0.85
    assert block3.polygon is None

    class ItemPolygonObjectDetection:
        def __init__(self) -> None:
            self.DetectedText = "ItemPolygon测试"
            self.Confidence = 89.0
            self.Polygon = None
            self.ItemPolygon = [MockPoint(5, 5), MockPoint(50, 5)]

    mock_client.reset_mock()
    mock_client.GeneralBasicOCR.return_value = MockOCRResponse(
        text_detections=[ItemPolygonObjectDetection()]  # type: ignore[list-item]
    )
    result_item_polygon = adapter.recognize_image(b"item_polygon_test")
    assert result_item_polygon.blocks[0].polygon is not None
    assert result_item_polygon.blocks[0].polygon.points[0] == OCRPoint(5, 5)


def test_tencent_ocr_auth_failure_mapping() -> None:
    """测试认证鉴权失败立即转译为 OCRAuthError 且不进行无意义重试。"""
    mock_client = MagicMock()
    mock_client.GeneralBasicOCR.side_effect = MockTencentCloudSDKError(
        code="AuthFailure.SecretIdNotFound",
        message="SecretId not found in cloud account",
    )

    adapter = TencentOCRAdapter(
        secret_id="bad_id",  # noqa: S106
        secret_key="bad_key",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=mock_client,
    )

    with pytest.raises(OCRAuthError) as exc_info:
        adapter.recognize_image(b"any_bytes")

    assert exc_info.value.error_code == 30006
    assert exc_info.value.status_code == 502
    assert "AuthFailure.SecretIdNotFound" in str(exc_info.value)
    assert mock_client.GeneralBasicOCR.call_count == 1


def test_tencent_ocr_timeout_retry_and_mapping() -> None:
    """测试网络超时触发 3 次指数重试后最终转译为 OCRTimeoutError。"""
    mock_client = MagicMock()
    mock_client.GeneralBasicOCR.side_effect = TimeoutError("Connection to OCR endpoint timed out")

    adapter = TencentOCRAdapter(
        secret_id="test_id",  # noqa: S106
        secret_key="test_key",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=mock_client,
    )

    with pytest.raises(OCRTimeoutError) as exc_info:
        adapter.recognize_image(b"test_bytes")

    assert exc_info.value.error_code == 30005
    assert exc_info.value.status_code == 504
    assert "重试 3 次后失败" in str(exc_info.value)
    # 初始 1 次 + 重试 3 次 = 4 次调用
    assert mock_client.GeneralBasicOCR.call_count == 4


def test_tencent_ocr_rate_limit_retry_success() -> None:
    """测试接口限流触发重试并在重试中成功恢复。"""
    mock_client = MagicMock()
    success_resp = MockOCRResponse(
        text_detections=[MockTextDetection("恢复后的文字", 95.0)],
    )

    mock_client.GeneralBasicOCR.side_effect = [
        MockTencentCloudSDKError(code="RequestLimitExceeded", message="Too many requests"),
        MockTencentCloudSDKError(code="RequestLimitExceeded", message="Too many requests"),
        success_resp,
    ]

    adapter = TencentOCRAdapter(
        secret_id="test_id",  # noqa: S106
        secret_key="test_key",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=mock_client,
    )

    res = adapter.recognize_url("https://example.com/retry.png")
    assert res.full_text == "恢复后的文字"
    assert mock_client.GeneralBasicOCR.call_count == 3


def test_tencent_ocr_generic_error_mapping() -> None:
    """测试图像解码失败等业务错误转译为 OCRError。"""
    mock_client = MagicMock()
    mock_client.GeneralBasicOCR.side_effect = MockTencentCloudSDKError(
        code="FailedOperation.ImageDecodeFailed",
        message="Cannot decode uploaded image format",
    )

    adapter = TencentOCRAdapter(
        secret_id="test_id",  # noqa: S106
        secret_key="test_key",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=mock_client,
    )

    with pytest.raises(OCRError) as exc_info:
        adapter.recognize_image(b"corrupted_image")

    assert exc_info.value.error_code == 30004
    assert exc_info.value.status_code == 502
    assert "FailedOperation.ImageDecodeFailed" in str(exc_info.value)
    assert mock_client.GeneralBasicOCR.call_count == 1


# ============================================================================
# 5. 工厂函数与顶级模块导出测试
# ============================================================================


def test_create_ocr_adapter_factory() -> None:
    """测试 create_ocr_adapter 工厂函数的分发与参数校验。"""
    fake_adapter = create_ocr_adapter("fake")
    assert isinstance(fake_adapter, FakeOCRAdapter)

    fake_case_adapter = create_ocr_adapter("  FAKE  ")
    assert isinstance(fake_case_adapter, FakeOCRAdapter)

    mock_client = MagicMock()
    tencent_adapter = create_ocr_adapter(
        "tencent",
        secret_id="id123",  # noqa: S106
        secret_key="key456",  # noqa: S106
        region="ap-shanghai",
        client=mock_client,
    )
    assert isinstance(tencent_adapter, TencentOCRAdapter)

    with pytest.raises(OCRError, match="secret_id 与 secret_key 均为必填配置参数"):
        create_ocr_adapter("tencent", secret_id=None, secret_key="key")  # noqa: S106

    with pytest.raises(OCRError, match="secret_id 与 secret_key 均为必填配置参数"):
        create_ocr_adapter("tencent", secret_id="id", secret_key=None)  # noqa: S106

    with pytest.raises(OCRError, match="不支持的 OCR 适配器类型"):
        create_ocr_adapter("aliyun")


def test_fake_ocr_unicode_decode_fallback() -> None:
    """测试 FakeOCRAdapter 处理非法 UTF-8 字节的容错。"""
    adapter = FakeOCRAdapter()
    invalid_utf8_bytes = b"\xff\xfe\xfd\xfc"

    custom_result = OCRResult(full_text="非标准字节流命中", provider="canned")
    adapter.set_canned_result(invalid_utf8_bytes, custom_result)

    result = adapter.recognize_image(invalid_utf8_bytes)
    assert result.full_text == "非标准字节流命中"

    # 未匹配的非法 UTF-8 字节
    unregistered_invalid = b"\xff\xaa\xbb"
    default_result = adapter.recognize_image(unregistered_invalid)
    assert "智练" in default_result.full_text


def test_tencent_ocr_dict_response_parsing() -> None:
    """测试 TencentOCRAdapter 对字典格式响应与小写坐标属性的解析。"""
    dict_detection = {
        "DetectedText": "字典格式识别文本",
        "Confidence": 92.5,
        "Polygon": [
            {"X": 15, "Y": 25},
            {"x": 105, "y": 25},
        ],
    }

    mock_client = MagicMock()
    mock_client.GeneralBasicOCR.return_value = {
        "TextDetections": [dict_detection],
        "ImageWidth": 1920,
        "ImageHeight": 1080,
    }

    adapter = TencentOCRAdapter(
        secret_id="id",  # noqa: S106
        secret_key="key",  # noqa: S106
        client=mock_client,
    )

    result = adapter.recognize_image(b"valid_image_bytes")
    assert result.full_text == "字典格式识别文本"
    assert result.image_width == 1920
    assert result.image_height == 1080
    assert len(result.blocks) == 1
    assert result.blocks[0].polygon is not None
    assert result.blocks[0].polygon.points[0] == OCRPoint(15, 25)
    assert result.blocks[0].polygon.points[1] == OCRPoint(105, 25)


def test_tencent_ocr_lowercase_point_objects() -> None:
    """测试 TencentOCRAdapter 处理仅具有小写 x, y 属性的坐标对象及 to_json_string 异常。"""

    class LowercasePoint:
        def __init__(self, x: int, y: int) -> None:
            self.x = x
            self.y = y

    class FaultyJsonResponse:
        def __init__(self) -> None:
            self.TextDetections = [
                MockTextDetection(
                    detected_text="测试小写属性",
                    confidence=0.88,
                    polygon=[LowercasePoint(30, 40)],
                )
            ]

        def to_json_string(self) -> str:
            raise RuntimeError("JSON 序列化失败")

    mock_client = MagicMock()
    mock_client.GeneralBasicOCR.return_value = FaultyJsonResponse()

    adapter = TencentOCRAdapter(
        secret_id="id",  # noqa: S106
        secret_key="key",  # noqa: S106
        client=mock_client,
    )

    result = adapter.recognize_image(b"valid_image_bytes")
    assert result.full_text == "测试小写属性"
    assert result.blocks[0].polygon is not None
    assert result.blocks[0].polygon.points[0] == OCRPoint(30, 40)
    assert result.raw_payload is None


def test_tencent_ocr_sdk_mock_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试在安装了 tencentcloud SDK 时的初始化与请求对象构造分支。"""
    import sys
    from types import ModuleType

    # 创建虚拟的 tencentcloud 模块族
    tc_module = ModuleType("tencentcloud")
    tc_common = ModuleType("tencentcloud.common")
    tc_credential = ModuleType("tencentcloud.common.credential")
    tc_profile = ModuleType("tencentcloud.common.profile")
    tc_cprofile = ModuleType("tencentcloud.common.profile.client_profile")
    tc_hprofile = ModuleType("tencentcloud.common.profile.http_profile")
    tc_ocr = ModuleType("tencentcloud.ocr")
    tc_v20181119 = ModuleType("tencentcloud.ocr.v20181119")
    tc_ocr_client = ModuleType("tencentcloud.ocr.v20181119.ocr_client")
    tc_models = ModuleType("tencentcloud.ocr.v20181119.models")

    class FakeCredential:
        def __init__(self, secret_id: str, secret_key: str) -> None:
            self.secret_id = secret_id
            self.secret_key = secret_key

    class FakeHttpProfile:
        endpoint: str = ""
        reqTimeout: int = 0  # noqa: N815

    class FakeClientProfile:
        httpProfile: Any = None  # noqa: N815

    class FakeOcrClient:
        def __init__(self, cred: Any, region: str, profile: Any) -> None:
            self.cred = cred
            self.region = region
            self.profile = profile

        def GeneralBasicOCR(self, req: Any) -> Any:  # noqa: N802
            return MockOCRResponse([MockTextDetection("SDK分支成功", 99.0)])

    class FakeGeneralBasicOCRRequest:
        ImageBase64: str | None = None
        ImageUrl: str | None = None
        LanguageType: str | None = None

    tc_credential.Credential = FakeCredential  # type: ignore[attr-defined]
    tc_hprofile.HttpProfile = FakeHttpProfile  # type: ignore[attr-defined]
    tc_cprofile.ClientProfile = FakeClientProfile  # type: ignore[attr-defined]
    tc_ocr_client.OcrClient = FakeOcrClient  # type: ignore[attr-defined]
    tc_models.GeneralBasicOCRRequest = FakeGeneralBasicOCRRequest  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "tencentcloud", tc_module)
    monkeypatch.setitem(sys.modules, "tencentcloud.common", tc_common)
    monkeypatch.setitem(sys.modules, "tencentcloud.common.credential", tc_credential)
    monkeypatch.setitem(sys.modules, "tencentcloud.common.profile", tc_profile)
    monkeypatch.setitem(sys.modules, "tencentcloud.common.profile.client_profile", tc_cprofile)
    monkeypatch.setitem(sys.modules, "tencentcloud.common.profile.http_profile", tc_hprofile)
    monkeypatch.setitem(sys.modules, "tencentcloud.ocr", tc_ocr)
    monkeypatch.setitem(sys.modules, "tencentcloud.ocr.v20181119", tc_v20181119)
    monkeypatch.setitem(sys.modules, "tencentcloud.ocr.v20181119.ocr_client", tc_ocr_client)
    monkeypatch.setitem(sys.modules, "tencentcloud.ocr.v20181119.models", tc_models)

    # 此时无需传 client，触发 _init_client
    adapter = TencentOCRAdapter(
        secret_id="akid_test",  # noqa: S106
        secret_key="secret_test",  # noqa: S106
        region="ap-guangzhou",
        timeout=15.0,
    )
    assert isinstance(adapter._client, FakeOcrClient)

    res = adapter.recognize_image(b"test_stream")
    assert res.full_text == "SDK分支成功"


def test_ocr_init_exports() -> None:
    """测试 app.integrations.ocr 顶级包导出符号的完整性与字典序。"""
    import app.integrations.ocr as ocr_module

    expected_exports = [
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

    assert ocr_module.__all__ == expected_exports
    assert ocr_module.__all__ == sorted(ocr_module.__all__)

    for name in expected_exports:
        assert hasattr(ocr_module, name), f"Missing exported symbol: {name}"
