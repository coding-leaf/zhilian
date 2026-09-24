"""知识点树形拓扑与切片双向溯源 API 路由控制模块。

处理资料知识树获取、知识点详情查询、切片正反向溯源及结构化抽取触发。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、依赖注入、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps.auth import get_current_user
from app.api.deps.knowledge import get_knowledge_service
from app.models.user import User
from app.schemas.knowledge import (
    ExtractKnowledgeRequest,
    ExtractKnowledgeResponse,
    KnowledgePointDetailResponse,
    KnowledgeTreeNodeResponse,
    KnowledgeTreeResponse,
    PointSourceListResponse,
    SnippetKnowledgePointsResponse,
    SnippetSourceResponse,
)
from app.services.knowledge import KnowledgeService

router = APIRouter(tags=["knowledge"])


@router.get(
    "/materials/{material_id}/knowledge-tree",
    response_model=KnowledgeTreeResponse,
    status_code=status.HTTP_200_OK,
    summary="获取学习资料知识树拓扑",
)
async def get_knowledge_tree(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    version_id: Annotated[
        uuid.UUID | None,
        Query(description="指定资料版本主键 (缺省自动使用最新版本)"),
    ] = None,
) -> KnowledgeTreeResponse:
    """获取指定学习资料与版本的知识点树形嵌套拓扑结构。

    Args:
        material_id: 学习资料主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        knowledge_service: 知识点领域编排服务。
        version_id: 可选的资料版本标识。

    Returns:
        KnowledgeTreeResponse: 包含根知识点列表与子拓扑树的响应对象。
    """
    nodes = knowledge_service.get_knowledge_tree(
        material_id=material_id,
        version_id=version_id,
        user_id=user.id,
    )
    if version_id is None:
        resolved_version_id = (
            uuid.UUID(nodes[0]["version_id"])
            if nodes
            else knowledge_service.get_latest_version_id(material_id, user.id)
        )
    else:
        resolved_version_id = version_id

    parsed_nodes = [KnowledgeTreeNodeResponse.model_validate(n) for n in nodes]
    return KnowledgeTreeResponse(
        material_id=material_id,
        version_id=resolved_version_id,
        nodes=parsed_nodes,
    )


@router.get(
    "/knowledge/{id}",
    response_model=KnowledgePointDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="获取知识点详情",
)
async def get_knowledge_point_detail(
    id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgePointDetailResponse:
    """获取单个知识点的元数据详情与状态标记。

    Args:
        id: 知识点主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        knowledge_service: 知识点领域编排服务。

    Returns:
        KnowledgePointDetailResponse: 知识点详情响应。
    """
    point = knowledge_service.get_knowledge_point_detail(
        knowledge_point_id=id,
        user_id=user.id,
    )
    return KnowledgePointDetailResponse.model_validate(point)


@router.get(
    "/knowledge/{id}/snippets",
    response_model=PointSourceListResponse,
    status_code=status.HTTP_200_OK,
    summary="知识点反向溯源关联切片列表",
)
async def get_knowledge_point_snippets(
    id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> PointSourceListResponse:
    """反向溯源：查询指定知识点关联的全部来源切片列表。

    Args:
        id: 知识点主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        knowledge_service: 知识点领域编排服务。

    Returns:
        PointSourceListResponse: 包含知识点与关联切片列表的响应。
    """
    snippets = knowledge_service.get_snippets_for_point(
        knowledge_point_id=id,
        user_id=user.id,
    )
    return PointSourceListResponse(
        knowledge_point_id=id,
        snippets=[SnippetSourceResponse.model_validate(s) for s in snippets],
    )


@router.get(
    "/knowledge/snippets/{snippet_id}/knowledge-points",
    response_model=SnippetKnowledgePointsResponse,
    status_code=status.HTTP_200_OK,
    summary="切片正向溯源关联知识点列表",
)
async def get_snippet_knowledge_points(
    snippet_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> SnippetKnowledgePointsResponse:
    """正向溯源：查询指定资料切片关联的所有知识点列表。

    Args:
        snippet_id: 切片主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        knowledge_service: 知识点领域编排服务。

    Returns:
        SnippetKnowledgePointsResponse: 包含切片与关联知识点列表的响应。
    """
    points = knowledge_service.get_points_for_snippet(
        snippet_id=snippet_id,
        user_id=user.id,
    )
    return SnippetKnowledgePointsResponse(
        snippet_id=snippet_id,
        knowledge_points=[KnowledgePointDetailResponse.model_validate(p) for p in points],
    )


@router.post(
    "/materials/{material_id}/knowledge/extract",
    response_model=ExtractKnowledgeResponse,
    status_code=status.HTTP_200_OK,
    summary="触发知识点结构化抽取与建树",
)
async def trigger_knowledge_extraction(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    request_data: Annotated[
        ExtractKnowledgeRequest | None,
        Body(description="抽取触发请求体参数"),
    ] = None,
) -> ExtractKnowledgeResponse:
    """触发指定资料切片的知识点抽取、语义去重、门禁质检与拓扑建树。

    Args:
        material_id: 学习资料主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        knowledge_service: 知识点领域编排服务。
        request_data: 可选的抽取配置入参（如指定版本）。

    Returns:
        ExtractKnowledgeResponse: 抽取完成概要指标与就绪状态。
    """
    version_id = request_data.version_id if request_data else None
    result = knowledge_service.trigger_extraction(
        material_id=material_id,
        version_id=version_id,
        user_id=user.id,
    )
    return ExtractKnowledgeResponse.model_validate(result)


__all__ = ["router"]
