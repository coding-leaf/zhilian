"""VLMSettings / RerankSettings / EmbeddingSettings(siliconflow) 配置单元测试。

覆盖：默认值（默认关闭、provider=fake）、环境变量嵌套覆盖、边界校验、SecretStr 脱敏。
"""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import AppSettings, EmbeddingSettings, RerankSettings, VLMSettings


class TestVLMSettings:
    """VLM 脏页转录配置。"""

    def test_defaults_are_offline_safe(self) -> None:
        """默认关闭且 provider=fake，保证离线零联网。"""
        vlm = VLMSettings()

        assert vlm.enabled is False
        assert vlm.provider == "fake"
        assert vlm.model == "Qwen/Qwen2.5-VL-7B-Instruct"
        assert vlm.base_url is None
        assert vlm.api_key is None
        assert vlm.timeout == 45.0
        assert vlm.max_retries == 2
        assert vlm.dpi == 150
        assert vlm.max_concurrency == 3

    def test_app_settings_embeds_vlm_and_rerank(self) -> None:
        """AppSettings 暴露 vlm / rerank 子配置。"""
        settings = AppSettings()

        assert isinstance(settings.vlm, VLMSettings)
        assert isinstance(settings.rerank, RerankSettings)
        assert settings.vlm.enabled is False
        assert settings.rerank.enabled is False

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ZHILIAN_VLM__* 嵌套环境变量覆盖。"""
        monkeypatch.setenv("ZHILIAN_VLM__ENABLED", "true")
        monkeypatch.setenv("ZHILIAN_VLM__PROVIDER", "siliconflow")
        monkeypatch.setenv("ZHILIAN_VLM__MODEL", "Qwen/Qwen2.5-VL-32B-Instruct")
        monkeypatch.setenv("ZHILIAN_VLM__API_KEY", "sk-vlm-secret")
        monkeypatch.setenv("ZHILIAN_VLM__MAX_CONCURRENCY", "8")
        monkeypatch.setenv("ZHILIAN_VLM__DPI", "200")
        monkeypatch.setenv("ZHILIAN_VLM__TIMEOUT", "60.5")

        vlm = AppSettings().vlm

        assert vlm.enabled is True
        assert vlm.provider == "siliconflow"
        assert vlm.model == "Qwen/Qwen2.5-VL-32B-Instruct"
        assert isinstance(vlm.api_key, SecretStr)
        assert vlm.api_key.get_secret_value() == "sk-vlm-secret"
        assert vlm.max_concurrency == 8
        assert vlm.dpi == 200
        assert vlm.timeout == 60.5

    def test_api_key_is_masked(self) -> None:
        """api_key 不出现在 repr / str 中。"""
        vlm = VLMSettings(api_key=SecretStr("sk-never-leak"))

        assert "sk-never-leak" not in repr(vlm)
        assert "sk-never-leak" not in str(vlm)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("max_concurrency", 0),
            ("max_concurrency", 17),
            ("dpi", 71),
            ("dpi", 301),
        ],
    )
    def test_bounds_rejected(self, field: str, value: int) -> None:
        """并发与 DPI 越界被拒绝。"""
        with pytest.raises(ValidationError):
            VLMSettings(**{field: value})  # type: ignore[arg-type]

    @pytest.mark.parametrize(("field", "value"), [("max_concurrency", 1), ("max_concurrency", 16)])
    def test_bounds_accepted_at_edges(self, field: str, value: int) -> None:
        """边界值本身合法。"""
        assert getattr(VLMSettings(**{field: value}), field) == value  # type: ignore[arg-type]

    def test_unknown_provider_rejected(self) -> None:
        """未知 provider 被 Literal 拒绝。"""
        with pytest.raises(ValidationError):
            VLMSettings(provider="dashscope")  # type: ignore[arg-type]


class TestRerankSettings:
    """检索精排配置。"""

    def test_defaults(self) -> None:
        """默认值契约。"""
        rerank = RerankSettings()

        assert rerank.enabled is False
        assert rerank.provider == "fake"
        assert rerank.model == "BAAI/bge-reranker-v2-m3"
        assert rerank.base_url is None
        assert rerank.api_key is None
        assert rerank.timeout == 15.0
        assert rerank.max_retries == 2
        assert rerank.top_n == 6
        assert rerank.min_score == 0.25
        assert rerank.rewrite_threshold == 0.45

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ZHILIAN_RERANK__* 嵌套环境变量覆盖。"""
        monkeypatch.setenv("ZHILIAN_RERANK__ENABLED", "true")
        monkeypatch.setenv("ZHILIAN_RERANK__PROVIDER", "siliconflow")
        monkeypatch.setenv("ZHILIAN_RERANK__API_KEY", "sk-rerank-secret")
        monkeypatch.setenv("ZHILIAN_RERANK__TOP_N", "10")
        monkeypatch.setenv("ZHILIAN_RERANK__MIN_SCORE", "0.3")
        monkeypatch.setenv("ZHILIAN_RERANK__REWRITE_THRESHOLD", "0.6")

        rerank = AppSettings().rerank

        assert rerank.enabled is True
        assert rerank.provider == "siliconflow"
        assert rerank.api_key is not None
        assert rerank.api_key.get_secret_value() == "sk-rerank-secret"
        assert rerank.top_n == 10
        assert rerank.min_score == 0.3
        assert rerank.rewrite_threshold == 0.6

    def test_api_key_is_masked(self) -> None:
        """api_key 不出现在 repr 中。"""
        rerank = RerankSettings(api_key=SecretStr("sk-never-leak"))

        assert "sk-never-leak" not in repr(rerank)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("top_n", 0),
            ("min_score", -0.01),
            ("min_score", 1.01),
            ("rewrite_threshold", -0.01),
            ("rewrite_threshold", 1.01),
        ],
    )
    def test_bounds_rejected(self, field: str, value: float) -> None:
        """越界值被拒绝。"""
        with pytest.raises(ValidationError):
            RerankSettings(**{field: value})  # type: ignore[arg-type]

    def test_unknown_provider_rejected(self) -> None:
        """未知 provider 被拒绝。"""
        with pytest.raises(ValidationError):
            RerankSettings(provider="cohere")  # type: ignore[arg-type]


class TestEmbeddingSettingsSiliconFlow:
    """EmbeddingSettings 新增 siliconflow 取值。"""

    def test_accepts_siliconflow(self) -> None:
        """provider='siliconflow' 合法。"""
        assert EmbeddingSettings(provider="siliconflow").provider == "siliconflow"

    def test_env_siliconflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量可选择 siliconflow。"""
        monkeypatch.setenv("ZHILIAN_EMBEDDING__PROVIDER", "siliconflow")

        assert AppSettings().embedding.provider == "siliconflow"

    def test_existing_providers_still_accepted(self) -> None:
        """既有取值不回归。"""
        for provider in ("fake", "openai", "dashscope"):
            assert EmbeddingSettings(provider=provider).provider == provider

    def test_unknown_provider_rejected(self) -> None:
        """未知 provider 被拒绝。"""
        with pytest.raises(ValidationError):
            EmbeddingSettings(provider="cohere")  # type: ignore[arg-type]
