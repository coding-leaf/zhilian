"""百度智能云 OCR (Baidu AI Cloud OCR) 识别适配器模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部供应商解耦；
- 依赖原生 httpx，零多余外部 SDK 依赖；
- 绝密脱敏防泄露：api_key 与 secret_key 严禁明文打印在 repr/str 与日志中；
- 内部缓存 Token (OAuth 2.0 client_credentials) 并按 expires_in 缓存复用；
- 指数退避重试（针对 QPS 限流与网络超时）；
- 异常分类转译为统一业务异常体系 (30004~30006, 30019)。
"""

import base64
import threading
import time
from typing import Any

import httpx

from app.core.errors import OCRAuthError, OCRError, OCRQuotaError, OCRTimeoutError
from app.integrations.ocr.protocol import (
    OCROptions,
    OCRPoint,
    OCRPolygon,
    OCRProtocol,
    OCRResult,
    OCRTextBlock,
)


class BaiduOCRAdapter(OCRProtocol):
    """百度智能云文字识别适配器。"""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        endpoint: str = "https://aip.baidubce.com",
        timeout: float = 20.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
        retry_delay_base: float = 0.5,
    ) -> None:
        """初始化百度 OCR 适配器。

        Args:
            api_key: 百度 API Key / Client ID。
            secret_key: 百度 Secret Key / Client Secret。
            endpoint: 百度 API 服务接入点，默认 "https://aip.baidubce.com"。
            timeout: 单次请求超时上限（秒），默认 20.0。
            max_retries: 偶发错误最大指数重试次数，默认 3。
            client: 可选外部注入的底层 HTTP 客户端（供测试打桩）。
            retry_delay_base: 重试基础退避时长（秒），默认 0.5。

        Raises:
            OCRError: 必要凭据缺失或配置参数非法。
        """
        if not api_key or not api_key.strip():
            raise OCRError("api_key 不能为空")
        if not secret_key or not secret_key.strip():
            raise OCRError("secret_key 不能为空")
        if timeout <= 0:
            raise OCRError("timeout 必须大于 0")
        if max_retries < 0:
            raise OCRError("max_retries 不能小于 0")

        self.api_key = api_key.strip()
        self.secret_key = secret_key.strip()

        endpoint_clean = endpoint.strip()
        if not endpoint_clean.startswith(("http://", "https://")):
            endpoint_clean = f"https://{endpoint_clean}"
        self.endpoint = endpoint_clean.rstrip("/")

        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base

        self._external_client = client is not None
        self._client = client if client is not None else httpx.Client(timeout=timeout)

        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = threading.Lock()

    def _fetch_token(self) -> str:
        """通过百度 OAuth 2.0 客户端凭据模式获取 access_token。

        Returns:
            str: 生效的 access_token 字符串。

        Raises:
            OCRAuthError: 凭据无效或鉴权被拒。
            OCRTimeoutError: 请求超时。
            OCRError: 获取令牌失败。
        """
        oauth_url = f"{self.endpoint}/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }

        try:
            resp = self._client.post(oauth_url, params=params)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise OCRTimeoutError(
                message=f"百度OCR获取Token超时: {exc!s}",
                details={"endpoint": self.endpoint},
            ) from exc
        except Exception as exc:
            raise OCRError(
                message=f"百度OCR获取Token连接异常: {exc!s}",
                details={"endpoint": self.endpoint},
            ) from exc

        if resp.status_code in (401, 403):
            raise OCRAuthError(
                message=f"百度OCR鉴权失败 (HTTP {resp.status_code}): {resp.text}",
                details={"status_code": resp.status_code},
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise OCRError(
                message=f"百度OCR Token响应格式异常: {resp.text}",
                details={"raw_text": resp.text},
            ) from exc

        if "error" in data or "error_code" in data:
            err_code = data.get("error_code")
            err_msg = (
                data.get("error_description") or data.get("error_msg") or str(data.get("error"))
            )
            if (
                err_code in (100, 110, 111)
                or "invalid_client" in str(data.get("error", "")).lower()
            ):
                raise OCRAuthError(
                    message=f"百度OCR鉴权凭据无效: {err_msg}",
                    details={"error_code": err_code, "raw": data},
                )
            if err_code == 17:
                raise OCRQuotaError(
                    message=f"百度OCR调用配额超限: {err_msg}",
                    details={"error_code": err_code, "raw": data},
                )
            raise OCRError(
                message=f"百度OCR获取Token失败: {err_msg}",
                details={"error_code": err_code, "raw": data},
            )

        access_token = data.get("access_token")
        if not access_token:
            raise OCRAuthError(
                message="百度OCR Token响应未包含 access_token",
                details={"raw": data},
            )

        expires_in = float(data.get("expires_in", 2592000.0))
        self._token = str(access_token)
        self._token_expires_at = time.time() + expires_in
        return self._token

    def _get_token(self) -> str:
        """获取已缓存的有效 access_token，若已失效则自动刷新。"""
        with self._token_lock:
            now = time.time()
            if self._token is not None and now < self._token_expires_at - 60.0:
                return self._token
            return self._fetch_token()

    def _resolve_url(self, options: OCROptions | None) -> str:
        """根据识别选项与端点配置解析具体 API 请求 URL。"""
        if "/rest/2.0/" in self.endpoint:
            return self.endpoint

        need_location = options.need_location if options is not None else True
        if need_location:
            return f"{self.endpoint}/rest/2.0/ocr/v1/accurate"
        return f"{self.endpoint}/rest/2.0/ocr/v1/accurate_basic"

    def _execute_with_retry(
        self,
        url: str,
        data: dict[str, Any],
    ) -> OCRResult:
        """执行 OCR 识别请求，具备自动 Token 注入、指数退避重试与异常分类转译能力。"""
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            token = self._get_token()
            params = {"access_token": token}
            try:
                start_time = time.perf_counter()
                resp = self._client.post(
                    url,
                    params=params,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0

                if resp.status_code in (401, 403):
                    with self._token_lock:
                        self._token = None
                        self._token_expires_at = 0.0
                    raise OCRAuthError(
                        message=f"百度OCR认证失败 (HTTP {resp.status_code}): {resp.text}",
                        details={"status_code": resp.status_code},
                    )

                try:
                    resp_json = resp.json()
                except Exception as exc:
                    raise OCRError(
                        message=f"百度OCR响应非合法JSON格式: {resp.text}",
                        details={"raw_text": resp.text},
                    ) from exc

                if "error_code" in resp_json:
                    error_code = int(resp_json["error_code"])
                    error_msg = str(resp_json.get("error_msg", ""))

                    if error_code in (110, 111):
                        with self._token_lock:
                            self._token = None
                            self._token_expires_at = 0.0
                        raise OCRAuthError(
                            message=f"百度OCR访问令牌失效或过期 [{error_code}]: {error_msg}",
                            details={"error_code": error_code, "error_msg": error_msg},
                        )

                    if error_code == 100:
                        raise OCRAuthError(
                            message=f"百度OCR鉴权凭证或参数错误 [{error_code}]: {error_msg}",
                            details={"error_code": error_code, "error_msg": error_msg},
                        )

                    if error_code == 17:
                        raise OCRQuotaError(
                            message=f"百度OCR当日调用量配额超限 [{error_code}]: {error_msg}",
                            details={"error_code": error_code, "error_msg": error_msg},
                        )

                    if error_code == 18:
                        if attempt < self.max_retries:
                            sleep_duration = self.retry_delay_base * (2**attempt)
                            if sleep_duration > 0:
                                time.sleep(sleep_duration)
                            continue
                        raise OCRQuotaError(
                            message=(
                                f"百度OCR并发频次过高 (重试 {self.max_retries} 次后超限)"
                                f" [{error_code}]: {error_msg}"
                            ),
                            details={"error_code": error_code, "retries": self.max_retries},
                        )

                    raise OCRError(
                        message=f"百度OCR服务异常 [{error_code}]: {error_msg}",
                        details={"error_code": error_code, "error_msg": error_msg},
                    )

                return self._parse_response(resp_json, duration_ms)

            except (OCRAuthError, OCRQuotaError, OCRError):
                raise
            except (httpx.TimeoutException, TimeoutError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                sleep_duration = self.retry_delay_base * (2**attempt)
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                sleep_duration = self.retry_delay_base * (2**attempt)
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

        if last_exc is None:
            raise OCRError("百度OCR未执行有效请求")

        if isinstance(last_exc, (httpx.TimeoutException, TimeoutError)):
            raise OCRTimeoutError(
                message=f"百度OCR服务响应超时 (重试 {self.max_retries} 次后失败): {last_exc!s}",
                details={"retries": self.max_retries},
            ) from last_exc

        raise OCRError(
            message=f"百度OCR调用异常 (重试 {self.max_retries} 次后失败): {last_exc!s}",
            details={"retries": self.max_retries},
        ) from last_exc

    @staticmethod
    def _parse_response(response: dict[str, Any], duration_ms: float) -> OCRResult:
        """解析百度 OCR 返回的 JSON 字典为标准强类型 OCRResult 模型。"""
        words_result = response.get("words_result") or []
        blocks: list[OCRTextBlock] = []
        full_text_lines: list[str] = []

        for index, item in enumerate(words_result, start=1):
            detected_text = str(item.get("words", ""))

            prob = item.get("probability")
            if isinstance(prob, dict):
                raw_conf = prob.get("average", 1.0)
            elif prob is not None:
                raw_conf = prob
            else:
                raw_conf = 1.0

            try:
                confidence = float(raw_conf)
            except (ValueError, TypeError):
                confidence = 1.0

            confidence = round(confidence / 100.0, 4) if confidence > 1.0 else round(confidence, 4)

            polygon: OCRPolygon | None = None
            raw_location = item.get("location")
            if isinstance(raw_location, dict):
                left = int(raw_location.get("left", 0))
                top = int(raw_location.get("top", 0))
                width = int(raw_location.get("width", 0))
                height = int(raw_location.get("height", 0))
                polygon = OCRPolygon.from_coordinates(
                    [
                        (left, top),
                        (left + width, top),
                        (left + width, top + height),
                        (left, top + height),
                    ]
                )
            elif isinstance(raw_location, list):
                points = tuple(
                    OCRPoint(x=int(p.get("x", 0)), y=int(p.get("y", 0)))
                    for p in raw_location
                    if isinstance(p, dict)
                )
                if points:
                    polygon = OCRPolygon(points=points)

            blocks.append(
                OCRTextBlock(
                    text=detected_text,
                    confidence=confidence,
                    polygon=polygon,
                    line_number=index,
                )
            )
            full_text_lines.append(detected_text)

        image_width = response.get("image_width") or response.get("width")
        image_height = response.get("image_height") or response.get("height")

        return OCRResult(
            full_text="\n".join(full_text_lines),
            blocks=tuple(blocks),
            duration_ms=round(duration_ms, 2),
            image_width=int(image_width) if image_width is not None else None,
            image_height=int(image_height) if image_height is not None else None,
            provider="baidu",
            raw_payload=response,
        )

    def recognize_image(
        self,
        image_bytes: bytes,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """识别上传的本地/内存图片二进制字节数据。"""
        if not image_bytes:
            raise OCRError("待识别图片二进制数据不能为空")

        b64_image = base64.b64encode(image_bytes).decode("ascii")
        data: dict[str, Any] = {
            "image": b64_image,
            "probability": "true",
        }
        if options and options.language_type:
            data["language_type"] = options.language_type

        url = self._resolve_url(options)
        return self._execute_with_retry(url, data)

    def recognize_url(
        self,
        image_url: str,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """通过图片公网或预签名 URL 进行识别。"""
        if not image_url or not image_url.strip():
            raise OCRError("待识别图片网络地址不能为空")

        data: dict[str, Any] = {
            "url": image_url.strip(),
            "probability": "true",
        }
        if options and options.language_type:
            data["language_type"] = options.language_type

        url = self._resolve_url(options)
        return self._execute_with_retry(url, data)

    def recognize_pdf_page(
        self,
        pdf_bytes: bytes,
        page_number: int = 1,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """识别 PDF 文档的指定单页内容。"""
        if not pdf_bytes:
            raise OCRError("待识别PDF二进制数据不能为空")
        if page_number < 1:
            raise OCRError("page_number 必须大于或等于 1")

        b64_pdf = base64.b64encode(pdf_bytes).decode("ascii")
        data: dict[str, Any] = {
            "pdf_file": b64_pdf,
            "pdf_file_num": str(page_number),
            "probability": "true",
        }
        if options and options.language_type:
            data["language_type"] = options.language_type

        url = self._resolve_url(options)
        return self._execute_with_retry(url, data)

    def close(self) -> None:
        """释放底层 HTTP 客户端连接。"""
        if not self._external_client:
            self._client.close()

    def __repr__(self) -> str:
        """绝密脱敏字符串表示，掩码 secret_key 与 api_key 部分信息。"""
        masked_api_key = f"{self.api_key[:4]}****" if len(self.api_key) > 4 else "****"
        return (
            f"BaiduOCRAdapter(api_key='{masked_api_key}', secret_key='******', "
            f"endpoint='{self.endpoint}', timeout={self.timeout})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["BaiduOCRAdapter"]
