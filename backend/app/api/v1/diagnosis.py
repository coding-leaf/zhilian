"""学情诊断、掌握度衰减聚合与错题闭环 API 路由控制模块。

处理学情诊断报告生成与查询、艾宾浩斯掌握度全景与单点查询、错题本检索、攻克标记与删除。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、依赖注入、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 8 个：api, id, url, ocr, llm, db, config, env；
- 绝密脱敏红线：严禁记录题干、选项、答案与用户作答原文入日志。
"""

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps.auth import get_current_user
from app.api.deps.diagnosis import get_diagnosis_service
from app.models.practice import WrongRecord
from app.models.user import User
from app.schemas.diagnosis import (
    DeleteWrongRecordResponse,
    DiagnosisReportListResponse,
    DiagnosisReportResponse,
    KnowledgeMasterySummaryResponse,
    MarkWrongRecordMasteredRequest,
    MarkWrongRecordMasteredResponse,
    UserMasteryOverviewResponse,
    WrongRecordGroupResponse,
    WrongRecordItemResponse,
    WrongRecordListResponse,
)
from app.services.diagnosis import DiagnosisService

router = APIRouter(tags=["diagnosis"])


@router.post(
    "/practices/{id}/diagnosis",
    response_model=DiagnosisReportResponse,
    status_code=status.HTTP_200_OK,
    summary="生成学情诊断报告",
)
async def generate_diagnosis_report(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
) -> DiagnosisReportResponse:
    """触发生成学情诊断报告端点。

    Args:
        id: 练习会话主键 UUID。
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。

    Returns:
        DiagnosisReportResponse: 生成或幂等命中的诊断报告实体响应。

    Raises:
        PracticeNotFoundError: 练习不存在或跨租户非法访问 (404 / 40010)。
        PracticeNotGradedError: 练习尚未全量完成判题 (400 / 40016)。
    """
    report = diagnosis_service.generate_diagnosis_report(
        user_id=current_user.id,
        practice_id=id,
    )
    if isinstance(report, DiagnosisReportResponse):
        return report
    return DiagnosisReportResponse.model_validate(report)


@router.get(
    "/practices/{id}/diagnosis",
    response_model=DiagnosisReportResponse,
    status_code=status.HTTP_200_OK,
    summary="查询练习关联的诊断报告",
)
async def get_diagnosis_report_by_practice(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
) -> DiagnosisReportResponse:
    """根据练习会话主键查询关联的学情诊断报告。

    Args:
        id: 练习会话主键 UUID。
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。

    Returns:
        DiagnosisReportResponse: 查询到的诊断报告实体响应。

    Raises:
        DiagnosisReportNotFoundError: 诊断报告不存在或无权访问 (404 / 40017)。
    """
    report = diagnosis_service.get_diagnosis_report_by_practice(
        user_id=current_user.id,
        practice_id=id,
    )
    if isinstance(report, DiagnosisReportResponse):
        return report
    return DiagnosisReportResponse.model_validate(report)


@router.get(
    "/diagnosis/reports",
    response_model=DiagnosisReportListResponse,
    status_code=status.HTTP_200_OK,
    summary="分页查询诊断报告列表",
)
async def list_diagnosis_reports(
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
    page: Annotated[int, Query(ge=1, description="分页页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页大小")] = 20,
    offset: Annotated[int | None, Query(ge=0, description="可选的分页偏移量")] = None,
    limit: Annotated[int | None, Query(ge=1, le=100, description="可选的分页条数上限")] = None,
) -> DiagnosisReportListResponse:
    """分页查询当前租户用户的历史学情诊断报告列表。

    Args:
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。
        page: 当前分页页码 (从 1 起始)。
        page_size: 每页记录数。
        offset: 可选的分页偏移量。
        limit: 可选的分页上限。

    Returns:
        DiagnosisReportListResponse: 分页诊断报告列表响应。
    """
    effective_limit = limit if limit is not None else page_size
    effective_offset = offset if offset is not None else (page - 1) * page_size

    reports = diagnosis_service.list_diagnosis_reports(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        limit=effective_limit,
        offset=effective_offset,
    )
    if isinstance(reports, DiagnosisReportListResponse):
        return reports
    items = [
        r if isinstance(r, DiagnosisReportResponse) else DiagnosisReportResponse.model_validate(r)
        for r in reports
    ]
    total_count = getattr(reports, "total", None)
    if total_count is None:
        total_count = len(items)

    return DiagnosisReportListResponse(
        items=items,
        total=total_count,
        offset=effective_offset,
        limit=effective_limit,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/diagnosis/reports/{id}",
    response_model=DiagnosisReportResponse,
    status_code=status.HTTP_200_OK,
    summary="查询诊断报告详情",
)
async def get_diagnosis_report_by_id(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
) -> DiagnosisReportResponse:
    """根据报告主键查询诊断报告详情。

    Args:
        id: 诊断报告主键 UUID。
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。

    Returns:
        DiagnosisReportResponse: 命中的诊断报告实体响应。

    Raises:
        DiagnosisReportNotFoundError: 诊断报告不存在或无权访问 (404 / 40017)。
    """
    report = diagnosis_service.get_diagnosis_report(
        user_id=current_user.id,
        report_id=id,
    )
    if isinstance(report, DiagnosisReportResponse):
        return report
    return DiagnosisReportResponse.model_validate(report)


@router.get(
    "/mastery",
    response_model=UserMasteryOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="用户全量掌握度概览",
)
@router.get(
    "/mastery/overview",
    response_model=UserMasteryOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="用户资料掌握度宏观全景",
    include_in_schema=False,
)
async def get_mastery_overview(
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
    material_id: Annotated[uuid.UUID | None, Query(description="关联学习资料标识 UUID")] = None,
) -> UserMasteryOverviewResponse:
    """获取用户掌握度宏观全景概览。

    Args:
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。
        material_id: 可选的学习资料主键 UUID。

    Returns:
        UserMasteryOverviewResponse: 包含四档统计与薄弱点清单的总览响应。
    """
    overview = diagnosis_service.get_user_mastery_overview(
        user_id=current_user.id,
        material_id=material_id,
    )
    if isinstance(overview, UserMasteryOverviewResponse):
        return overview
    return UserMasteryOverviewResponse.model_validate(overview)


@router.get(
    "/mastery/{knowledge_point_id}",
    response_model=KnowledgeMasterySummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="单知识点掌握度详情",
)
async def get_knowledge_mastery(
    knowledge_point_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
) -> KnowledgeMasterySummaryResponse:
    """查询单个知识点当前艾宾浩斯时间衰减掌握度。

    Args:
        knowledge_point_id: 知识点主键 UUID。
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。

    Returns:
        KnowledgeMasterySummaryResponse: 单知识点掌握度衰减聚合数据响应。

    Raises:
        MasteryRecordNotFoundError: 知识点尚未产生掌握度评估记录 (404 / 40018)。
    """
    summary = diagnosis_service.get_knowledge_mastery(
        user_id=current_user.id,
        knowledge_point_id=knowledge_point_id,
    )
    if isinstance(summary, KnowledgeMasterySummaryResponse):
        return summary
    return KnowledgeMasterySummaryResponse.model_validate(summary)


@router.get(
    "/wrong-records",
    response_model=WrongRecordListResponse,
    status_code=status.HTTP_200_OK,
    summary="错题本列表检索",
)
async def list_wrong_records(
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
    material_id: Annotated[uuid.UUID | None, Query(description="学习资料主键 UUID")] = None,
    folder_id: Annotated[uuid.UUID | None, Query(description="课程文件夹主键 UUID")] = None,
    unclassified: Annotated[bool, Query(description="仅未分类资料错题")] = False,
    knowledge_point_id: Annotated[uuid.UUID | None, Query(description="知识点主键 UUID")] = None,
    error_type: Annotated[str | None, Query(description="错误类型分类过滤")] = None,
    question_type: Annotated[str | None, Query(description="题目类型过滤")] = None,
    is_mastered: Annotated[bool | None, Query(description="攻克掌握布尔状态过滤")] = None,
    status: Annotated[str | None, Query(description="错题状态过滤")] = None,
    page: Annotated[int, Query(ge=1, description="分页页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 20,
    offset: Annotated[int | None, Query(ge=0, description="可选的分页偏移量")] = None,
    limit: Annotated[int | None, Query(ge=1, le=100, description="可选的分页上限")] = None,
) -> WrongRecordListResponse:
    """多维条件分页查询当前用户的错题本记录列表。

    Args:
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。
        material_id: 可选的学习资料标识过滤。
        knowledge_point_id: 可选的知识点主键过滤。
        error_type: 可选的错误类型分类过滤。
        question_type: 可选的题目类型过滤。
        is_mastered: 可选的攻克掌握状态过滤。
        status: 可选的错题状态过滤。
        page: 当前分页页码。
        page_size: 每页条数。
        offset: 可选的分页偏移量。
        limit: 可选的分页上限。

    Returns:
        WrongRecordListResponse: 包含原题快照的错题记录分页列表响应。
    """
    effective_limit = limit if limit is not None else page_size
    effective_offset = offset if offset is not None else (page - 1) * page_size

    result = diagnosis_service.list_wrong_records(
        user_id=current_user.id,
        material_id=material_id,
        folder_id=folder_id,
        unclassified=unclassified,
        status=status,
        is_mastered=is_mastered,
        knowledge_point_id=knowledge_point_id,
        error_type=error_type,
        question_type=question_type,
        page=page,
        page_size=page_size,
        limit=effective_limit,
        offset=effective_offset,
    )
    if isinstance(result, WrongRecordListResponse):
        return result

    records: list[WrongRecord] = []
    total_count: int | None = None
    if isinstance(result, tuple) and len(result) == 2:
        records = list(result[0])
        total_count = int(result[1])
    else:
        # 兼容旧契约：Service 直接返回普通列表 (含携带 total 属性的列表容器)
        legacy_records = cast("list[WrongRecord]", result)
        records = list(legacy_records)
        total_count = getattr(legacy_records, "total", None)

    items = [
        r if isinstance(r, WrongRecordItemResponse) else WrongRecordItemResponse.model_validate(r)
        for r in records
    ]
    if items:
        scopes = diagnosis_service.get_wrong_record_scopes(
            current_user.id, {item.knowledge_point_id for item in items}
        )
        if isinstance(scopes, dict):
            for item in items:
                scope = scopes.get(item.knowledge_point_id)
                if scope is not None:
                    item.material_id, item.folder_id = scope
    groups = [
        WrongRecordGroupResponse.model_validate(group)
        for group in diagnosis_service.list_wrong_record_groups(current_user.id, is_mastered)
    ]
    if total_count is None:
        total_count = len(items)

    return WrongRecordListResponse(
        items=items,
        groups=groups,
        total=total_count,
        offset=effective_offset,
        limit=effective_limit,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/wrong-records/{id}/master",
    response_model=MarkWrongRecordMasteredResponse,
    status_code=status.HTTP_200_OK,
    summary="错题攻克标记",
)
async def mark_wrong_record_mastered(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
    request: Annotated[MarkWrongRecordMasteredRequest | None, Body()] = None,
) -> MarkWrongRecordMasteredResponse:
    """手动标记或取消指定错题的已消灭/已掌握状态。

    Args:
        id: 错题记录主键 UUID。
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。
        request: 可选请求体，`is_mastered` 缺省时按 True (置为已攻克) 处理。

    Returns:
        MarkWrongRecordMasteredResponse: 标记掌握操作结果响应。

    Raises:
        WrongRecordNotFoundError: 错题记录不存在或无权访问 (404 / 40019)。
    """
    target_is_mastered = (
        request.is_mastered if request is not None and request.is_mastered is not None else True
    )
    record = diagnosis_service.mark_wrong_record_mastered(
        user_id=current_user.id,
        record_id=id,
        is_mastered=target_is_mastered,
    )
    if isinstance(record, MarkWrongRecordMasteredResponse):
        return record
    return MarkWrongRecordMasteredResponse(
        id=getattr(record, "id", id),
        is_mastered=getattr(record, "is_mastered", target_is_mastered),
        mastered_at=getattr(record, "mastered_at", None),
        message="错题已成功标记为已攻克" if target_is_mastered else "已取消该错题的攻克状态",
    )


@router.delete(
    "/wrong-records/{id}",
    response_model=DeleteWrongRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="错题删除",
)
async def delete_wrong_record(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
) -> DeleteWrongRecordResponse:
    """从错题本彻底移除错题记录。

    Args:
        id: 错题记录主键 UUID。
        current_user: 当前认证登录租户用户对象。
        diagnosis_service: 学情诊断与错题联动编排服务。

    Returns:
        DeleteWrongRecordResponse: 移除操作结果响应。

    Raises:
        WrongRecordNotFoundError: 错题记录不存在或无权访问 (404 / 40019)。
    """
    success = diagnosis_service.remove_wrong_record(
        user_id=current_user.id,
        record_id=id,
    )
    if isinstance(success, DeleteWrongRecordResponse):
        return success
    return DeleteWrongRecordResponse(
        id=id,
        success=True,
        removed=True,
        message="错题记录已成功移除",
    )


__all__ = ["router"]
