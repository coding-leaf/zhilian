"""百度智能云 OCR 适配器单元测试套件。

严格遵循 AGENTS.md 规范：
- 零外部网络外联红线；
- 单元测试毫秒级运行；
- 覆盖参数边界与空输入拦截；
- 覆盖 Token 获取、缓存复用与过期刷新（Mock HTTP）；
- 覆盖图像/URL/PDF 单页识别成功流转与坐标多边形转换；
- 覆盖错误码 110/111/100/17/18 与 HTTP 异常分类转译；
- 覆盖超时与 QPS 限流指数退避重试；
- 覆盖敏感凭据脱敏防护与工厂方法分发。
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.errors import OCRAuthError, OCRError, OCRQuotaError, OCRTimeoutError
from app.integrations.ocr import (
    BaiduOCRAdapter,
    OCROptions,
    OCRPoint,
    OCRProtocol,
    OCRResult,
    create_ocr_adapter,
)


def _build_mock_client_with_responses(responses: list[Any]) -> MagicMock:
    """构建按调用次序返回响应或抛出异常的 mock httpx.Client。"""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = responses
    return mock_client


# ============================================================================
# 1. 适配器构造校验与敏感信息脱敏测试
# ============================================================================


def test_baidu_ocr_adapter_initialization_validation() -> None:
    """测试 BaiduOCRAdapter 参数校验防御。"""
    mock_client = MagicMock(spec=httpx.Client)

    with pytest.raises(OCRError, match="api_key 不能为空"):
        BaiduOCRAdapter(api_key="", secret_key="sec_key", client=mock_client)  # noqa: S106

    with pytest.raises(OCRError, match="secret_key 不能为空"):
        BaiduOCRAdapter(api_key="api_key", secret_key="  ", client=mock_client)  # noqa: S106

    with pytest.raises(OCRError, match="timeout 必须大于 0"):
        BaiduOCRAdapter(
            api_key="api_key",
            secret_key="sec_key",  # noqa: S106
            timeout=0.0,
            client=mock_client,
        )

    with pytest.raises(OCRError, match="max_retries 不能小于 0"):
        BaiduOCRAdapter(
            api_key="api_key",
            secret_key="sec_key",  # noqa: S106
            max_retries=-1,
            client=mock_client,
        )


def test_baidu_ocr_adapter_endpoint_normalization() -> None:
    """测试 endpoint 协议头补齐与尾部斜杠清理。"""
    mock_client = MagicMock(spec=httpx.Client)

    adapter_no_protocol = BaiduOCRAdapter(
        api_key="test_key",
        secret_key="test_secret",  # noqa: S106
        endpoint="aip.baidubce.com/",
        client=mock_client,
    )
    assert adapter_no_protocol.endpoint == "https://aip.baidubce.com"

    adapter_with_protocol = BaiduOCRAdapter(
        api_key="test_key",
        secret_key="test_secret",  # noqa: S106
        endpoint="http://custom.baidu.com//",
        client=mock_client,
    )
    assert adapter_with_protocol.endpoint == "http://custom.baidu.com"


def test_baidu_ocr_adapter_credential_masking() -> None:
    """测试 __repr__ 与 __str__ 中绝密凭证的脱敏防护。"""
    real_api_key = "abcdef123456789"
    real_secret = "sensitive_baidu_secret_key_888"  # noqa: S105

    adapter = BaiduOCRAdapter(
        api_key=real_api_key,
        secret_key=real_secret,
        client=MagicMock(spec=httpx.Client),
    )

    repr_str = repr(adapter)
    str_val = str(adapter)

    assert "abcd****" in repr_str
    assert "secret_key='******'" in repr_str
    assert real_secret not in repr_str
    assert real_secret not in str_val


def test_baidu_ocr_adapter_close_lifecycle() -> None:
    """测试 close 生命周期调用安全。"""
    external_client = MagicMock(spec=httpx.Client)
    adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        client=external_client,
    )
    adapter.close()
    external_client.close.assert_not_called()

    # 内部管理 client 时应调用 close
    internal_adapter = BaiduOCRAdapter(api_key="key", secret_key="sec")  # noqa: S106
    mock_internal = MagicMock(spec=httpx.Client)
    internal_adapter._client = mock_internal
    internal_adapter.close()
    mock_internal.close.assert_called_once()


# ============================================================================
# 2. Token 获取、缓存复用与过期刷新测试
# ============================================================================


def test_baidu_ocr_token_fetch_and_caching() -> None:
    """测试首次获取 Token、有效期内复用以及过期后自动刷新机制。"""
    token_resp_1 = httpx.Response(
        status_code=200,
        json={"access_token": "token_v1", "expires_in": 100},
    )
    recognize_resp_1 = httpx.Response(
        status_code=200,
        json={"words_result": [{"words": "第一段文字"}]},
    )
    token_resp_2 = httpx.Response(
        status_code=200,
        json={"access_token": "token_v2", "expires_in": 100},
    )
    recognize_resp_2 = httpx.Response(
        status_code=200,
        json={"words_result": [{"words": "第二段文字"}]},
    )

    client = _build_mock_client_with_responses(
        [token_resp_1, recognize_resp_1, token_resp_2, recognize_resp_2]
    )

    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    # 1. 第一次调用：请求 Token 并执行识别
    res1 = adapter.recognize_image(b"fake_image_bytes_1")
    assert res1.full_text == "第一段文字"
    assert adapter._token == "token_v1"  # noqa: S105

    # 2. 短时间内再次调用：应直接命中缓存 Token，不发起 Token 请求
    client.post.side_effect = [recognize_resp_1]
    res1_cached = adapter.recognize_image(b"fake_image_bytes_1")
    assert res1_cached.full_text == "第一段文字"
    assert client.post.call_count == 3  # 1(token) + 1(ocr) + 1(ocr)

    # 3. 模拟 Token 临界过期 (剩余时间小于 60 秒)
    adapter._token_expires_at = time.time() + 30.0
    client.post.side_effect = [token_resp_2, recognize_resp_2]
    res2 = adapter.recognize_image(b"fake_image_bytes_2")
    assert res2.full_text == "第二段文字"
    assert adapter._token == "token_v2"  # noqa: S105


def test_baidu_ocr_token_fetch_errors() -> None:
    """测试获取 Token 时的鉴权错误、配额超限与网络异常分类转译。"""
    client = MagicMock(spec=httpx.Client)

    # 鉴权拒绝 100 / invalid_client
    client.post.return_value = httpx.Response(
        status_code=200,
        json={"error": "invalid_client", "error_description": "unknown client id"},
    )
    adapter = BaiduOCRAdapter(api_key="bad_key", secret_key="bad_sec", client=client)  # noqa: S106
    with pytest.raises(OCRAuthError, match="百度OCR鉴权凭据无效"):
        adapter.recognize_image(b"test")

    # 配额超限 17
    client.post.return_value = httpx.Response(
        status_code=200,
        json={"error_code": 17, "error_msg": "Open api daily request limit reached"},
    )
    adapter_quota = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    with pytest.raises(OCRQuotaError, match="百度OCR调用配额超限"):
        adapter_quota.recognize_image(b"test")

    # HTTP 401 鉴权失败
    client.post.return_value = httpx.Response(
        status_code=401,
        text="Unauthorized",
    )
    adapter_401 = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    with pytest.raises(OCRAuthError, match="HTTP 401"):
        adapter_401.recognize_image(b"test")

    # 超时异常转译
    client.post.side_effect = httpx.TimeoutException("Token request timeout")
    adapter_timeout = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    with pytest.raises(OCRTimeoutError, match="百度OCR获取Token超时"):
        adapter_timeout.recognize_image(b"test")

    # 响应缺少 access_token 字段
    client.post.side_effect = None
    client.post.return_value = httpx.Response(status_code=200, json={"status": "ok"})
    adapter_empty = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    with pytest.raises(OCRAuthError, match="未包含 access_token"):
        adapter_empty.recognize_image(b"test")


# ============================================================================
# 3. 图片、URL 与 PDF 识别流转及坐标转换测试
# ============================================================================


def test_baidu_ocr_image_recognition_success() -> None:
    """测试通过图片二进制识别成功并转换为 OCRTextBlock 与 OCRPolygon。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    ocr_resp = httpx.Response(
        status_code=200,
        json={
            "words_result": [
                {
                    "words": "题目 1: 简述操作系统进程与线程的区别",
                    "probability": {"average": 0.985},
                    "location": {"left": 20, "top": 30, "width": 400, "height": 50},
                },
                {
                    "words": "题目 2: 简述死锁的四个必要条件",
                    "probability": 96.0,
                    "location": {"left": 20, "top": 100, "width": 380, "height": 45},
                },
                {
                    "words": "无坐标文字项",
                    "probability": "0.85",
                },
            ],
            "image_width": 1024,
            "image_height": 768,
        },
    )

    client = _build_mock_client_with_responses([token_resp, ocr_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    result = adapter.recognize_image(b"valid_image_bytes")

    assert isinstance(result, OCRResult)
    assert result.provider == "baidu"
    assert len(result.blocks) == 3
    assert "简述操作系统进程与线程的区别" in result.full_text
    assert result.image_width == 1024
    assert result.image_height == 768
    assert result.duration_ms >= 0.0

    # 块 1：带位置与概率字典
    b1 = result.blocks[0]
    assert b1.line_number == 1
    assert b1.text == "题目 1: 简述操作系统进程与线程的区别"
    assert b1.confidence == 0.985
    assert b1.polygon is not None
    assert len(b1.polygon.points) == 4
    assert b1.polygon.points[0] == OCRPoint(x=20, y=30)
    assert b1.polygon.points[1] == OCRPoint(x=420, y=30)
    assert b1.polygon.points[2] == OCRPoint(x=420, y=80)
    assert b1.polygon.points[3] == OCRPoint(x=20, y=80)

    # 块 2：概率数值百分比归一化 (96.0 -> 0.96)
    b2 = result.blocks[1]
    assert b2.line_number == 2
    assert b2.confidence == 0.96
    assert b2.polygon is not None

    # 块 3：无坐标与字符串概率
    b3 = result.blocks[2]
    assert b3.line_number == 3
    assert b3.confidence == 0.85
    assert b3.polygon is None


def test_baidu_ocr_url_recognition_success() -> None:
    """测试通过图片公网 URL 发起识别。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    ocr_resp = httpx.Response(
        status_code=200,
        json={"words_result": [{"words": "URL识别结果"}]},
    )

    client = _build_mock_client_with_responses([token_resp, ocr_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    result = adapter.recognize_url(
        "https://example.com/test.png",
        options=OCROptions(language_type="CHN_ENG"),
    )

    assert result.full_text == "URL识别结果"
    # 验证请求参数
    call_args = client.post.call_args_list[1]
    assert call_args[1]["data"]["url"] == "https://example.com/test.png"
    assert call_args[1]["data"]["language_type"] == "CHN_ENG"


def test_baidu_ocr_pdf_page_recognition_success() -> None:
    """测试识别 PDF 文档单页内容。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    ocr_resp = httpx.Response(
        status_code=200,
        json={"words_result": [{"words": "PDF第一页解析内容"}]},
    )

    client = _build_mock_client_with_responses([token_resp, ocr_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    result = adapter.recognize_pdf_page(b"%PDF-1.4 mock content", page_number=2)

    assert result.full_text == "PDF第一页解析内容"
    call_args = client.post.call_args_list[1]
    assert call_args[1]["data"]["pdf_file_num"] == "2"
    assert "pdf_file" in call_args[1]["data"]


def test_baidu_ocr_empty_input_defense() -> None:
    """测试对空图片、空URL、空PDF和非法页码的防御。"""
    adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        client=MagicMock(spec=httpx.Client),
    )

    with pytest.raises(OCRError, match="待识别图片二进制数据不能为空"):
        adapter.recognize_image(b"")

    with pytest.raises(OCRError, match="待识别图片网络地址不能为空"):
        adapter.recognize_url("")

    with pytest.raises(OCRError, match="待识别图片网络地址不能为空"):
        adapter.recognize_url("   ")

    with pytest.raises(OCRError, match="待识别PDF二进制数据不能为空"):
        adapter.recognize_pdf_page(b"")

    with pytest.raises(OCRError, match="page_number 必须大于或等于 1"):
        adapter.recognize_pdf_page(b"%PDF", page_number=0)


# ============================================================================
# 4. 业务错误码映射与重试逻辑测试 (110/111/100/17/18/超时)
# ============================================================================


def test_baidu_ocr_token_invalid_error_clears_cache_and_raises_auth_error() -> None:
    """测试错误码 110/111 (令牌失效/过期) 清空 Token 缓存并抛出 OCRAuthError。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "expired_token", "expires_in": 3600},
    )
    error_110_resp = httpx.Response(
        status_code=200,
        json={"error_code": 110, "error_msg": "Access token invalid or no longer valid"},
    )

    client = _build_mock_client_with_responses([token_resp, error_110_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    with pytest.raises(OCRAuthError) as exc_info:
        adapter.recognize_image(b"test_image")

    assert exc_info.value.error_code == 30006
    assert "110" in str(exc_info.value)
    # 确认 Token 缓存已清空
    assert adapter._token is None


def test_baidu_ocr_error_100_auth_error_mapping() -> None:
    """测试错误码 100 映射为 OCRAuthError。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    error_100_resp = httpx.Response(
        status_code=200,
        json={"error_code": 100, "error_msg": "Invalid parameter"},
    )

    client = _build_mock_client_with_responses([token_resp, error_100_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    with pytest.raises(OCRAuthError) as exc_info:
        adapter.recognize_image(b"test_image")

    assert exc_info.value.error_code == 30006
    assert "100" in str(exc_info.value)


def test_baidu_ocr_error_17_quota_error_mapping() -> None:
    """测试错误码 17 (当日调用配额超限) 映射为 OCRQuotaError 且不重试。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    error_17_resp = httpx.Response(
        status_code=200,
        json={"error_code": 17, "error_msg": "Open api daily request limit reached"},
    )

    client = _build_mock_client_with_responses([token_resp, error_17_resp])
    adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=client,
    )

    with pytest.raises(OCRQuotaError) as exc_info:
        adapter.recognize_image(b"test_image")

    assert exc_info.value.error_code == 30019
    assert exc_info.value.status_code == 429
    # 确认未执行无意义重试
    assert client.post.call_count == 2  # 1 次 token + 1 次 ocr


def test_baidu_ocr_error_18_qps_rate_limit_retry_and_exhaustion() -> None:
    """测试错误码 18 (QPS 并发超限) 指数退避重试并最终抛出 OCRQuotaError。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    error_18_resp = httpx.Response(
        status_code=200,
        json={"error_code": 18, "error_msg": "Open api qps request limit reached"},
    )

    # 1 次 token + 3 次重试 (共 4 次 OCR 调用)
    client = _build_mock_client_with_responses(
        [token_resp, error_18_resp, error_18_resp, error_18_resp, error_18_resp]
    )
    adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=client,
    )

    with pytest.raises(OCRQuotaError) as exc_info:
        adapter.recognize_image(b"test_image")

    assert exc_info.value.error_code == 30019
    assert exc_info.value.status_code == 429
    assert "重试 3 次后超限" in str(exc_info.value)
    # 1 token + 4 ocr = 5 calls
    assert client.post.call_count == 5


def test_baidu_ocr_timeout_retry_and_mapping() -> None:
    """测试网络超时重试 3 次后转译为 OCRTimeoutError。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    timeout_exc = httpx.TimeoutException("Read timed out")

    client = _build_mock_client_with_responses(
        [token_resp, timeout_exc, timeout_exc, timeout_exc, timeout_exc]
    )
    adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=client,
    )

    with pytest.raises(OCRTimeoutError) as exc_info:
        adapter.recognize_image(b"test_image")

    assert exc_info.value.error_code == 30005
    assert exc_info.value.status_code == 504
    assert client.post.call_count == 5


def test_baidu_ocr_rate_limit_retry_success() -> None:
    """测试 QPS 限流在重试中成功恢复返回。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    error_18_resp = httpx.Response(
        status_code=200,
        json={"error_code": 18, "error_msg": "Open api qps request limit reached"},
    )
    success_resp = httpx.Response(
        status_code=200,
        json={"words_result": [{"words": "重试成功识别内容"}]},
    )

    client = _build_mock_client_with_responses([token_resp, error_18_resp, success_resp])
    adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        max_retries=3,
        retry_delay_base=0.001,
        client=client,
    )

    res = adapter.recognize_image(b"test_bytes")
    assert res.full_text == "重试成功识别内容"
    assert client.post.call_count == 3


# ============================================================================
# 5. 工厂函数分发与协议契约测试
# ============================================================================


def test_create_ocr_adapter_baidu_factory() -> None:
    """测试 create_ocr_adapter 对 baidu 类型的分发与凭证注入。"""
    mock_client = MagicMock(spec=httpx.Client)

    adapter = create_ocr_adapter(
        "baidu",
        api_key="b_key",
        secret_key="b_sec",  # noqa: S106
        client=mock_client,
    )
    assert isinstance(adapter, BaiduOCRAdapter)
    assert isinstance(adapter, OCRProtocol)
    assert adapter.endpoint == "https://aip.baidubce.com"

    # 兼容 secret_id 传参
    adapter_compat = create_ocr_adapter(
        "BAIDU",
        secret_id="compat_key",  # noqa: S106
        secret_key="compat_sec",  # noqa: S106
        endpoint="custom.endpoint.com",
        client=mock_client,
    )
    assert isinstance(adapter_compat, BaiduOCRAdapter)
    assert adapter_compat.api_key == "compat_key"
    assert adapter_compat.endpoint == "https://custom.endpoint.com"

    # 缺少 api_key 或 secret_id
    with pytest.raises(OCRError, match=r"api_key.*均为必填配置参数"):
        create_ocr_adapter("baidu", secret_key="only_secret")  # noqa: S106

    # 缺少 secret_key
    with pytest.raises(OCRError, match=r"api_key.*均为必填配置参数"):
        create_ocr_adapter("baidu", api_key="only_key")


def test_baidu_ocr_thread_safe_token_access() -> None:
    """测试多线程并发请求时 Token 获取的线程安全性。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "thread_safe_token", "expires_in": 3600},
    )
    ocr_resp = httpx.Response(
        status_code=200,
        json={"words_result": [{"words": "并发内容"}]},
    )

    client = MagicMock(spec=httpx.Client)
    # 模拟第一次返回 token，之后全返回 ocr
    client.post.side_effect = [token_resp] + [ocr_resp] * 50

    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    def worker(_: int) -> bool:
        res = adapter.recognize_image(b"thread_bytes")
        return res.full_text == "并发内容"

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker, range(10)))

    assert all(results)
    # 验证 Token 仅获取了 1 次
    first_call_url = client.post.call_args_list[0][0][0]
    assert "oauth/2.0/token" in first_call_url


# ============================================================================
# 6. 深入防御性分支与边界测试
# ============================================================================


def test_baidu_ocr_token_network_and_malformed_errors() -> None:
    """测试获取 Token 时的底层通用网络异常、非 JSON 响应与未知错误码。"""
    client = MagicMock(spec=httpx.Client)

    # 1. 模拟非超时网络异常
    client.post.side_effect = RuntimeError("Socket reset")
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    with pytest.raises(OCRError, match="百度OCR获取Token连接异常"):
        adapter.recognize_image(b"bytes")

    # 2. 模拟响应非 JSON
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.text = "<html>Bad Gateway</html>"
    bad_resp.json.side_effect = ValueError("Invalid JSON")
    client.post.side_effect = [bad_resp]
    with pytest.raises(OCRError, match="百度OCR Token响应格式异常"):
        adapter.recognize_image(b"bytes")

    # 3. 模拟未知业务错误码
    client.post.side_effect = [
        httpx.Response(
            status_code=200,
            json={"error_code": 999, "error_msg": "Unknown baidu error"},
        )
    ]
    with pytest.raises(OCRError, match="百度OCR获取Token失败"):
        adapter.recognize_image(b"bytes")


def test_baidu_ocr_resolve_url_variants() -> None:
    """测试不同 options 及端点前缀下的 URL 解析。"""
    client = MagicMock(spec=httpx.Client)

    # 1. need_location=False
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    url_basic = adapter._resolve_url(OCROptions(need_location=False))
    assert url_basic.endswith("/rest/2.0/ocr/v1/accurate_basic")

    # 2. 端点自带 /rest/2.0/ 路径
    custom_adapter = BaiduOCRAdapter(
        api_key="key",
        secret_key="sec",  # noqa: S106
        endpoint="https://custom.baidu.com/rest/2.0/ocr/v1/general",
        client=client,
    )
    assert custom_adapter._resolve_url(None) == "https://custom.baidu.com/rest/2.0/ocr/v1/general"


def test_baidu_ocr_execute_http_and_json_errors() -> None:
    """测试识别调用时的 HTTP 403 异常、非 JSON 响应与未知业务错误码。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    client = MagicMock(spec=httpx.Client)

    # 1. HTTP 403 鉴权拒绝
    client.post.side_effect = [token_resp, httpx.Response(status_code=403, text="Forbidden")]
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106
    with pytest.raises(OCRAuthError, match="HTTP 403"):
        adapter.recognize_image(b"bytes")
    assert adapter._token is None

    # 2. 识别响应非 JSON
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.text = "Bad Gateway"
    bad_resp.json.side_effect = ValueError("Not JSON")
    adapter._token = "pre_cached_token"  # noqa: S105
    adapter._token_expires_at = time.time() + 3600
    client.post.side_effect = [bad_resp]
    with pytest.raises(OCRError, match="百度OCR响应非合法JSON格式"):
        adapter.recognize_image(b"bytes")

    # 3. 未知业务错误码 (例如 216100 非法参数)
    client.post.side_effect = [
        httpx.Response(
            status_code=200,
            json={"error_code": 216100, "error_msg": "Invalid param"},
        )
    ]
    with pytest.raises(OCRError, match="百度OCR服务异常 \\[216100\\]"):
        adapter.recognize_image(b"bytes")

    # 4. 底层通用网络异常重试耗尽
    client.post.side_effect = [
        RuntimeError("Connection broken"),
        RuntimeError("Connection broken"),
        RuntimeError("Connection broken"),
        RuntimeError("Connection broken"),
    ]
    adapter.max_retries = 3
    adapter.retry_delay_base = 0.001
    with pytest.raises(OCRError, match="百度OCR调用异常 \\(重试 3 次后失败\\)"):
        adapter.recognize_image(b"bytes")


def test_baidu_ocr_polygon_list_and_invalid_confidence() -> None:
    """测试多边形点序列格式与非数值型置信度解析防御。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    ocr_resp = httpx.Response(
        status_code=200,
        json={
            "words_result": [
                {
                    "words": "多点包围框文本",
                    "probability": "invalid_number_str",
                    "location": [{"x": 10, "y": 20}, {"x": 80, "y": 20}, {"x": 80, "y": 50}],
                },
            ],
        },
    )
    client = _build_mock_client_with_responses([token_resp, ocr_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    res = adapter.recognize_image(b"image_bytes")
    b = res.blocks[0]
    assert b.text == "多点包围框文本"
    assert b.confidence == 1.0  # 异常字符串回退为 1.0
    assert b.polygon is not None
    assert len(b.polygon.points) == 3
    assert b.polygon.points[0] == OCRPoint(10, 20)


def test_baidu_ocr_options_language_type_propagation() -> None:
    """测试 options.language_type 正确透传至识别请求表单。"""
    token_resp = httpx.Response(
        status_code=200,
        json={"access_token": "valid_token", "expires_in": 3600},
    )
    ocr_resp = httpx.Response(status_code=200, json={"words_result": []})
    client = _build_mock_client_with_responses([token_resp, ocr_resp, ocr_resp])
    adapter = BaiduOCRAdapter(api_key="key", secret_key="sec", client=client)  # noqa: S106

    options = OCROptions(language_type="ENG")
    adapter.recognize_image(b"image_data", options=options)
    call_image_data = client.post.call_args_list[1][1]["data"]
    assert call_image_data["language_type"] == "ENG"

    adapter.recognize_pdf_page(b"%PDF_data", page_number=1, options=options)
    call_pdf_data = client.post.call_args_list[2][1]["data"]
    assert call_pdf_data["language_type"] == "ENG"
