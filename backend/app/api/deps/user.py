"""FastAPI 用户管理服务依赖注入模块。

提供解析与获取用户管理服务的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from app.services.auth import AuthService


def get_user_service() -> AuthService:
    """FastAPI 依赖项：获取用户管理服务实例 (AuthService 门面)。

    在生产环境下由服务装配工厂提供；
    在单元测试中通过 app.dependency_overrides[get_user_service] 注入。

    Returns:
        AuthService: 用户管理编排服务。

    Raises:
        NotImplementedError: 在服务装配前直接调用时抛出。
    """
    raise NotImplementedError(
        "AuthService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_user_service] 注入"
    )


__all__ = ["get_user_service"]
