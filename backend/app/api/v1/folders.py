"""课程文件夹管理 API 路由控制模块。

处理课程文件夹创建、列表、详情、重命名、归档、恢复与立即清理。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps.auth import get_current_user
from app.api.deps.folder import get_folder_service
from app.models.user import User
from app.schemas.folder import (
    FolderCreateRequest,
    FolderDeleteResponse,
    FolderDetailResponse,
    FolderListResponse,
    FolderUpdateRequest,
)
from app.services.folder import FolderAggregate, FolderService

router = APIRouter(prefix="/folders", tags=["folders"])


def _to_detail_response(aggregate: FolderAggregate) -> FolderDetailResponse:
    """将课程聚合视图对象转换为统一详情响应模型。"""
    folder = aggregate.folder
    return FolderDetailResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        sort_order=folder.sort_order,
        is_archived=folder.archived_at is not None,
        archived_at=folder.archived_at,
        purge_after=aggregate.purge_after,
        material_count=aggregate.material_count,
        ready_material_count=aggregate.ready_material_count,
        knowledge_point_count=aggregate.knowledge_point_count,
        question_count=aggregate.question_count,
        last_practice_at=aggregate.last_practice_at,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.post(
    "",
    response_model=FolderDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建课程文件夹",
)
async def create_folder(
    payload: FolderCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderDetailResponse:
    """创建课程文件夹，同用户下重名返回 409。

    Args:
        payload: 课程创建请求体。
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        FolderDetailResponse: 新建课程详情。
    """
    aggregate = folder_service.create_folder(user_id=user.id, name=payload.name)
    return _to_detail_response(aggregate)


@router.get(
    "",
    response_model=FolderListResponse,
    status_code=status.HTTP_200_OK,
    summary="分页检索课程文件夹列表",
)
async def list_folders(
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
    include_archived: Annotated[bool, Query(description="是否包含已归档课程")] = False,
    limit: Annotated[int, Query(ge=1, le=200, description="单页容量")] = 100,
    offset: Annotated[int, Query(ge=0, description="偏移游标")] = 0,
) -> FolderListResponse:
    """分页检索课程文件夹列表（默认隐藏已归档课程，含聚合计数）。

    Args:
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。
        include_archived: 是否包含已归档课程。
        limit: 单页容量限制。
        offset: 偏移游标。

    Returns:
        FolderListResponse: 课程列表与总数。
    """
    aggregates, total = folder_service.list_folders(
        user_id=user.id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return FolderListResponse(
        items=[_to_detail_response(aggregate) for aggregate in aggregates],
        total=total,
    )


@router.get(
    "/{folder_id}",
    response_model=FolderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="获取课程文件夹详情",
)
async def get_folder(
    folder_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderDetailResponse:
    """获取指定课程文件夹详情，越权返回 404。

    Args:
        folder_id: 目标课程主键。
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        FolderDetailResponse: 课程聚合详情。
    """
    aggregate = folder_service.get_folder(user_id=user.id, folder_id=folder_id)
    return _to_detail_response(aggregate)


@router.patch(
    "/{folder_id}",
    response_model=FolderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="重命名课程文件夹",
)
async def rename_folder(
    folder_id: uuid.UUID,
    payload: FolderUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderDetailResponse:
    """重命名指定课程文件夹，重名返回 409。

    Args:
        folder_id: 目标课程主键。
        payload: 重命名请求体。
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        FolderDetailResponse: 重命名后的课程详情。
    """
    aggregate = folder_service.rename_folder(
        user_id=user.id, folder_id=folder_id, name=payload.name
    )
    return _to_detail_response(aggregate)


@router.delete(
    "/{folder_id}",
    response_model=FolderDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="归档课程文件夹",
)
async def archive_folder(
    folder_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderDeleteResponse:
    """归档指定课程文件夹（软删除，7 天后惰性物理清理）。

    Args:
        folder_id: 目标课程主键。
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        FolderDeleteResponse: 归档结果与清理时间。
    """
    aggregate = folder_service.archive_folder(user_id=user.id, folder_id=folder_id)
    return FolderDeleteResponse(
        id=folder_id,
        is_deleted=True,
        archived_at=aggregate.folder.archived_at,
        purge_after=aggregate.purge_after,
        message="课程已归档，7 天内可恢复",
    )


@router.post(
    "/{folder_id}/restore",
    response_model=FolderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="恢复已归档课程文件夹",
)
async def restore_folder(
    folder_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderDetailResponse:
    """恢复已归档课程文件夹，其下资料随之恢复可见。

    Args:
        folder_id: 目标课程主键。
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        FolderDetailResponse: 恢复后的课程详情。
    """
    aggregate = folder_service.restore_folder(user_id=user.id, folder_id=folder_id)
    return _to_detail_response(aggregate)


@router.delete(
    "/{folder_id}/purge",
    response_model=FolderDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="立即物理清理课程文件夹",
)
async def purge_folder(
    folder_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> FolderDeleteResponse:
    """立即物理级联清理指定课程及其下全部资料。

    Args:
        folder_id: 目标课程主键。
        user: 当前登录租户用户对象。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        FolderDeleteResponse: 清理结果。
    """
    folder_service.purge_folder(user_id=user.id, folder_id=folder_id)
    return FolderDeleteResponse(
        id=folder_id,
        is_deleted=True,
        archived_at=None,
        purge_after=None,
        message="课程及其下资料已物理级联清理",
    )


__all__ = [
    "archive_folder",
    "create_folder",
    "get_folder",
    "list_folders",
    "purge_folder",
    "rename_folder",
    "restore_folder",
    "router",
]
