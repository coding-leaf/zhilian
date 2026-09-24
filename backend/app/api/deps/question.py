"""FastAPI 题目服务依赖注入模块。

提供解析与获取 QuestionService 业务编排服务实例的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.knowledge import get_db_session
from app.services.question import QuestionService


def get_question_service(
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> QuestionService:
    """FastAPI 依赖项：获取 QuestionService 服务实例。

    在生产环境下由服务装配工厂或生命周期依赖提供；
    在单元测试中通过 app.dependency_overrides[get_question_service] 注入。

    Args:
        session: 异步数据库会话（由 get_db_session 依赖注入）。

    Returns:
        QuestionService: 题目领域编排服务。

    Raises:
        NotImplementedError: 在外部服务层装配前直接调用时提醒依赖注入覆盖。
    """
    raise NotImplementedError(
        "QuestionService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_question_service] 注入"
    )


__all__ = ["get_question_service"]
