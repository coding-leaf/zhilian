"""OCR 适配器工厂模块。

严格遵循 AGENTS.md 规范：
- 根据配置参数分发并创建符合 OCRProtocol 契约的适配器实例；
- 单元测试与离线环境默认分发 FakeOCRAdapter 实现，具备零外部依赖特性；
- 生产环境支持创建 TencentOCRAdapter 与 BaiduOCRAdapter。
"""

from typing import Any

from app.core.errors import OCRError
from app.integrations.ocr.baidu import BaiduOCRAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.ocr.tencent import TencentOCRAdapter


def create_ocr_adapter(
    adapter_type: str = "fake",
    *,
    api_key: str | None = None,
    secret_id: str | None = None,
    secret_key: str | None = None,
    region: str = "ap-guangzhou",
    endpoint: str = "ocr.tencentcloudapi.com",
    timeout: float = 20.0,
    max_retries: int = 3,
    client: Any | None = None,
) -> OCRProtocol:
    """根据类型与配置创建 OCR 适配器实例。

    Args:
        adapter_type: 适配器类型 ("fake", "tencent" 或 "baidu")，默认 "fake"。
        api_key: 百度 API Key (Client ID) 或通用访问密钥。
        secret_id: 腾讯云 SecretId。
        secret_key: 密钥密文 (腾讯云 SecretKey 或百度 Secret Key)。
        region: 腾讯云地域标识，默认 "ap-guangzhou"。
        endpoint: API 接入点地址，默认 "ocr.tencentcloudapi.com"。
        timeout: 超时时间（秒），默认 20.0。
        max_retries: 最大重试次数，默认 3。
        client: 可选外部注入的底层客户端实例（供测试打桩）。

    Returns:
        OCRProtocol: 符合抽象协议的 OCR 适配器实例。

    Raises:
        OCRError: adapter_type 不支持或必要凭据缺失。
    """
    normalized_type = adapter_type.strip().lower()

    if normalized_type == "fake":
        return FakeOCRAdapter()

    if normalized_type == "tencent":
        effective_secret_id = secret_id or api_key
        if not effective_secret_id or not secret_key:
            raise OCRError(
                f"创建 {normalized_type} 适配器失败：secret_id 与 secret_key 均为必填配置参数"
            )
        return TencentOCRAdapter(
            secret_id=effective_secret_id,
            secret_key=secret_key,
            region=region,
            endpoint=endpoint,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )

    if normalized_type == "baidu":
        effective_api_key = api_key or secret_id
        if not effective_api_key or not secret_key:
            raise OCRError(
                f"创建 {normalized_type} 适配器失败："
                "api_key (或 secret_id) 与 secret_key 均为必填配置参数"
            )
        # 若未定制百度端点则使用官方默认接入点
        baidu_endpoint = (
            endpoint
            if endpoint
            not in (
                "ocr.tencentcloudapi.com",
                "https://ocr.tencentcloudapi.com",
            )
            else "https://aip.baidubce.com"
        )
        return BaiduOCRAdapter(
            api_key=effective_api_key,
            secret_key=secret_key,
            endpoint=baidu_endpoint,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )

    raise OCRError(f"不支持的 OCR 适配器类型: '{adapter_type}'，仅支持 'fake', 'tencent', 'baidu'")


__all__ = ["create_ocr_adapter"]
