"""智练自主学习平台强类型配置中心。

基于 pydantic-settings 实现全局与子域强类型配置管理。
统一使用 ZHILIAN_ 环境变量前缀与双下划线 __ 嵌套字段反序列化解析。
所有敏感凭证（密码、密钥、Token）统一使用 SecretStr 脱敏防护。
"""

import logging
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 依据：系统安全基线要求，生产环境强制由 ZHILIAN_SECRET_KEY 注入；非生产环境提供开发测试保底密钥。
# 该常量同时作为「开发默认密钥」的唯一判定源，任何生产环境检测到仍在使用时必须启动期 fail-fast。
DEVELOPMENT_SECRET_KEY: str = "zhilian-development-secret-key-32bytes-min!"  # noqa: S105


class DatabaseSettings(BaseSettings):
    """关系型数据库连接与连接池配置。

    Attributes:
        db_url: 数据库连接 URI。
        echo: 是否打印 SQLAlchemy 原始 SQL 日志。
        pool_size: 连接池常驻连接数。
        max_overflow: 连接池最大突发溢出连接数。
        pool_timeout: 连接池获取连接的超时时间（秒）。
        pool_pre_ping: 连接借出前是否执行连通性检测。
    """

    db_url: str = Field(
        default="sqlite:///./zhilian_dev.db",
        description="数据库连接 URI",
    )
    echo: bool = Field(
        default=False,
        description="是否打印 SQLAlchemy 原始 SQL 日志",
    )
    pool_size: int = Field(
        default=10,
        description="连接池常驻连接数",
    )
    max_overflow: int = Field(
        default=20,
        description="连接池最大突发溢出连接数",
    )
    pool_timeout: float = Field(
        default=30.0,
        description="连接池获取连接的超时时间（秒）",
    )
    pool_pre_ping: bool = Field(
        default=True,
        description="连接借出前是否执行连通性检测",
    )


class RedisSettings(BaseSettings):
    """Redis 缓存与消息队列连接配置。

    Attributes:
        redis_url: Redis 连接 URI。
        max_connections: 连接池最大连接数。
        timeout: 连接与命令读写超时时间（秒）。
    """

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接 URI",
    )
    max_connections: int = Field(
        default=10,
        description="连接池最大连接数",
    )
    timeout: float = Field(
        default=5.0,
        description="连接与命令读写超时时间（秒）",
    )


class StorageSettings(BaseSettings):
    """对象存储适配器配置。

    Attributes:
        provider: 存储提供商类型。
        bucket_name: 资料默认存储桶名称。
        endpoint_url: S3 或 MinIO 端点 URL。
        access_key: 访问密钥标识。
        secret_key: 访问密钥密文。
        region: 存储地域。
        use_ssl: 是否启用 HTTPS 安全连接。
    """

    provider: Literal["memory", "s3", "minio"] = Field(
        default="memory",
        description="存储提供商类型",
    )
    bucket_name: str = Field(
        default="zhilian-materials",
        description="资料默认存储桶名称",
    )
    endpoint_url: str | None = Field(
        default=None,
        description="S3 或 MinIO 端点 URL",
    )
    access_key: SecretStr | None = Field(
        default=None,
        description="访问密钥标识",
    )
    secret_key: SecretStr | None = Field(
        default=None,
        description="访问密钥密文",
    )
    region: str = Field(
        default="us-east-1",
        description="存储地域",
    )
    use_ssl: bool = Field(
        default=False,
        description="是否启用 HTTPS 安全连接",
    )

    @property
    def secure(self) -> bool:
        """兼容 secure 命名属性。

        Returns:
            bool: 是否启用安全连接。
        """
        return self.use_ssl


class SearchSettings(BaseSettings):
    """混合检索与向量检索适配器配置。

    Attributes:
        provider: 检索后端提供商。
        vector_dimension: 向量维度大小。
        distance_strategy: 距离度量策略。
    """

    provider: Literal["fake", "pgvector"] = Field(
        default="fake",
        description="检索后端提供商",
    )
    vector_dimension: int = Field(
        default=1024,
        description="向量维度大小",
    )
    distance_strategy: Literal["cosine", "l2", "inner_product"] = Field(
        default="cosine",
        description="距离度量策略",
    )


class QueueSettings(BaseSettings):
    """异步任务队列配置。

    Attributes:
        provider: 任务队列提供商。
        dead_letter_topic: 死信队列主题标识。
        retry_limit: 任务失败最大重试次数。
        immediate_mode: 是否同步立即执行。
    """

    provider: Literal["memory", "redis"] = Field(
        default="memory",
        description="任务队列提供商",
    )
    dead_letter_topic: str = Field(
        default="zhilian_dead_letter",
        description="死信队列主题标识",
    )
    retry_limit: int = Field(
        default=3,
        description="任务失败最大重试次数",
    )
    immediate_mode: bool = Field(
        default=False,
        description="是否同步立即执行",
    )


class IdempotencySettings(BaseSettings):
    """分布式幂等拦截器配置。

    Attributes:
        provider: 幂等存储提供商。
        default_ttl_seconds: 幂等记录默认过期时间（秒）。
    """

    provider: Literal["memory", "redis"] = Field(
        default="memory",
        description="幂等存储提供商",
    )
    default_ttl_seconds: int = Field(
        default=300,
        description="幂等记录默认过期时间（秒）",
    )


class EmbeddingSettings(BaseSettings):
    """文本向量化模型配置。

    Attributes:
        provider: 向量化服务提供商。
        model: 向量化模型名称。
        dimension: 向量维度大小。
        batch_size: 批量向量化大小。
        api_key: 向量化接口 API Key。
        base_url: 向量化服务基础 URL。
        timeout: 请求超时上限（秒）。
        max_retries: 失败最大重试次数。
    """

    provider: Literal["fake", "openai", "dashscope"] = Field(
        default="fake",
        description="向量化服务提供商",
    )
    model: str = Field(
        default="text-embedding-v3",
        description="向量化模型名称",
    )
    dimension: int = Field(
        default=1024,
        description="向量维度大小",
    )
    batch_size: int = Field(
        default=16,
        description="批量向量化大小",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="向量化接口 API Key",
    )
    base_url: str | None = Field(
        default=None,
        description="向量化服务基础 URL",
    )
    timeout: float = Field(
        default=20.0,
        description="请求超时上限（秒）",
    )
    max_retries: int = Field(
        default=3,
        description="失败最大重试次数",
    )

    @property
    def dimensions(self) -> int:
        """兼容复数形式 dimensions 命名。

        Returns:
            int: 向量维度大小。
        """
        return self.dimension


class LLMSettings(BaseSettings):
    """大语言模型（LLM）配置。

    Attributes:
        provider: LLM 适配提供商。
        model: 模型名称。
        base_url: 服务端点基础 URL。
        api_key: 访问凭证 API Key。
        timeout: 请求超时上限（秒）。
        max_retries: 失败最大重试次数。
    """

    provider: Literal["fake", "openai", "dashscope", "deepseek", "siliconflow"] = Field(
        default="fake",
        description="LLM 适配提供商",
    )
    model: str = Field(
        default="qwen-max",
        description="模型名称",
    )
    base_url: str | None = Field(
        default=None,
        description="服务端点基础 URL",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="访问凭证 API Key",
    )
    timeout: float = Field(
        default=30.0,
        description="请求超时上限（秒）",
    )
    max_retries: int = Field(
        default=3,
        description="失败最大重试次数",
    )


class OCRSettings(BaseSettings):
    """光学字符识别（OCR）服务配置。

    Attributes:
        provider: OCR 提供商。
        api_key: 百度 API Key 或通用访问密钥（兼容 secret_id）。
        secret_id: 密钥 ID。
        secret_key: 密钥密文。
        region: 服务地域。
        endpoint: 接口端点。
        timeout: 请求超时上限（秒）。
        max_retries: 失败最大重试次数。
    """

    provider: Literal["fake", "tencent", "baidu"] = Field(
        default="fake",
        description="OCR 提供商",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="访问密钥 API Key (兼容 secret_id)",
    )
    secret_id: SecretStr | None = Field(
        default=None,
        description="密钥 ID (兼容 api_key)",
    )
    secret_key: SecretStr | None = Field(
        default=None,
        description="密钥密文",
    )
    region: str = Field(
        default="ap-guangzhou",
        description="服务地域",
    )
    endpoint: str = Field(
        default="ocr.tencentcloudapi.com",
        description="接口端点",
    )
    timeout: float = Field(
        default=20.0,
        description="请求超时上限（秒）",
    )
    max_retries: int = Field(
        default=3,
        description="失败最大重试次数",
    )

    @field_validator("endpoint", mode="before")
    @classmethod
    def _normalize_endpoint(cls, v: Any) -> Any:
        """规范化端点，若用户未填写 http:// 或 https:// 协议头则自动补齐 https://。"""
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped == "ocr.tencentcloudapi.com":
                return v_stripped
            if v_stripped and not v_stripped.startswith(("http://", "https://")):
                return f"https://{v_stripped}"
            return v_stripped
        return v

    @model_validator(mode="before")
    @classmethod
    def _sync_credentials(cls, data: Any) -> Any:
        """兼容处理 api_key 与 secret_id 相互映射。"""
        if isinstance(data, dict):
            if data.get("api_key") is None and data.get("secret_id") is not None:
                data["api_key"] = data["secret_id"]
            elif data.get("secret_id") is None and data.get("api_key") is not None:
                data["secret_id"] = data["api_key"]
        return data

    @property
    def effective_api_key(self) -> SecretStr | None:
        """获取生效的 API Key / Secret ID 凭证。"""
        return self.api_key or self.secret_id


class AppSettings(BaseSettings):
    """智练自主学习平台全局强类型配置中心。

    管理全局运行环境、安全密钥与 9 大功能子域配置。
    支持 ZHILIAN_ 前缀与 __ 嵌套环境变量覆写。

    Attributes:
        env: 当前运行环境（development / test / production）。
        debug: 是否开启调试模式。
        secret_key: 系统核心 JWT 签名私钥。
        db: 数据库子配置。
        redis: Redis 子配置。
        storage: 对象存储子配置。
        llm: 大语言模型子配置。
        ocr: OCR 识别子配置。
        embedding: 向量化模型子配置。
        queue: 任务队列子配置。
        idempotency: 幂等拦截器子配置。
        search: 检索子配置。
    """

    env: Literal["development", "test", "production"] = Field(
        default="development",
        description="当前运行环境",
    )
    debug: bool = Field(
        default=False,
        description="是否开启调试模式",
    )
    secret_key: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_SECRET_KEY),
        description="系统核心 JWT 签名私钥",
    )
    wechat_app_id: str | None = Field(
        default=None,
        description="微信小程序 AppID",
    )
    wechat_app_secret: SecretStr | None = Field(
        default=None,
        description="微信小程序 AppSecret",
    )

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    idempotency: IdempotencySettings = Field(default_factory=IdempotencySettings)
    search: SearchSettings = Field(default_factory=SearchSettings)

    model_config = SettingsConfigDict(
        env_prefix="ZHILIAN_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    @property
    def uses_insecure_default_secret_key(self) -> bool:
        """判断当前 JWT 签名密钥是否仍为开发默认密钥。

        Returns:
            bool: 仍在使用开发默认密钥时返回 True，否则返回 False。
        """
        return self.secret_key.get_secret_value() == DEVELOPMENT_SECRET_KEY


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """获取单例全局配置项。

    使用 lru_cache 避免重复从环境文件解析构建开销。

    Returns:
        AppSettings: 全局配置单例实例。
    """
    return AppSettings()


def validate_secret_key(settings: AppSettings | None = None) -> None:
    """校验 JWT 签名密钥在生产环境的安全性（启动期 fail-fast）。

    生产环境检测到仍使用开发默认密钥时必须立即中止启动，防止以可预测密钥
    签发 JWT 导致凭据可被伪造；非生产环境仅记录告警。

    Args:
        settings: 待校验配置，缺省使用 get_settings() 单例。

    Raises:
        RuntimeError: 当运行环境为 production 且仍使用开发默认密钥时。
    """
    resolved = settings if settings is not None else get_settings()
    if not resolved.uses_insecure_default_secret_key:
        return

    if resolved.env == "production":
        raise RuntimeError(
            "生产环境安全校验失败: 检测到仍在使用开发默认 JWT 密钥，"
            "请通过环境变量 ZHILIAN_SECRET_KEY 注入强随机密钥。"
        )

    logger.warning(
        "当前环境 (%s) 正在使用开发默认 JWT 密钥，生产部署前必须通过 ZHILIAN_SECRET_KEY 覆写。",
        resolved.env,
    )
