"""FastAPI 知识点服务依赖注入模块。

提供解析与获取 KnowledgeService 业务编排服务实例的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge import KnowledgeService


def get_db_session() -> AsyncSession:
    """FastAPI 依赖项：获取数据库异步会话。

    在生产环境下由全局数据库引擎会话工厂提供；
    在单元测试中通过 app.dependency_overrides[get_db_session] 注入。

    Returns:
        AsyncSession: 异步数据库会话对象。

    Raises:
        NotImplementedError: 在未配置数据库连接会话时抛出。
    """
    raise NotImplementedError(
        "数据库会话工厂尚未挂载，请在测试或路由中使用 dependency_overrides[get_db_session] 注入"
    )


def get_knowledge_service(
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> KnowledgeService:
    """FastAPI 依赖项：获取 KnowledgeService 服务实例。

    在生产环境下由服务装配工厂或生命周期依赖提供；
    在单元测试中通过 app.dependency_overrides[get_knowledge_service] 注入。

    Args:
        session: 异步数据库会话（由 get_db_session 依赖注入）。

    Returns:
        KnowledgeService: 知识点领域编排服务。

    Raises:
        NotImplementedError: 在外部服务层装配前直接调用时提醒依赖注入覆盖。
    """
    raise NotImplementedError(
        "KnowledgeService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_knowledge_service] 注入"
    )


__all__ = ["get_db_session", "get_knowledge_service"]
