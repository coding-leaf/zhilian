"""自定义题单与跨题目收纳 API 路由控制模块。

严禁使用 PATCH（全量仅使用 GET / POST / PUT / DELETE），兼容微信小程序请求规范。
路由函数全部声明为同步 def，严禁直接导入 repositories/。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps.auth import get_current_user
from app.api.deps.collection import get_collection_service
from app.api.v1._filters import parse_folder_filter
from app.models.user import User
from app.schemas.collection import (
    CollectionCreateRequest,
    CollectionItemsAddRequest,
    CollectionItemsAddResponse,
    CollectionListResponse,
    CollectionQuestionListResponse,
    CollectionUpdateRequest,
    QuestionCollectionResponse,
    QuestionCollectionsResponse,
    QuestionCollectionsSyncRequest,
    QuestionCollectionsSyncResponse,
)
from app.services.collection import CollectionService

router = APIRouter(tags=["Collections"])


@router.get(
    "/collections",
    response_model=CollectionListResponse,
    status_code=status.HTTP_200_OK,
    summary="查询自定义题单列表",
)
def list_collections(
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
    folder_id: Annotated[
        str | None,
        Query(description="课程文件夹过滤 ('__none__' 表示未绑定课程的通用题单)"),
    ] = None,
) -> CollectionListResponse:
    """分页/全量查询当前用户自定义题单列表（含活跃题目数量，零 N+1）。"""
    resolved_folder_id, unclassified = parse_folder_filter(folder_id)
    return collection_service.list_collections(
        user_id=current_user.id,
        folder_id=resolved_folder_id,
        unclassified=unclassified,
    )


@router.post(
    "/collections",
    response_model=QuestionCollectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建自定义题单",
)
def create_collection(
    payload: CollectionCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> QuestionCollectionResponse:
    """新建自定义题单（同名返回 409 Conflict）。"""
    return collection_service.create_collection(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        color_token=payload.color_token,
        is_pinned=payload.is_pinned,
    )


@router.put(
    "/collections/{collection_id}",
    response_model=QuestionCollectionResponse,
    status_code=status.HTTP_200_OK,
    summary="更新自定义题单",
)
def update_collection(
    collection_id: uuid.UUID,
    payload: CollectionUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> QuestionCollectionResponse:
    """更新自定义题单名称、简介、绑定课程或置顶状态。"""
    return collection_service.update_collection(
        user_id=current_user.id,
        collection_id=collection_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        clear_folder=payload.clear_folder,
        color_token=payload.color_token,
        is_pinned=payload.is_pinned,
    )


@router.delete(
    "/collections/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除自定义题单",
)
def delete_collection(
    collection_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> Response:
    """删除自定义题单及其关联项，绝不删除原题。"""
    collection_service.delete_collection(
        user_id=current_user.id,
        collection_id=collection_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/collections/{collection_id}/questions",
    response_model=CollectionQuestionListResponse,
    status_code=status.HTTP_200_OK,
    summary="分页查询题单内题目",
)
def list_collection_questions(
    collection_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页题数")] = 20,
) -> CollectionQuestionListResponse:
    """分页返回题单内未软删除题目完整展示详情。"""
    return collection_service.list_collection_questions(
        user_id=current_user.id,
        collection_id=collection_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/collections/{collection_id}/items",
    response_model=CollectionItemsAddResponse,
    status_code=status.HTTP_200_OK,
    summary="批量向题单收纳题目",
)
def add_collection_items(
    collection_id: uuid.UUID,
    payload: CollectionItemsAddRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> CollectionItemsAddResponse:
    """批量幂等向题单加入题目（校验归属与软删除）。"""
    return collection_service.add_items(
        user_id=current_user.id,
        collection_id=collection_id,
        question_ids=payload.question_ids,
        note=payload.note,
    )


@router.delete(
    "/collections/{collection_id}/items/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="从题单移出题目",
)
def remove_collection_item(
    collection_id: uuid.UUID,
    question_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> Response:
    """将指定题目从题单中移出（不删除原题）。"""
    collection_service.remove_item(
        user_id=current_user.id,
        collection_id=collection_id,
        question_id=question_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/questions/{question_id}/collections",
    response_model=QuestionCollectionsResponse,
    status_code=status.HTTP_200_OK,
    summary="查询题目所属题单列表",
)
def get_question_collections(
    question_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> QuestionCollectionsResponse:
    """获取单道题目当前归属的全部自定义题单主键列表。"""
    return collection_service.get_question_collections(
        user_id=current_user.id,
        question_id=question_id,
    )


@router.post(
    "/questions/{question_id}/collections",
    response_model=QuestionCollectionsSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="同步题目所属题单",
)
def sync_question_collections(
    question_id: uuid.UUID,
    payload: QuestionCollectionsSyncRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> QuestionCollectionsSyncResponse:
    """原子同步单道题目归属的所有题单。"""
    return collection_service.sync_question_collections(
        user_id=current_user.id,
        question_id=question_id,
        collection_ids=payload.collection_ids,
    )


__all__ = ["router"]
