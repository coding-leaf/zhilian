"""判题自评、重判申请与作答明细查询 API 路由控制模块。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、依赖注入、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行业务逻辑判断；
- 缩写白名单仅限 8 个：api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps.auth import get_current_user
from app.api.deps.grading import get_grading_service
from app.core.errors import (
    AttemptItemNotFoundError,
    GradingExecutionError,
    GradingNotAllowedError,
)
from app.models.user import User
from app.schemas.grading import (
    AttemptGradingDetailResponse,
    RegradeRequest,
    RegradeResponse,
    SelfEvaluateRequest,
    SelfEvaluateResponse,
)
from app.services.grading import (
    GradingService,
    RegradeAttemptDTO,
    SelfEvaluateDTO,
)

router = APIRouter(tags=["grading"])


@router.post(
    "/grading/self-evaluate",
    response_model=SelfEvaluateResponse,
    status_code=status.HTTP_200_OK,
    summary="主观题用户自主评分",
)
async def self_evaluate(
    request: SelfEvaluateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    grading_service: Annotated[GradingService, Depends(get_grading_service)],
) -> SelfEvaluateResponse:
    """主观题用户自主评分提交端点。

    Args:
        request: 自评请求体模型。
        current_user: 当前已认证登录租户用户对象。
        grading_service: 判题领域编排服务。

    Returns:
        SelfEvaluateResponse: 生成并生效的自评记录响应。

    Raises:
        AttemptItemNotFoundError: 作答项不存在或跨租户越权 (404 / 40013)。
        GradingNotAllowedError: 客观题禁止自评或超出满分 (403 / 40014)。
        GradingExecutionError: 判题执行严重异常 (500 / 40015)。
    """
    try:
        evaluate_payload = SelfEvaluateDTO(
            attempt_item_id=request.attempt_item_id,
            score=request.score,
            feedback=request.feedback,
        )
        record = grading_service.self_evaluate_attempt(
            user_id=current_user.id,
            dto=evaluate_payload,
        )
        record_id = getattr(record, "id", None) or uuid.uuid4()
        grading_record_id = getattr(record, "grading_record_id", record_id)
        return SelfEvaluateResponse(
            grading_record_id=grading_record_id,
            id=getattr(record, "id", None),
            attempt_item_id=getattr(record, "attempt_item_id", request.attempt_item_id),
            score=getattr(record, "score", request.score) or 0.0,
            is_final=getattr(record, "is_final", True),
            evaluated_at=getattr(record, "evaluated_at", getattr(record, "created_at", None)),
            created_at=getattr(record, "created_at", None),
            feedback=getattr(record, "feedback", request.feedback),
            channel=getattr(record, "channel", "user_self"),
        )
    except AttemptItemNotFoundError:
        raise
    except GradingNotAllowedError as exc:
        raise GradingNotAllowedError(
            message=exc.message,
            details=exc.details,
            status_code=status.HTTP_403_FORBIDDEN,
        ) from exc
    except GradingExecutionError:
        raise


@router.post(
    "/grading/regrade",
    response_model=RegradeResponse,
    status_code=status.HTTP_200_OK,
    summary="申请重新判题",
)
async def regrade(
    request: RegradeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    grading_service: Annotated[GradingService, Depends(get_grading_service)],
) -> RegradeResponse:
    """申请主观题重新判题端点。

    Args:
        request: 重新判题请求体模型。
        current_user: 当前已认证登录租户用户对象。
        grading_service: 判题领域编排服务。

    Returns:
        RegradeResponse: 重新判题受理响应。

    Raises:
        AttemptItemNotFoundError: 作答项不存在或跨租户越权 (404 / 40013)。
        GradingNotAllowedError: 客观题或未作答题目不允许重判 (403 / 40014)。
        GradingExecutionError: 判题服务异常或未配置大模型 (500 / 40015)。
    """
    try:
        regrade_payload = RegradeAttemptDTO(
            attempt_item_id=request.attempt_item_id,
            reason=request.reason,
        )
        record = grading_service.regrade_attempt(
            user_id=current_user.id,
            dto=regrade_payload,
        )
        return RegradeResponse(
            attempt_item_id=getattr(record, "attempt_item_id", request.attempt_item_id),
            status=getattr(record, "status", "pending_regrade"),
            message="已受理重新判题申请",
            grading_record_id=getattr(record, "id", None),
        )
    except AttemptItemNotFoundError:
        raise
    except GradingNotAllowedError as exc:
        raise GradingNotAllowedError(
            message=exc.message,
            details=exc.details,
            status_code=status.HTTP_403_FORBIDDEN,
        ) from exc
    except GradingExecutionError:
        raise


@router.get(
    "/attempts/{attempt_item_id}/grading",
    response_model=AttemptGradingDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="作答题目判题明细与历史记录查询",
)
async def get_attempt_grading_detail(
    attempt_item_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    grading_service: Annotated[GradingService, Depends(get_grading_service)],
) -> AttemptGradingDetailResponse:
    """作答题目判题明细与历史记录查询端点。

    Args:
        attempt_item_id: 作答项主键标识。
        current_user: 当前已认证登录租户用户对象。
        grading_service: 判题领域编排服务。

    Returns:
        AttemptGradingDetailResponse: 包含最新生效记录与历史记录的作答判题明细。

    Raises:
        AttemptItemNotFoundError: 作答项不存在或跨租户越权 (404 / 40013)。
        GradingNotAllowedError: 判题操作不合法 (403 / 40014)。
        GradingExecutionError: 判题服务异常 (500 / 40015)。
    """
    try:
        detail_result = grading_service.get_attempt_grading_detail(
            user_id=current_user.id,
            attempt_item_id=attempt_item_id,
        )
        if isinstance(detail_result, AttemptGradingDetailResponse):
            return detail_result
        return AttemptGradingDetailResponse.model_validate(detail_result)
    except AttemptItemNotFoundError:
        raise
    except GradingNotAllowedError as exc:
        raise GradingNotAllowedError(
            message=exc.message,
            details=exc.details,
            status_code=status.HTTP_403_FORBIDDEN,
        ) from exc
    except GradingExecutionError:
        raise


__all__ = ["router"]
