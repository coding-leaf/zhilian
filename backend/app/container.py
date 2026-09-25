"""应用全局装配容器 (AppContainer)。

严格遵循 AGENTS.md 规范：
- 集中管理 SQLAlchemy 数据库引擎连接池与 sessionmaker；
- 托管外部协议注册中心 ProviderRegistry；
- 负责 8 大业务领域服务的依赖注入装配与生命周期管理；
- 提供数据库事务上下文管理器 (get_session) 与 FastAPI 兼容生成器 (get_db_session)；
- 提供应用启动预热 (startup)、优雅停机 (shutdown) 与结构化健康检查 (check_health)。
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings, get_settings
from app.integrations.container import ProviderRegistry
from app.services.auth import AuthService
from app.services.diagnosis import DiagnosisService
from app.services.grading import GradingService
from app.services.knowledge import KnowledgeService
from app.services.material import MaterialService
from app.services.practice import PracticeService
from app.services.question import QuestionService


class HealthResult(dict[str, Any]):
    """健康探测结果容器，同时支持同步字典属性访问与异步 await 等待。"""

    def __await__(self) -> Generator[Any, None, "HealthResult"]:
        """支持将该结果直接当做协程执行 await。"""

        async def _async_self() -> "HealthResult":
            return self

        return _async_self().__await__()


class AppContainer:
    """智练应用全局顶层依赖装配容器。

    管理连接池、会话工厂、基础设施提供商与全套业务领域服务。
    """

    def __init__(
        self,
        settings: AppSettings,
        engine: Engine,
        session_factory: sessionmaker[Session],
        providers: ProviderRegistry,
    ) -> None:
        """初始化应用顶层装配容器。

        Args:
            settings: 全局强类型配置。
            engine: SQLAlchemy 数据库引擎实例。
            session_factory: SQLAlchemy 数据库会话工厂。
            providers: 外部能力适配器注册中心。
        """
        self.settings = settings
        self.engine = engine
        self.session_factory = session_factory
        self.providers = providers
        self.registry = providers

    @classmethod
    def create(
        cls,
        settings: AppSettings | None = None,
        registry: ProviderRegistry | None = None,
        engine: Engine | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> "AppContainer":
        """自底向上装配连接池、注册中心与应用容器实例。

        Args:
            settings: 应用强类型配置，缺省使用 get_settings()。
            registry: 外部能力注册中心，缺省根据配置构建默认注册中心。
            engine: 可选外部注入的 SQLAlchemy 引擎。
            session_factory: 可选外部注入的会话工厂。

        Returns:
            AppContainer: 装配完成的应用容器。
        """
        if settings is None:
            settings = get_settings()

        if engine is None:
            if settings.db.db_url.startswith("sqlite"):
                engine = create_engine(
                    settings.db.db_url,
                    echo=settings.db.echo,
                    connect_args={"check_same_thread": False},
                )
            else:
                engine = create_engine(
                    settings.db.db_url,
                    echo=settings.db.echo,
                    pool_size=settings.db.pool_size,
                    max_overflow=settings.db.max_overflow,
                    pool_timeout=settings.db.pool_timeout,
                    pool_pre_ping=settings.db.pool_pre_ping,
                )

        if session_factory is None:
            session_factory = sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
            )

        if registry is None:
            registry = ProviderRegistry.create_default(
                settings=settings,
                session_factory=session_factory,
            )

        return cls(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            providers=registry,
        )

    @classmethod
    def create_from_settings(
        cls,
        settings: AppSettings | None = None,
        registry: ProviderRegistry | None = None,
    ) -> "AppContainer":
        """兼容从配置构建容器的工厂方法。"""
        return cls.create(settings=settings, registry=registry)

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """产出数据库事务会话上下文管理器。

        Yields:
            Session: 活跃的 SQLAlchemy 数据库事务会话。
        """
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_db_session(self) -> Generator[Session, None, None]:
        """产出单请求生命周期的独立数据库会话 (FastAPI Depends 兼容生成器)。

        Yields:
            Session: 独立数据库会话。
        """
        with self.get_session() as session:
            yield session

    # --------------------------------------------------------------------------
    # 8 大领域服务纯工厂方法 (强制绑定指定独立 Session，杜绝共享会话)
    # --------------------------------------------------------------------------

    def create_auth_service(self, session: Session) -> AuthService:
        """纯工厂方法：构建绑定独立 Session 的 AuthService。"""
        return AuthService(session=session)

    def create_user_service(self, session: Session) -> AuthService:
        """纯工厂方法：构建绑定独立 Session 的用户管理服务 (AuthService 门面兼容)。"""
        return self.create_auth_service(session=session)

    def create_material_service(
        self,
        session: Session,
        knowledge_service: KnowledgeService | None = None,
    ) -> MaterialService:
        """纯工厂方法：构建绑定独立 Session 的 MaterialService。"""
        resolved_knowledge_service = knowledge_service
        if resolved_knowledge_service is None:
            resolved_knowledge_service = self.create_knowledge_service(session)

        return MaterialService(
            session=session,
            storage_adapter=self.providers.storage,
            ocr_adapter=self.providers.ocr,
            embedding_adapter=self.providers.embedding,
            queue_adapter=self.providers.queue,
            idempotency_adapter=self.providers.idempotency,
            knowledge_service=resolved_knowledge_service,
            bucket=self.settings.storage.bucket_name,
        )

    def create_knowledge_service(self, session: Session) -> KnowledgeService:
        """纯工厂方法：构建绑定独立 Session 的 KnowledgeService。"""
        return KnowledgeService(
            session=session,
            llm=self.providers.llm,
            embedding=self.providers.embedding,
        )

    def create_question_service(self, session: Session) -> QuestionService:
        """纯工厂方法：构建绑定独立 Session 的 QuestionService。"""
        return QuestionService(
            session=session,
            llm=self.providers.llm,
            embedding=self.providers.embedding,
            search_adapter=self.providers.search,
        )

    def create_practice_service(self, session: Session) -> PracticeService:
        """纯工厂方法：构建绑定独立 Session 的 PracticeService。"""
        return PracticeService(
            session=session,
            idempotency=self.providers.idempotency,
            queue=self.providers.queue,
        )

    def create_grading_service(self, session: Session) -> GradingService:
        """纯工厂方法：构建绑定独立 Session 的 GradingService。"""
        return GradingService(
            session=session,
            llm_adapter=self.providers.llm,
        )

    def create_diagnosis_service(self, session: Session) -> DiagnosisService:
        """纯工厂方法：构建绑定独立 Session 的 DiagnosisService。"""
        return DiagnosisService(session=session)

    # --------------------------------------------------------------------------
    # 兼容历史调用的别名方法
    # --------------------------------------------------------------------------

    def get_auth_service(self, session: Session) -> AuthService:
        """兼容接口：委托给 create_auth_service。"""
        return self.create_auth_service(session=session)

    def get_user_service(self, session: Session) -> AuthService:
        """兼容接口：委托给 create_user_service。"""
        return self.create_user_service(session=session)

    def get_material_service(self, session: Session) -> MaterialService:
        """兼容接口：委托给 create_material_service。"""
        return self.create_material_service(session=session)

    def get_knowledge_service(self, session: Session) -> KnowledgeService:
        """兼容接口：委托给 create_knowledge_service。"""
        return self.create_knowledge_service(session=session)

    def get_question_service(self, session: Session) -> QuestionService:
        """兼容接口：委托给 create_question_service。"""
        return self.create_question_service(session=session)

    def get_practice_service(self, session: Session) -> PracticeService:
        """兼容接口：委托给 create_practice_service。"""
        return self.create_practice_service(session=session)

    def get_grading_service(self, session: Session) -> GradingService:
        """兼容接口：委托给 create_grading_service。"""
        return self.create_grading_service(session=session)

    def get_diagnosis_service(self, session: Session) -> DiagnosisService:
        """兼容接口：委托给 create_diagnosis_service。"""
        return self.create_diagnosis_service(session=session)

    # --------------------------------------------------------------------------
    # 生命周期与健康探测
    # --------------------------------------------------------------------------

    async def startup(self) -> None:
        """容器启动预热钩子：验证数据库连通性并确保存储桶已初始化。"""
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        self.providers.storage.ensure_bucket_exists(self.settings.storage.bucket_name)

    async def shutdown(self) -> None:
        """容器优雅停机钩子：释放外部适配器连接池并销毁数据库引擎。"""
        await self.providers.shutdown()
        self.engine.dispose()

    def check_health(self) -> HealthResult:
        """执行多组件健康状态检查并返回结构化诊断信息。

        Returns:
            HealthResult: 包含数据库、存储及提供商状态的多组件健康诊断结构。
        """
        db_status = "connected"
        db_details: dict[str, Any] = {
            "status": db_status,
            "dialect": self.engine.dialect.name,
        }

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            db_status = "disconnected"
            db_details["status"] = db_status
            db_details["error"] = str(exc)

        overall_status = "ok" if db_status == "connected" else "degraded"

        result = HealthResult(
            {
                "status": overall_status,
                "app": "ZhiLian",
                "environment": self.settings.env,
                "database": db_details,
                "storage": {
                    "provider": self.settings.storage.provider,
                    "bucket": self.settings.storage.bucket_name,
                },
                "providers": {
                    "llm": self.settings.llm.provider,
                    "ocr": self.settings.ocr.provider,
                    "embedding": self.settings.embedding.provider,
                    "search": self.settings.search.provider,
                    "queue": self.settings.queue.provider,
                },
            }
        )
        return result


__all__ = ["AppContainer", "HealthResult"]
