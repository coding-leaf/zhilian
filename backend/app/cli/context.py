"""Headless CLI 执行上下文：配置装配、真实链路校验与基础设施探测。

`CliContext` 是 CLI 与生产装配之间唯一的桥梁：
- 通过 `AppContainer.create(settings=...)` 获取引擎、会话工厂与 Provider 注册中心；
- 提供 Provider 配置矩阵、基础设施连通性、迁移版本等只读诊断能力；
- 强制校验真实 Provider 链路，返回结构化配置缺口（`Gap`），由命令层决定退出码。
"""

import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import redis
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.cli.report import redact_url
from app.container import AppContainer
from app.core.config import AppSettings, get_settings


@dataclass(frozen=True)
class Gap:
    """真实链路配置缺口的结构化描述。

    Attributes:
        component: 缺口所属组件（llm/ocr/embedding/search/storage/database）。
        env_key: 建议补齐的环境变量键名。
        expected: 期望的取值形态。
        actual: 当前取值（严禁包含密钥明文）。
        remediation: 修复建议。
    """

    component: str
    env_key: str
    expected: str
    actual: str
    remediation: str = ""

    def to_dict(self) -> dict[str, str]:
        """转换为可序列化字典。"""
        data = {
            "component": self.component,
            "env_key": self.env_key,
            "expected": self.expected,
            "actual": self.actual,
        }
        if self.remediation:
            data["remediation"] = self.remediation
        return data


class CliContext:
    """CLI 执行上下文，封装配置、容器与真实链路校验逻辑。

    Attributes:
        settings: 解析后的强类型全局配置。
        allow_fake: 是否允许 fake/memory Provider（仅用于离线测试）。
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        allow_fake: bool = False,
        container: AppContainer | None = None,
    ) -> None:
        """初始化 CLI 执行上下文。

        Args:
            settings: 强类型全局配置。
            allow_fake: 是否跳过真实 Provider 校验（仅测试用）。
            container: 可选注入的应用容器（测试隔离用），缺省按需懒装配。
        """
        self.settings = settings
        self.allow_fake = allow_fake
        self._container = container

    @classmethod
    def create(
        cls,
        *,
        settings: AppSettings | None = None,
        db_url: str | None = None,
        allow_fake: bool = False,
        container: AppContainer | None = None,
    ) -> "CliContext":
        """构建 CLI 执行上下文，支持 `--db-url` 覆盖数据库连接串。

        Args:
            settings: 可选外部注入配置，缺省使用 get_settings()。
            db_url: 可选数据库连接串覆盖。
            allow_fake: 是否允许 fake/memory Provider。
            container: 可选注入容器。

        Returns:
            CliContext: 装配完成的执行上下文。
        """
        resolved = settings if settings is not None else get_settings()
        if db_url:
            resolved = resolved.model_copy(
                update={"db": resolved.db.model_copy(update={"db_url": db_url})}
            )
        return cls(resolved, allow_fake=allow_fake, container=container)

    @property
    def db_url(self) -> str:
        """当前生效的数据库连接串。"""
        return self.settings.db.db_url

    @property
    def container(self) -> AppContainer:
        """按需懒装配的应用容器（复用生产同款 AppContainer.create）。"""
        if self._container is None:
            self._container = AppContainer.create(settings=self.settings)
        return self._container

    def provider_matrix(self) -> dict[str, dict[str, Any]]:
        """返回 Provider 配置矩阵（仅含 provider 名与是否已配置的布尔值）。

        Returns:
            dict[str, dict[str, Any]]: 各 Provider 的脱敏配置摘要。
        """
        settings = self.settings
        return {
            "llm": {
                "provider": settings.llm.provider,
                "model": settings.llm.model,
                "api_key_configured": settings.llm.api_key is not None,
            },
            "ocr": {
                "provider": settings.ocr.provider,
                "api_key_configured": settings.ocr.effective_api_key is not None,
                "secret_key_configured": settings.ocr.secret_key is not None,
            },
            "embedding": {
                "provider": settings.embedding.provider,
                "model": settings.embedding.model,
                "dimension": settings.embedding.dimension,
                "api_key_configured": settings.embedding.api_key is not None,
            },
            "search": {
                "provider": settings.search.provider,
                "vector_dimension": settings.search.vector_dimension,
            },
            "storage": {
                "provider": settings.storage.provider,
                "endpoint_configured": settings.storage.endpoint_url is not None,
                "access_key_configured": settings.storage.access_key is not None,
                "secret_key_configured": settings.storage.secret_key is not None,
            },
            "queue": {"provider": settings.queue.provider},
            "idempotency": {"provider": settings.idempotency.provider},
        }

    def probe_infra(self) -> dict[str, dict[str, Any]]:
        """探测 DB / Redis / MinIO 连通性，任何异常均转为结构化结果。

        Returns:
            dict[str, dict[str, Any]]: 各基础设施组件的 `reachable` 与 `detail`。
        """
        return {
            "database": self._probe_database(),
            "redis": self._probe_redis(),
            "minio": self._probe_minio(),
        }

    def db_revision(self) -> str | None:
        """读取当前数据库 Alembic 迁移版本号。

        Returns:
            str | None: 迁移版本号；表不存在或不可达时返回 None。
        """
        try:
            engine: Engine = self.container.engine
            with engine.connect() as conn:
                value = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return str(value) if value is not None else None
        except Exception:
            return None

    def assert_real_providers(self, require_ocr: bool = False) -> list[Gap]:
        """校验是否存在 fake/memory/sqlite 回落或密钥缺失。

        Args:
            require_ocr: 是否强制要求真实 OCR Provider（仅图片链路需要）。

        Returns:
            list[Gap]: 结构化配置缺口列表；`allow_fake` 为真或全部合规时为空。
        """
        if self.allow_fake:
            return []

        settings = self.settings
        gaps: list[Gap] = []

        if settings.llm.provider == "fake":
            gaps.append(
                Gap(
                    "llm",
                    "ZHILIAN_LLM__PROVIDER",
                    "openai | dashscope | deepseek | siliconflow",
                    settings.llm.provider,
                    "在 backend/.env 配置真实 LLM Provider 与 API Key。",
                )
            )
        elif settings.llm.api_key is None:
            gaps.append(
                Gap(
                    "llm",
                    "ZHILIAN_LLM__API_KEY",
                    "非空 API Key",
                    "未配置",
                    "补齐真实 LLM 服务访问密钥。",
                )
            )

        if settings.embedding.provider == "fake":
            gaps.append(
                Gap(
                    "embedding",
                    "ZHILIAN_EMBEDDING__PROVIDER",
                    "openai | dashscope",
                    settings.embedding.provider,
                    "在 backend/.env 配置真实向量化 Provider 与 API Key。",
                )
            )
        elif settings.embedding.api_key is None:
            gaps.append(
                Gap(
                    "embedding",
                    "ZHILIAN_EMBEDDING__API_KEY",
                    "非空 API Key",
                    "未配置",
                    "补齐真实向量化服务访问密钥。",
                )
            )

        if settings.search.provider == "fake":
            gaps.append(
                Gap(
                    "search",
                    "ZHILIAN_SEARCH__PROVIDER",
                    "pgvector",
                    settings.search.provider,
                    "在 backend/.env 配置 ZHILIAN_SEARCH__PROVIDER=pgvector。",
                )
            )

        if settings.storage.provider == "memory":
            gaps.append(
                Gap(
                    "storage",
                    "ZHILIAN_STORAGE__PROVIDER",
                    "minio | s3",
                    settings.storage.provider,
                    "在 backend/.env 配置真实对象存储 Provider 与连接参数。",
                )
            )
        elif settings.storage.access_key is None or settings.storage.secret_key is None:
            gaps.append(
                Gap(
                    "storage",
                    "ZHILIAN_STORAGE__ACCESS_KEY / ZHILIAN_STORAGE__SECRET_KEY",
                    "非空访问密钥对",
                    "存在未配置项",
                    "补齐对象存储 Access Key 与 Secret Key。",
                )
            )

        if settings.db.db_url.startswith("sqlite"):
            gaps.append(
                Gap(
                    "database",
                    "ZHILIAN_DB__DB_URL",
                    "postgresql+psycopg://user:pass@host:5432/db",
                    redact_url(settings.db.db_url),
                    "配置真实 PostgreSQL 连接串（含 pgvector 扩展）。",
                )
            )

        if require_ocr:
            if settings.ocr.provider == "fake":
                gaps.append(
                    Gap(
                        "ocr",
                        "ZHILIAN_OCR__PROVIDER",
                        "tencent | baidu",
                        settings.ocr.provider,
                        "在 backend/.env 配置真实 OCR Provider 与凭证。",
                    )
                )
            elif settings.ocr.effective_api_key is None:
                gaps.append(
                    Gap(
                        "ocr",
                        "ZHILIAN_OCR__API_KEY",
                        "非空 API Key / Secret ID",
                        "未配置",
                        "补齐真实 OCR 服务访问凭证。",
                    )
                )

        return gaps

    def _probe_database(self) -> dict[str, Any]:
        try:
            engine: Engine = self.container.engine
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"reachable": True, "detail": f"dialect={engine.dialect.name}"}
        except Exception as exc:
            return {"reachable": False, "detail": str(exc)}

    def _probe_redis(self) -> dict[str, Any]:
        url = self.settings.redis.redis_url
        try:
            client = redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.ping()
            return {"reachable": True, "detail": "ping ok"}
        except Exception as exc:
            return {"reachable": False, "detail": str(exc)}

    def _probe_minio(self) -> dict[str, Any]:
        settings = self.settings.storage
        if settings.provider == "memory":
            return {"reachable": True, "detail": "storage provider=memory，跳过端点探测"}
        endpoint = settings.endpoint_url
        if not endpoint:
            return {"reachable": False, "detail": "storage.endpoint_url 未配置"}
        try:
            parsed = urlsplit(endpoint)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 9000)
            with socket.create_connection((host, port), timeout=0.5):
                return {"reachable": True, "detail": f"tcp {host}:{port} open"}
        except Exception as exc:
            return {"reachable": False, "detail": str(exc)}


__all__ = ["CliContext", "Gap"]
