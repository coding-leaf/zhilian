"""FastAPI 练习服务依赖注入模块。

提供解析与获取 PracticeService 业务编排服务实例的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from app.services.practice import PracticeService


def get_practice_service() -> PracticeService:
    """FastAPI 依赖项：获取 PracticeService 服务实例。

    在生产环境下由服务装配工厂或生命周期依赖提供；
    在单元测试中通过 app.dependency_overrides[get_practice_service] 注入。

    Returns:
        PracticeService: 练习会话与组卷编排服务。

    Raises:
        NotImplementedError: 在外部服务层装配前直接调用时提醒依赖注入覆盖。
    """
    raise NotImplementedError(
        "PracticeService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_practice_service] 注入"
    )


__all__ = ["get_practice_service"]
