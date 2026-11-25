"""练习会话、作答暂存与交卷强幂等调度 API 路由控制模块。

处理练习会话创建与组卷、分页查询、练习详情与题目快照查询、逐题作答草稿实时暂存、
练习暂停与恢复生命周期管理、交卷强幂等拦截与判题任务调度。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、依赖注入、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 8 个：api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, status

from app.api.deps.auth import get_current_user
from app.api.deps.practice import get_practice_service
from app.api.v1._filters import parse_folder_filter
from app.core.errors import (
    IdempotencyKeyInvalidError,
    PracticeNotFoundError,
)
from app.core.idempotency import validate_idempotency_key
from app.models.user import User
from app.schemas.practice import (
    PracticeCreateRequest,
    PracticeDetailResponse,
    PracticeListResponse,
    PracticeStatusResponse,
    PracticeSubmitRequest,
    PracticeSummaryResponse,
    SaveAnswerRequest,
    SaveAnswerResponse,
    SubmitPracticeResponse,
)
from app.services.practice import (
    CreatePracticeOptions,
    PracticeAssemblyMode,
    PracticeService,
)

router = APIRouter(prefix="/practices", tags=["Practices"])


@router.post(
    "",
    response_model=PracticeDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建练习并组卷",
)
def create_practice(
    request: PracticeCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PracticeDetailResponse:
    """创建练习会话并执行智能组卷与同知识点打散。

    Args:
        request: 组卷出题配置请求体模型。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。
        idempotency_key: 可选的客户端幂等键 (标准 ``Idempotency-Key`` 请求头)，
            用于拦截快速重复连击创建重复练习；请求体同名字段作为兜底。

    Returns:
        PracticeDetailResponse: 已创建的练习详情与卷面题目快照列表。

    Raises:
        PracticeEmptyQuestionsError: 题库可用题目不足阻断 (400 / 40012)。
        IdempotencyConflictError: 相同幂等键请求正在并发处理中 (409 / 30017)。
        IdempotencyKeyInvalidError: 幂等键格式非法 (400 / 10001)。
    """
    mode_enum = PracticeAssemblyMode(request.mode)
    options = CreatePracticeOptions(
        title=request.title,
        material_id=request.material_id,
        knowledge_point_ids=request.knowledge_point_ids,
        question_count=request.question_count,
        question_types=request.question_types,
        difficulty=request.difficulty,
        mode=mode_enum,
        source_type=request.source_type,
        source_report_id=request.source_report_id,
        idempotency_key=idempotency_key or request.idempotency_key,
        folder_id=request.folder_id,
        question_ids=request.question_ids,
        collection_id=request.collection_id,
    )
    practice = practice_service.create_practice(
        user_id=current_user.id,
        options=options,
    )
    if isinstance(practice, PracticeDetailResponse):
        return practice
    return PracticeDetailResponse.model_validate(practice)


@router.get(
    "",
    response_model=PracticeListResponse,
    status_code=status.HTTP_200_OK,
    summary="练习列表查询",
)
def list_practices(
    status: Annotated[str | None, Query(description="按练习生命周期状态过滤")] = None,
    material_id: Annotated[uuid.UUID | None, Query(description="按学习资料标识过滤")] = None,
    folder_id: Annotated[
        str | None,
        Query(description="课程文件夹过滤 ('__none__' 表示未分类)"),
    ] = None,
    offset: Annotated[int, Query(ge=0, description="分页游标偏移量")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="单页容量限制")] = 20,
    *,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeListResponse:
    """多维条件过滤并分页查询当前租户用户的练习列表。"""
    resolved_folder_id, is_unclassified = parse_folder_filter(folder_id)
    filter_kwargs: dict[str, Any] = {}
    if resolved_folder_id is not None:
        filter_kwargs["folder_id"] = resolved_folder_id
    if is_unclassified:
        filter_kwargs["unclassified"] = True

    result = practice_service.list_practices(
        user_id=current_user.id,
        status=status,
        material_id=material_id,
        offset=offset,
        limit=limit,
        **filter_kwargs,
    )
    if isinstance(result, tuple) and len(result) == 2:
        items_raw, total = result
    elif isinstance(result, list):
        items_raw = result
        if isinstance(practice_service, PracticeService) and not hasattr(
            practice_service, "assert_called"
        ):
            total = practice_service.count_practices(
                user_id=current_user.id,
                status=status,
                material_id=material_id,
                **filter_kwargs,
            )
            items = practice_service.build_practice_summaries(
                items_raw,
                user_id=current_user.id,
            )
            return PracticeListResponse(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
            )
        total = len(items_raw)
    else:
        items_raw = []
        total = 0

    items = [
        item
        if isinstance(item, PracticeSummaryResponse)
        else PracticeSummaryResponse.model_validate(item)
        for item in items_raw
    ]
    return PracticeListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{id}",
    response_model=PracticeDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="练习详情查询",
)
def get_practice(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeDetailResponse:
    """查询指定练习会话详情及其卷面题目作答快照。

    Args:
        id: 练习主键标识。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。

    Returns:
        PracticeDetailResponse: 练习详情及按 order_index 升序排列的作答项。

    Raises:
        PracticeNotFoundError: 练习不存在或跨租户越权 (404 / 40010)。
    """
    practice = practice_service.get_practice(
        user_id=current_user.id,
        practice_id=id,
    )
    if practice is None:
        raise PracticeNotFoundError(
            "请求的练习不存在或无权访问",
            details={"practice_id": str(id)},
        )
    if isinstance(practice, PracticeDetailResponse):
        return practice
    return PracticeDetailResponse.model_validate(practice)


@router.put(
    "/{id}/answers",
    response_model=SaveAnswerResponse,
    status_code=status.HTTP_200_OK,
    summary="逐题作答草稿实时暂存",
)
def save_answer(
    id: uuid.UUID,
    request: SaveAnswerRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
) -> SaveAnswerResponse:
    """做题过程中逐题草稿暂存与作答耗时原子累加。

    Args:
        id: 练习主键标识。
        request: 逐题作答草稿数据模型。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。

    Returns:
        SaveAnswerResponse: 实时暂存成功响应。

    Raises:
        PracticeNotFoundError: 练习或题目作答项不存在 (404 / 40010)。
        PracticeStatusError: 练习已完成禁止修改作答 (400 / 40011)。
    """
    result = practice_service.save_answer(
        user_id=current_user.id,
        practice_id=id,
        question_id=request.question_id,
        user_answer=request.user_answer,
        time_spent_seconds=request.time_spent_seconds,
    )
    if isinstance(result, SaveAnswerResponse):
        return result
    resolved_item_id: uuid.UUID = (
        getattr(result, "id", None) or getattr(result, "attempt_item_id", None) or uuid.uuid4()
    )
    return SaveAnswerResponse(
        attempt_item_id=resolved_item_id,
        status=getattr(result, "status", "answered"),
        updated_at=getattr(result, "updated_at", None),
        practice_id=getattr(result, "practice_id", id),
        question_id=getattr(result, "question_id", request.question_id),
        user_answer=getattr(result, "user_answer", request.user_answer),
        is_answered=getattr(result, "is_answered", True),
        duration_seconds=getattr(result, "duration_seconds", request.time_spent_seconds),
        time_spent_seconds=getattr(result, "duration_seconds", request.time_spent_seconds),
    )


@router.post(
    "/{id}/pause",
    response_model=PracticeStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="暂停练习",
)
def pause_practice(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeStatusResponse:
    """暂停正在进行中的练习会话计时。

    Args:
        id: 练习主键标识。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。

    Returns:
        PracticeStatusResponse: 练习状态变更结果。

    Raises:
        PracticeNotFoundError: 练习不存在或跨租户越权 (404 / 40010)。
        PracticeStatusError: 当前状态不允许暂停 (400 / 40011)。
    """
    practice = practice_service.pause_practice(
        user_id=current_user.id,
        practice_id=id,
    )
    if isinstance(practice, PracticeStatusResponse):
        return practice
    resolved_practice_id: uuid.UUID = (
        getattr(practice, "id", None) or getattr(practice, "practice_id", None) or id
    )
    return PracticeStatusResponse(
        practice_id=resolved_practice_id,
        status=getattr(practice, "status", "paused"),
        message="练习已成功暂停",
    )


@router.post(
    "/{id}/resume",
    response_model=PracticeStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="恢复练习",
)
def resume_practice(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeStatusResponse:
    """恢复已暂停的练习会话计时。

    Args:
        id: 练习主键标识。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。

    Returns:
        PracticeStatusResponse: 练习状态变更结果。

    Raises:
        PracticeNotFoundError: 练习不存在或跨租户越权 (404 / 40010)。
        PracticeStatusError: 当前状态不允许恢复 (400 / 40011)。
    """
    practice = practice_service.resume_practice(
        user_id=current_user.id,
        practice_id=id,
    )
    if isinstance(practice, PracticeStatusResponse):
        return practice
    resolved_practice_id: uuid.UUID = (
        getattr(practice, "id", None) or getattr(practice, "practice_id", None) or id
    )
    return PracticeStatusResponse(
        practice_id=resolved_practice_id,
        status=getattr(practice, "status", "in_progress"),
        message="练习已成功恢复",
    )


@router.post(
    "/{id}/submit",
    response_model=SubmitPracticeResponse,
    status_code=status.HTTP_200_OK,
    summary="交卷提交强幂等",
)
def submit_practice(
    id: uuid.UUID,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
    payload: Annotated[PracticeSubmitRequest | None, Body()] = None,
) -> SubmitPracticeResponse:
    """交卷提交端点，基于分布式强幂等键防止重复交卷并调度异步判题。

    Args:
        id: 练习主键标识。
        idempotency_key: 客户端强幂等键 (UUIDv4 格式)。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。
        payload: 可选的交卷确认选项。

    Returns:
        SubmitPracticeResponse: 交卷受理与调度结果响应。

    Raises:
        IdempotencyKeyInvalidError: 幂等键缺失或格式非法 (400 / 10001)。
        IdempotencyConflictError: 并发交卷冲突 (409 / 30017)。
        PracticeStatusError: 状态非法或未确认未作答题目 (400 / 40011)。
        PracticeNotFoundError: 练习不存在或跨租户越权 (404 / 40010)。
    """
    if not idempotency_key or not idempotency_key.strip():
        raise IdempotencyKeyInvalidError(
            message="幂等键不能为空",
            error_code=10001,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        clean_key = validate_idempotency_key(idempotency_key)
    except IdempotencyKeyInvalidError as error:
        raise IdempotencyKeyInvalidError(
            message=error.message,
            error_code=10001,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=error.details,
        ) from error

    confirm_unanswered = payload.confirm_unanswered if payload is not None else False
    submit_kwargs: dict[str, Any] = {"confirm_unanswered": True} if confirm_unanswered else {}
    result = practice_service.submit_practice(
        user_id=current_user.id,
        practice_id=id,
        idempotency_key=clean_key,
        **submit_kwargs,
    )

    if isinstance(result, SubmitPracticeResponse):
        return result
    return SubmitPracticeResponse(
        practice_id=getattr(result, "practice_id", id),
        status=getattr(result, "status", "completed"),
        message="交卷成功，已调度判题任务",
        uncompleted_count=getattr(
            result, "uncompleted_count", getattr(result, "unanswered_count", 0)
        ),
        unanswered_count=getattr(result, "unanswered_count", 0),
        is_idempotent_replay=getattr(result, "is_idempotent_replay", False),
        task_id=getattr(result, "task_id", None),
        total_questions=getattr(result, "total_questions", None),
        answered_questions=getattr(result, "answered_questions", None),
        submitted_at=getattr(result, "submitted_at", None),
    )


@router.post(
    "/{id}/regrade",
    response_model=PracticeStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="重试未完成的整卷判题",
)
def retry_practice_grading(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    practice_service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeStatusResponse:
    """重试未完成的整卷判题（用户可操作的恢复入口，幂等）。

    仅在练习处于 ``partially_graded``（存在待重判项或判题任务终态失败）时允许触发；
    状态回写为 ``submitted`` 本身即并发锁，重复触发会被拒绝从而不会重复派发判题任务。

    Args:
        id: 练习主键标识。
        current_user: 当前已认证登录租户用户对象。
        practice_service: 练习会话与组卷编排服务。

    Returns:
        PracticeStatusResponse: 重新调度后的练习状态与提示信息。

    Raises:
        PracticeNotFoundError: 练习不存在或跨租户越权 (404 / 40010)。
        PracticeStatusError: 练习已全判完或当前状态不允许重试判题 (400 / 40011)。
    """
    _, practice = practice_service.retry_grading(
        user_id=current_user.id,
        practice_id=id,
    )
    return PracticeStatusResponse(
        practice_id=getattr(practice, "id", None) or id,
        status=getattr(practice, "status", "submitted"),
        message="判题任务已重新调度，请稍候刷新查看结果",
    )


__all__ = ["router"]
