"""题目管理、生成与质检拦截 API 路由控制模块。

处理题目结构化生成、详情查询、多条件筛选、编辑留痕、软删除、修改审计日志与质检拦截明细查询。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、依赖注入、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, status

from app.api.deps.auth import get_current_user
from app.api.deps.question import get_question_service
from app.models.user import User
from app.schemas.question import (
    MaterialQualityChecksResponse,
    QuestionAuditLogsResponse,
    QuestionDeleteResponse,
    QuestionDetailResponse,
    QuestionEditLogResponse,
    QuestionGenerateRequest,
    QuestionGenerateResponse,
    QuestionListResponse,
    QuestionQualityCheckResponse,
    QuestionUpdateRequest,
)
from app.services.question import (
    GenerateQuestionsOptions,
    MultiKnowledgePointGenerationResult,
    QuestionGenerationResult,
    QuestionService,
)

router = APIRouter(tags=["questions"])


async def _resolve_delete_reason(request: Request, reason: str | None) -> str | None:
    """解析删除原因，优先 Query，缺省时兜底读取 JSON 请求体的 reason 字段。

    Args:
        request: 原始 HTTP 请求对象。
        reason: Query 参数传入的删除原因。

    Returns:
        str | None: 解析到的删除原因，均缺省时返回 None。
    """
    if reason is not None:
        return reason
    try:
        body = await request.json()
    except Exception:
        return None
    if isinstance(body, dict):
        body_reason = body.get("reason")
        if isinstance(body_reason, str):
            return body_reason
    return None


def _build_generate_response(
    result: QuestionGenerationResult | MultiKnowledgePointGenerationResult,
    knowledge_point_ids: list[uuid.UUID],
) -> QuestionGenerateResponse:
    """将单/多考点生成结果统一映射为出题响应模型。

    Args:
        result: 单考点或多考点生成结果对象。
        knowledge_point_ids: 本次覆盖的全部知识点标识列表。

    Returns:
        QuestionGenerateResponse: 出题生成与门禁质检结果概要及题目明细。
    """
    qualified_items = result.qualified_questions
    pending_items = result.pending_questions
    check_items = result.quality_checks

    return QuestionGenerateResponse(
        batch_id=result.batch_id,
        material_id=result.material_id,
        version_id=result.version_id,
        knowledge_point_id=result.knowledge_point_id,
        knowledge_point_ids=knowledge_point_ids,
        total_generated=result.total_generated,
        qualified_count=len(qualified_items),
        pending_count=len(pending_items),
        retry_count=result.retry_count,
        qualified_questions=[QuestionDetailResponse.model_validate(q) for q in qualified_items],
        pending_questions=[QuestionDetailResponse.model_validate(q) for q in pending_items],
        quality_checks=[QuestionQualityCheckResponse.model_validate(qc) for qc in check_items],
    )


@router.post(
    "/questions/generate",
    response_model=QuestionGenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="触发出题生成与质检门禁",
)
async def generate_questions(
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
    payload: Annotated[QuestionGenerateRequest, Body(description="出题生成配置请求体")],
) -> QuestionGenerateResponse:
    """触发出题生成流水线。

    Args:
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。
        payload: 出题生成请求配置模型。

    Returns:
        QuestionGenerateResponse: 出题生成与门禁质检结果概要及题目明细。

    Raises:
        MissingSourceSnippetError: 知识点无切片或相似度未达标门禁时阻断抛出 (40003)。
        KnowledgeNotFoundError: 知识点不存在或越权 (40007)。
        MaterialNotFoundError: 资料不存在或越权 (40010)。
    """
    options = GenerateQuestionsOptions(
        question_types=tuple(payload.question_types),
        count=payload.count,
        difficulty=payload.difficulty,
        max_retries=payload.max_retries,
    )
    target_kp_ids = list(payload.knowledge_point_ids)
    if not target_kp_ids and payload.knowledge_point_id is not None:
        target_kp_ids = [payload.knowledge_point_id]

    # 课程文件夹范围：跨资料分组出题（考点缺省取文件夹全部）。
    if payload.folder_id is not None:
        folder_result = question_service.generate_questions_for_folder(
            user_id=user.id,
            folder_id=payload.folder_id,
            knowledge_point_ids=target_kp_ids or None,
            options=options,
        )
        return _build_generate_response(
            result=folder_result,
            knowledge_point_ids=list(folder_result.knowledge_point_ids),
        )

    # 多考点：走均分编排；单考点：保持既有单考点链路（向后兼容）。
    material_id = payload.material_id
    if material_id is None:  # pragma: no cover - 校验器保证 folder_id 为空时 material_id 必填
        raise ValueError("material_id 必须指定")

    if len(target_kp_ids) > 1:
        multi_result = question_service.generate_questions_for_knowledge_points(
            user_id=user.id,
            material_id=material_id,
            version_id=payload.version_id,
            knowledge_point_ids=target_kp_ids,
            options=options,
        )
        return _build_generate_response(
            result=multi_result,
            knowledge_point_ids=list(multi_result.knowledge_point_ids),
        )

    result = question_service.generate_questions(
        user_id=user.id,
        material_id=material_id,
        version_id=payload.version_id,
        knowledge_point_id=target_kp_ids[0],
        options=options,
    )
    return _build_generate_response(
        result=result,
        knowledge_point_ids=[result.knowledge_point_id],
    )


@router.get(
    "/questions/{id}",
    response_model=QuestionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="获取题目详情",
)
async def get_question_detail(
    id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
) -> QuestionDetailResponse:
    """获取单个题目详情，含 6 要素、来源切片溯源及质检状态。

    Args:
        id: 题目主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。

    Returns:
        QuestionDetailResponse: 题目完整元数据详情。

    Raises:
        QuestionNotFoundError: 题目不存在或越权访问 (40009)。
    """
    question = question_service.get_question_detail(
        question_id=id,
        user_id=user.id,
    )
    return QuestionDetailResponse.model_validate(question)


@router.get(
    "/questions",
    response_model=QuestionListResponse,
    status_code=status.HTTP_200_OK,
    summary="多条件筛选查询题目列表",
)
async def list_questions(
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
    material_id: Annotated[uuid.UUID | None, Query(description="按学习资料标识过滤")] = None,
    folder_id: Annotated[uuid.UUID | None, Query(description="按课程文件夹标识过滤")] = None,
    knowledge_point_id: Annotated[uuid.UUID | None, Query(description="按知识点标识过滤")] = None,
    question_type: Annotated[str | None, Query(description="按题型过滤")] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5, description="按难度系数 1~5 过滤")] = None,
    review_status: Annotated[
        str | None, Query(description="按审核状态过滤 (available / pending_review)")
    ] = None,
    status_filter: Annotated[str | None, Query(alias="status", description="题目状态过滤")] = None,
    page: Annotated[int, Query(ge=1, description="当前页码，从 1 开始")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页记录数")] = 20,
    limit: Annotated[int | None, Query(ge=1, le=100, description="单页限制 (兼容)")] = None,
    offset: Annotated[int | None, Query(ge=0, description="游标偏移量 (兼容)")] = None,
) -> QuestionListResponse:
    """多条件组合筛选并分页查询题目列表。

    Args:
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。
        material_id: 可选的资料主键过滤。
        folder_id: 可选的课程文件夹主键过滤。
        knowledge_point_id: 可选的知识点主键过滤。
        question_type: 可选的题型过滤。
        difficulty: 可选的难度过滤。
        review_status: 可选的审核/可用状态过滤。
        status_filter: 别名状态过滤。
        page: 页码。
        page_size: 每页记录数。
        limit: 单页记录数限制。
        offset: 游标偏移量。

    Returns:
        QuestionListResponse: 分页题目列表及总数。
    """
    effective_limit = limit if limit is not None else page_size
    effective_offset = offset if offset is not None else (max(page - 1, 0) * effective_limit)
    effective_status = review_status if review_status is not None else status_filter

    items, total = question_service.list_questions(
        user_id=user.id,
        material_id=material_id,
        folder_id=folder_id,
        knowledge_point_id=knowledge_point_id,
        question_type=question_type,
        difficulty=difficulty,
        review_status=effective_status,
        page=page,
        page_size=effective_limit,
        limit=effective_limit,
        offset=effective_offset,
    )
    return QuestionListResponse(
        items=[QuestionDetailResponse.model_validate(q) for q in items],
        total=total,
        limit=effective_limit,
        offset=effective_offset,
    )


@router.put(
    "/questions/{id}",
    response_model=QuestionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="题目审核与人工修改（写入修改审计日志）",
)
async def update_question(
    id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
    payload: Annotated[QuestionUpdateRequest, Body(description="题目修改参数请求体")],
) -> QuestionDetailResponse:
    """更新题目内容并在同一事务内留存修改痕迹审计日志。

    Args:
        id: 题目主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。
        payload: 题目更新数据模型。

    Returns:
        QuestionDetailResponse: 更新后的题目元数据详情。

    Raises:
        QuestionNotFoundError: 题目不存在或越权 (40009)。
    """
    update_data = payload.model_dump(
        exclude={"reason", "edit_reason"},
        exclude_unset=True,
    )
    filtered_updates = {k: v for k, v in update_data.items() if v is not None}
    edit_reason = payload.reason or payload.edit_reason

    updated_question = question_service.update_question(
        question_id=id,
        user_id=user.id,
        update_data=filtered_updates,
        edit_reason=edit_reason,
    )
    return QuestionDetailResponse.model_validate(updated_question)


@router.delete(
    "/questions/{id}",
    response_model=QuestionDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="软删除题目",
)
async def delete_question(
    id: uuid.UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
    reason: Annotated[str | None, Query(description="删除原因说明")] = None,
) -> QuestionDeleteResponse:
    """对题目执行软删除并保留不可变审计痕迹。

    Args:
        id: 题目主键 UUIDv4。
        request: 原始 HTTP 请求对象，用于请求体原因兜底解析。
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。
        reason: 可选的删除原因备注。

    Returns:
        QuestionDeleteResponse: 软删除执行结果。

    Raises:
        QuestionNotFoundError: 题目不存在或越权 (40009)。
    """
    resolved_reason = await _resolve_delete_reason(request, reason)
    success = question_service.delete_question(
        question_id=id,
        user_id=user.id,
        reason=resolved_reason,
    )
    return QuestionDeleteResponse(
        id=id,
        is_deleted=success,
        message="题目已软删除",
    )


@router.get(
    "/questions/{id}/edit-logs",
    response_model=QuestionAuditLogsResponse,
    status_code=status.HTTP_200_OK,
    summary="查看题目修改痕迹审计日志",
)
async def list_question_edit_logs(
    id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
) -> QuestionAuditLogsResponse:
    """获取指定题目的修改痕迹审计日志列表。

    Args:
        id: 题目主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。

    Returns:
        QuestionAuditLogsResponse: 审计日志列表。

    Raises:
        QuestionNotFoundError: 题目不存在或越权 (40009)。
    """
    logs = question_service.list_edit_logs(
        question_id=id,
        user_id=user.id,
    )
    return QuestionAuditLogsResponse(
        question_id=id,
        logs=[QuestionEditLogResponse.model_validate(log) for log in logs],
    )


@router.get(
    "/materials/{material_id}/quality-checks",
    response_model=MaterialQualityChecksResponse,
    status_code=status.HTTP_200_OK,
    summary="查看资料下题目质检拦截记录",
)
async def list_material_quality_checks(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    question_service: Annotated[QuestionService, Depends(get_question_service)],
) -> MaterialQualityChecksResponse:
    """查看指定资料下所有题目的质检检查与拦截明细记录。

    Args:
        material_id: 学习资料主键 UUIDv4。
        user: 当前已认证登录租户用户对象。
        question_service: 题目领域编排服务。

    Returns:
        MaterialQualityChecksResponse: 资料下关联题目质检记录列表。

    Raises:
        MaterialNotFoundError: 资料不存在或越权 (40010)。
    """
    checks = question_service.list_quality_checks(
        material_id=material_id,
        user_id=user.id,
    )
    return MaterialQualityChecksResponse(
        material_id=material_id,
        quality_checks=[QuestionQualityCheckResponse.model_validate(qc) for qc in checks],
    )


__all__ = ["router"]
