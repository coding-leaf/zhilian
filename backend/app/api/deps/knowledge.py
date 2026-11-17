"""FastAPI 知识点服务依赖注入模块。

提供解析与获取 KnowledgeService 业务编排服务实例的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from app.api.deps._factory import make_service_dep

get_knowledge_service = make_service_dep(
    service_name="KnowledgeService",
    dep_name="get_knowledge_service",
    builder=lambda container, session: container.create_knowledge_service(session=session),
)
get_knowledge_service.__doc__ = """FastAPI 依赖项：获取 KnowledgeService 服务实例。

优先从请求生命周期的 AppContainer 中以单请求独立 Session 装配服务实例；
在单元测试中通过 app.dependency_overrides[get_knowledge_service] 注入。
"""

__all__ = ["get_knowledge_service"]
