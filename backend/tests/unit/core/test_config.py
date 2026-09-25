"""Unit tests for the strong-typed application configuration module.

Validates default loading, environment prefix / nested delimiter parsing,
SecretStr credential masking, enum validation constraints, and singleton caching.
"""

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import (
    AppSettings,
    DatabaseSettings,
    EmbeddingSettings,
    IdempotencySettings,
    LLMSettings,
    OCRSettings,
    QueueSettings,
    RedisSettings,
    SearchSettings,
    StorageSettings,
    get_settings,
)


class TestAppSettingsDefaults:
    """Test suite for default configuration loading."""

    def test_default_app_settings(self) -> None:
        """Verify default AppSettings hierarchy and fallback values."""
        settings = AppSettings()

        assert settings.env == "development"
        assert settings.debug is False
        assert isinstance(settings.secret_key, SecretStr)
        assert len(settings.secret_key.get_secret_value()) >= 32

        # Sub-settings instances
        assert isinstance(settings.db, DatabaseSettings)
        assert isinstance(settings.redis, RedisSettings)
        assert isinstance(settings.storage, StorageSettings)
        assert isinstance(settings.llm, LLMSettings)
        assert isinstance(settings.ocr, OCRSettings)
        assert isinstance(settings.embedding, EmbeddingSettings)
        assert isinstance(settings.queue, QueueSettings)
        assert isinstance(settings.idempotency, IdempotencySettings)
        assert isinstance(settings.search, SearchSettings)

    def test_default_sub_settings_values(self) -> None:
        """Verify default field values across all sub-settings."""
        db = DatabaseSettings()
        assert db.db_url == "sqlite:///./zhilian_dev.db"
        assert db.echo is False
        assert db.pool_size == 10
        assert db.max_overflow == 20
        assert db.pool_timeout == 30.0
        assert db.pool_pre_ping is True

        redis = RedisSettings()
        assert redis.redis_url == "redis://localhost:6379/0"
        assert redis.max_connections == 10
        assert redis.timeout == 5.0

        storage = StorageSettings()
        assert storage.provider == "memory"
        assert storage.bucket_name == "zhilian-materials"
        assert storage.endpoint_url is None
        assert storage.access_key is None
        assert storage.secret_key is None
        assert storage.region == "us-east-1"
        assert storage.use_ssl is False
        assert storage.secure is False

        llm = LLMSettings()
        assert llm.provider == "fake"
        assert llm.model == "qwen-max"
        assert llm.base_url is None
        assert llm.api_key is None
        assert llm.timeout == 30.0
        assert llm.max_retries == 3

        ocr = OCRSettings()
        assert ocr.provider == "fake"
        assert ocr.secret_id is None
        assert ocr.secret_key is None
        assert ocr.region == "ap-guangzhou"
        assert ocr.endpoint == "ocr.tencentcloudapi.com"
        assert ocr.timeout == 20.0
        assert ocr.max_retries == 3

        embedding = EmbeddingSettings()
        assert embedding.provider == "fake"
        assert embedding.model == "text-embedding-v3"
        assert embedding.dimension == 1024
        assert embedding.dimensions == 1024
        assert embedding.batch_size == 16
        assert embedding.api_key is None
        assert embedding.base_url is None
        assert embedding.timeout == 20.0
        assert embedding.max_retries == 3

        queue = QueueSettings()
        assert queue.provider == "memory"
        assert queue.dead_letter_topic == "zhilian_dead_letter"
        assert queue.retry_limit == 3
        assert queue.immediate_mode is False

        idempotency = IdempotencySettings()
        assert idempotency.provider == "memory"
        assert idempotency.default_ttl_seconds == 300

        search = SearchSettings()
        assert search.provider == "fake"
        assert search.vector_dimension == 1024
        assert search.distance_strategy == "cosine"


class TestAppSettingsEnvironmentOverride:
    """Test suite for environment variable prefix and nested delimiter overrides."""

    def test_environment_variable_nested_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify ZHILIAN_ prefix and __ delimiter nested field overrides."""
        env_vars: dict[str, str] = {
            "ZHILIAN_ENV": "production",
            "ZHILIAN_DEBUG": "true",
            "ZHILIAN_SECRET_KEY": "production-super-secret-key-at-least-32-chars!",
            "ZHILIAN_DB__DB_URL": "postgresql+psycopg://user:pass@localhost:5432/zhilian_db",
            "ZHILIAN_DB__POOL_SIZE": "25",
            "ZHILIAN_DB__ECHO": "true",
            "ZHILIAN_REDIS__REDIS_URL": "redis://:pwd@redis.internal:6379/2",
            "ZHILIAN_REDIS__MAX_CONNECTIONS": "50",
            "ZHILIAN_STORAGE__PROVIDER": "minio",
            "ZHILIAN_STORAGE__BUCKET_NAME": "custom-materials",
            "ZHILIAN_STORAGE__ENDPOINT_URL": "http://minio:9000",
            "ZHILIAN_STORAGE__ACCESS_KEY": "custom_access_key",
            "ZHILIAN_STORAGE__SECRET_KEY": "custom_secret_key",
            "ZHILIAN_STORAGE__USE_SSL": "true",
            "ZHILIAN_LLM__PROVIDER": "deepseek",
            "ZHILIAN_LLM__MODEL": "deepseek-chat",
            "ZHILIAN_LLM__API_KEY": "sk-deepseek-test-key",
            "ZHILIAN_LLM__TIMEOUT": "45.5",
            "ZHILIAN_OCR__PROVIDER": "tencent",
            "ZHILIAN_OCR__SECRET_ID": "tencent_secret_id_123",
            "ZHILIAN_OCR__SECRET_KEY": "tencent_secret_key_456",
            "ZHILIAN_EMBEDDING__PROVIDER": "openai",
            "ZHILIAN_EMBEDDING__MODEL": "text-embedding-3-small",
            "ZHILIAN_EMBEDDING__DIMENSION": "1536",
            "ZHILIAN_EMBEDDING__BATCH_SIZE": "32",
            "ZHILIAN_QUEUE__PROVIDER": "redis",
            "ZHILIAN_QUEUE__DEAD_LETTER_TOPIC": "custom_dead_letter",
            "ZHILIAN_QUEUE__RETRY_LIMIT": "5",
            "ZHILIAN_IDEMPOTENCY__PROVIDER": "redis",
            "ZHILIAN_IDEMPOTENCY__DEFAULT_TTL_SECONDS": "600",
            "ZHILIAN_SEARCH__PROVIDER": "pgvector",
            "ZHILIAN_SEARCH__VECTOR_DIMENSION": "1536",
            "ZHILIAN_SEARCH__DISTANCE_STRATEGY": "inner_product",
        }

        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)

        settings = AppSettings()

        assert settings.env == "production"
        assert settings.debug is True
        assert (
            settings.secret_key.get_secret_value()
            == "production-super-secret-key-at-least-32-chars!"
        )

        assert settings.db.db_url == "postgresql+psycopg://user:pass@localhost:5432/zhilian_db"
        assert settings.db.pool_size == 25
        assert settings.db.echo is True

        assert settings.redis.redis_url == "redis://:pwd@redis.internal:6379/2"
        assert settings.redis.max_connections == 50

        assert settings.storage.provider == "minio"
        assert settings.storage.bucket_name == "custom-materials"
        assert settings.storage.endpoint_url == "http://minio:9000"
        assert settings.storage.access_key is not None
        assert settings.storage.access_key.get_secret_value() == "custom_access_key"
        assert settings.storage.secret_key is not None
        assert settings.storage.secret_key.get_secret_value() == "custom_secret_key"
        assert settings.storage.use_ssl is True
        assert settings.storage.secure is True

        assert settings.llm.provider == "deepseek"
        assert settings.llm.model == "deepseek-chat"
        assert settings.llm.api_key is not None
        assert settings.llm.api_key.get_secret_value() == "sk-deepseek-test-key"
        assert settings.llm.timeout == 45.5

        assert settings.ocr.provider == "tencent"
        assert settings.ocr.secret_id is not None
        assert settings.ocr.secret_id.get_secret_value() == "tencent_secret_id_123"
        assert settings.ocr.secret_key is not None
        assert settings.ocr.secret_key.get_secret_value() == "tencent_secret_key_456"

        assert settings.embedding.provider == "openai"
        assert settings.embedding.model == "text-embedding-3-small"
        assert settings.embedding.dimension == 1536
        assert settings.embedding.dimensions == 1536
        assert settings.embedding.batch_size == 32

        assert settings.queue.provider == "redis"
        assert settings.queue.dead_letter_topic == "custom_dead_letter"
        assert settings.queue.retry_limit == 5

        assert settings.idempotency.provider == "redis"
        assert settings.idempotency.default_ttl_seconds == 600

        assert settings.search.provider == "pgvector"
        assert settings.search.vector_dimension == 1536
        assert settings.search.distance_strategy == "inner_product"


class TestSecretStrMasking:
    """Test suite for credential masking and SecretStr leak prevention."""

    def test_secret_str_masking_does_not_leak_plaintext(self) -> None:
        """Verify str() and repr() do not leak secret values in plain text."""
        raw_sample_key = "sensitive-api-token-998877"
        settings = AppSettings(
            secret_key=SecretStr(raw_sample_key),
            storage=StorageSettings(
                access_key=SecretStr(raw_sample_key),
                secret_key=SecretStr(raw_sample_key),
            ),
            llm=LLMSettings(api_key=SecretStr(raw_sample_key)),
            ocr=OCRSettings(
                secret_id=SecretStr(raw_sample_key),
                secret_key=SecretStr(raw_sample_key),
            ),
            embedding=EmbeddingSettings(api_key=SecretStr(raw_sample_key)),
        )

        secrets_to_check: list[SecretStr | None] = [
            settings.secret_key,
            settings.storage.access_key,
            settings.storage.secret_key,
            settings.llm.api_key,
            settings.ocr.secret_id,
            settings.ocr.secret_key,
            settings.embedding.api_key,
        ]

        for sec in secrets_to_check:
            assert sec is not None
            str_repr = str(sec)
            repr_str = repr(sec)
            assert raw_sample_key not in str_repr
            assert raw_sample_key not in repr_str
            assert "**********" in str_repr or "**********" in repr_str
            assert sec.get_secret_value() == raw_sample_key


class TestValidationConstraints:
    """Test suite for enum, boundary, and format validation failure modes."""

    @pytest.mark.parametrize(
        "invalid_field,invalid_value",
        [
            ("env", "staging"),
            ("env", "local"),
        ],
    )
    def test_invalid_app_env_rejected(self, invalid_field: str, invalid_value: Any) -> None:
        """Verify invalid environment string raises ValidationError."""
        with pytest.raises(ValidationError):
            AppSettings(**{invalid_field: invalid_value})

    def test_invalid_storage_provider_rejected(self) -> None:
        """Verify unsupported storage provider raises ValidationError."""
        with pytest.raises(ValidationError):
            StorageSettings(provider="aliyun_oss")  # type: ignore[arg-type]

    def test_invalid_llm_provider_rejected(self) -> None:
        """Verify unsupported LLM provider raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMSettings(provider="anthropic")  # type: ignore[arg-type]

    def test_invalid_ocr_provider_rejected(self) -> None:
        """Verify unsupported OCR provider raises ValidationError."""
        with pytest.raises(ValidationError):
            OCRSettings(provider="aliyun")  # type: ignore[arg-type]

    def test_valid_ocr_provider_baidu_and_normalization(self) -> None:
        """Verify baidu provider is accepted and endpoint normalization works."""
        ocr_baidu = OCRSettings(
            provider="baidu",
            api_key=SecretStr("baidu_key_123"),
            secret_key=SecretStr("baidu_secret_456"),
            endpoint="aip.baidubce.com",
        )
        assert ocr_baidu.provider == "baidu"
        assert ocr_baidu.endpoint == "https://aip.baidubce.com"
        assert ocr_baidu.effective_api_key is not None
        assert ocr_baidu.effective_api_key.get_secret_value() == "baidu_key_123"
        assert ocr_baidu.secret_id is not None
        assert ocr_baidu.secret_id.get_secret_value() == "baidu_key_123"

        # Compatibility when only secret_id is passed
        ocr_compat = OCRSettings(
            provider="baidu",
            secret_id=SecretStr("compat_id"),
        )
        assert ocr_compat.api_key is not None
        assert ocr_compat.api_key.get_secret_value() == "compat_id"
        assert ocr_compat.effective_api_key is not None
        assert ocr_compat.effective_api_key.get_secret_value() == "compat_id"

    def test_invalid_embedding_provider_rejected(self) -> None:
        """Verify unsupported embedding provider raises ValidationError."""
        with pytest.raises(ValidationError):
            EmbeddingSettings(provider="cohere")  # type: ignore[arg-type]

    def test_invalid_queue_provider_rejected(self) -> None:
        """Verify unsupported queue provider raises ValidationError."""
        with pytest.raises(ValidationError):
            QueueSettings(provider="rabbitmq")  # type: ignore[arg-type]

    def test_invalid_search_distance_strategy_rejected(self) -> None:
        """Verify unsupported search distance strategy raises ValidationError."""
        with pytest.raises(ValidationError):
            SearchSettings(distance_strategy="manhattan")  # type: ignore[arg-type]

    def test_invalid_integer_field_rejected(self) -> None:
        """Verify invalid int field type raises ValidationError."""
        with pytest.raises(ValidationError):
            DatabaseSettings(pool_size="not_a_valid_number")  # type: ignore[arg-type]


class TestSingletonGetSettings:
    """Test suite for get_settings() singleton factory and cache behavior."""

    def test_get_settings_caching_and_clear(self) -> None:
        """Verify get_settings returns singleton instance and cache_clear refreshes it."""
        get_settings.cache_clear()
        settings_1 = get_settings()
        settings_2 = get_settings()
        assert settings_1 is settings_2

        get_settings.cache_clear()
        settings_3 = get_settings()
        assert settings_3 is not settings_1
