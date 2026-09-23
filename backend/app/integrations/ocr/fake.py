"""OCR 识别适配器纯内存假实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与离线环境设计，零外部套接字连接；
- 内部基于 threading.Lock 保障多线程并发安全；
- 支持开箱即用确定性解析、预置匹配、故障注入与延迟模拟；
- 绝密脱敏防泄露。
"""

import hashlib
import threading
import time

from app.core.errors import OCRError
from app.integrations.ocr.protocol import (
    OCROptions,
    OCRPoint,
    OCRPolygon,
    OCRProtocol,
    OCRResult,
    OCRTextBlock,
)


class FakeOCRAdapter(OCRProtocol):
    """纯内存假 OCR 适配器实现。

    提供确定性返回、预置结果映射、时延模拟与异常注入能力。
    """

    def __init__(self, default_result: OCRResult | None = None) -> None:
        """初始化内存假适配器。

        Args:
            default_result: 可选的全局保底确定性返回结果。
        """
        self._lock = threading.Lock()
        self._canned_results: dict[str, OCRResult] = {}
        self._fault_injections: dict[str, Exception] = {}
        self._latency_seconds: float = 0.0
        self._default_result = default_result or self._build_default_result()

    @staticmethod
    def _build_default_result() -> OCRResult:
        """构造开箱即用的默认确定性 OCR 结果。"""
        blocks = (
            OCRTextBlock(
                text="智练自主学习系统智能OCR文字识别结果",
                confidence=0.99,
                polygon=OCRPolygon(
                    points=(
                        OCRPoint(x=10, y=10),
                        OCRPoint(x=400, y=10),
                        OCRPoint(x=400, y=40),
                        OCRPoint(x=10, y=40),
                    )
                ),
                line_number=1,
            ),
            OCRTextBlock(
                text="第一章 绪论与系统架构设计",
                confidence=0.98,
                polygon=OCRPolygon(
                    points=(
                        OCRPoint(x=10, y=50),
                        OCRPoint(x=300, y=50),
                        OCRPoint(x=300, y=80),
                        OCRPoint(x=10, y=80),
                    )
                ),
                line_number=2,
            ),
            OCRTextBlock(
                text="1.1 核心算法与高可用基础设施",
                confidence=0.97,
                polygon=OCRPolygon(
                    points=(
                        OCRPoint(x=10, y=90),
                        OCRPoint(x=350, y=90),
                        OCRPoint(x=350, y=120),
                        OCRPoint(x=10, y=120),
                    )
                ),
                line_number=3,
            ),
        )
        full_text = "\n".join(b.text for b in blocks)
        return OCRResult(
            full_text=full_text,
            blocks=blocks,
            duration_ms=5.0,
            image_width=800,
            image_height=600,
            provider="fake",
            raw_payload={"status": "OK", "block_count": len(blocks)},
        )

    def set_canned_result(self, key: str | bytes, result: OCRResult) -> None:
        """注册针对特定图片内容（摘要）或网络 URL 的预置识别结果。

        Args:
            key: 图片完整字节流、哈希摘要字符串或 URL 字符串。
            result: 期望返回的 OCRResult 对象。
        """
        with self._lock:
            if isinstance(key, bytes):
                digest = hashlib.sha256(key).hexdigest()
                self._canned_results[digest] = result
                try:
                    text_key = key.decode("utf-8")
                    self._canned_results[text_key] = result
                except UnicodeDecodeError:
                    pass
            else:
                self._canned_results[key] = result

    def inject_failure(self, method_name: str, exception: Exception) -> None:
        """注入指定方法的模拟异常故障。

        Args:
            method_name: 待注入异常的方法名（如 'recognize_image', 'recognize_url' 或 '*'）。
            exception: 调取时抛出的异常实例。
        """
        with self._lock:
            self._fault_injections[method_name] = exception

    def inject_latency(self, seconds: float) -> None:
        """设置模拟网络调用的延迟时间。

        Args:
            seconds: 延迟时长（秒）。
        """
        with self._lock:
            self._latency_seconds = max(0.0, seconds)

    def clear(self) -> None:
        """清空所有预置结果、故障注入与延迟配置。"""
        with self._lock:
            self._canned_results.clear()
            self._fault_injections.clear()
            self._latency_seconds = 0.0

    def _check_fault_and_latency(self, method_name: str) -> None:
        """并发安全检查故障注入与延迟。"""
        with self._lock:
            if "*" in self._fault_injections:
                raise self._fault_injections["*"]
            if method_name in self._fault_injections:
                raise self._fault_injections[method_name]
            latency = self._latency_seconds

        if latency > 0.0:
            time.sleep(latency)

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
            OCRError: 图片内容为空或注入的异常。
        """
        if not image_bytes:
            raise OCRError("待识别图片二进制数据不能为空")

        start_time = time.perf_counter()
        self._check_fault_and_latency("recognize_image")

        digest = hashlib.sha256(image_bytes).hexdigest()
        with self._lock:
            if digest in self._canned_results:
                return self._canned_results[digest]
            try:
                decoded_key = image_bytes.decode("utf-8")
                if decoded_key in self._canned_results:
                    return self._canned_results[decoded_key]
            except UnicodeDecodeError:
                pass
            fallback = self._default_result

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return OCRResult(
            full_text=fallback.full_text,
            blocks=fallback.blocks,
            duration_ms=round(elapsed_ms, 2),
            image_width=fallback.image_width,
            image_height=fallback.image_height,
            provider=fallback.provider,
            raw_payload=fallback.raw_payload,
        )

    def recognize_url(
        self,
        image_url: str,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """通过图片网络 URL 进行识别。

        Args:
            image_url: 可访问的图片资源网络链接。
            options: 可选的识别配置选项。

        Returns:
            OCRResult: 结构化解析结果对象。

        Raises:
            OCRError: 图片网络链接为空或注入的异常。
        """
        if not image_url or not image_url.strip():
            raise OCRError("待识别图片网络地址不能为空")

        start_time = time.perf_counter()
        self._check_fault_and_latency("recognize_url")

        with self._lock:
            if image_url in self._canned_results:
                return self._canned_results[image_url]
            fallback = self._default_result

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return OCRResult(
            full_text=fallback.full_text,
            blocks=fallback.blocks,
            duration_ms=round(elapsed_ms, 2),
            image_width=fallback.image_width,
            image_height=fallback.image_height,
            provider=fallback.provider,
            raw_payload=fallback.raw_payload,
        )

    def __repr__(self) -> str:
        """脱敏字符串表示。"""
        with self._lock:
            return (
                f"FakeOCRAdapter(canned_count={len(self._canned_results)}, "
                f"fault_count={len(self._fault_injections)}, "
                f"latency_seconds={self._latency_seconds})"
            )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["FakeOCRAdapter"]
