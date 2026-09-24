"""学习资料管理与解析调度 API 路由控制模块。

处理学习资料文件上传、状态查询与生命周期编排。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    Query,
    UploadFile,
    status,
)

from app.api.deps.auth import get_current_user
from app.api.deps.material import get_material_service
from app.models.user import User
from app.schemas.material import (
    MaterialDeleteResponse,
    MaterialDetailResponse,
    MaterialListItem,
    MaterialListResponse,
    MaterialParseRequest,
    MaterialParseResponse,
    MaterialReshootResponse,
    MaterialUploadResponse,
    MaterialVersionItem,
    MaterialVersionListResponse,
)
from app.services.material import MaterialService

router = APIRouter(prefix="/materials", tags=["materials"])


@router.post(
    "/upload",
    response_model=MaterialUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传并创建学习资料",
)
async def upload_material(
    file: Annotated[UploadFile, File(description="待解析学习资料文件二进制流")],
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    title: Annotated[str | None, Form(description="资料展示标题 (为空时使用文件名)")] = None,
    source_type: Annotated[str, Form(description="资料来源渠道 (local/wechat)")] = "local",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MaterialUploadResponse:
    """上传文件创建学习资料并触发异步解析流水线。

    读取文件流并委托 MaterialService 执行格式魔数校验、内容查重秒传与入队调度。

    Args:
        file: 客户端上传的文件流对象。
        title: 可选的资料展示标题。
        source_type: 导入来源渠道 (local/wechat)。
        idempotency_key: 可选的请求防重幂等键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialUploadResponse: 创建就绪的资料与版本初始元数据。
    """
    content = await file.read()
    material, version = material_service.import_material_file(
        user_id=user.id,
        file_content=content,
        filename=file.filename,
        title=title,
        source_type=source_type,
        idempotency_key=idempotency_key,
    )
    return MaterialUploadResponse(
        id=material.id,
        version_id=version.id,
        title=material.title,
        file_format=material.file_format,
        file_size=material.file_size,
        source_type=material.source_type,
        status=material.status,
        created_at=material.created_at,
    )


@router.get(
    "",
    response_model=MaterialListResponse,
    status_code=status.HTTP_200_OK,
    summary="分页检索资料列表",
)
async def list_materials(
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    page: Annotated[int, Query(ge=1, description="当前页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="单页容量")] = 20,
    limit: Annotated[
        int | None, Query(ge=1, le=100, description="单页容量限制 (兼容游标分页)")
    ] = None,
    offset: Annotated[int | None, Query(ge=0, description="游标偏移量 (兼容游标分页)")] = None,
    keyword: Annotated[str | None, Query(max_length=100, description="标题模糊检索词")] = None,
    status_filter: Annotated[str | None, Query(alias="status", description="状态筛选")] = None,
) -> MaterialListResponse:
    """分页检索当前租户用户的学习资料列表，支持标题模糊检索与状态筛选。

    Args:
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。
        page: 当前页码 (从 1 开始)。
        page_size: 单页容量限制。
        limit: 可选的单页容量限制（兼容游标分页）。
        offset: 可选的分页游标偏移量（兼容游标分页）。
        keyword: 可选标题模糊检索关键词。
        status_filter: 可选资料生命周期状态。

    Returns:
        MaterialListResponse: 包含资料列表与分页总数的分页响应。
    """
    calc_limit = limit if limit is not None else page_size
    calc_offset = offset if offset is not None else (page - 1) * calc_limit
    calc_page = (calc_offset // calc_limit) + 1 if limit is not None else page

    items, total = material_service.list_materials(
        user_id=user.id,
        keyword=keyword,
        status=status_filter,
        page=calc_page,
        page_size=calc_limit,
        limit=calc_limit,
        offset=calc_offset,
    )
    return MaterialListResponse(
        items=[
            MaterialListItem(
                id=item.id,
                title=item.title,
                file_format=item.file_format,
                file_size=item.file_size,
                source_type=item.source_type,
                status=item.status,
                current_version_id=item.current_version_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        total=total,
        limit=calc_limit,
        offset=calc_offset,
    )


@router.get(
    "/{material_id}",
    response_model=MaterialDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="获取指定学习资料详情",
)
async def get_material_detail(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
) -> MaterialDetailResponse:
    """获取指定学习资料详情与激活版本信息，严格保证多租户隔离。

    委托 MaterialService 查询资料，若非本用户资源或不存在则抛出统一异常。

    Args:
        material_id: 目标资料 UUIDv4 主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialDetailResponse: 资料详细元数据与版本统计信息。
    """
    material = material_service.get_material_detail(
        material_id=material_id,
        user_id=user.id,
    )
    versions_count = getattr(material, "versions_count", None)
    if versions_count is None:
        versions = getattr(material, "versions", [])
        versions_count = len(versions)

    return MaterialDetailResponse(
        id=material.id,
        title=material.title,
        file_format=material.file_format,
        file_size=material.file_size,
        source_type=material.source_type,
        status=material.status,
        current_version_id=material.current_version_id,
        versions_count=versions_count,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.post(
    "/{material_id}/parse",
    response_model=MaterialParseResponse,
    status_code=status.HTTP_200_OK,
    summary="触发或重新调度资料解析流水线",
)
async def trigger_material_parse(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    payload: Annotated[MaterialParseRequest | None, Body()] = None,
) -> MaterialParseResponse:
    """触发指定资料及版本的文本抽取、质量评估与切片向量化流水线。

    Args:
        material_id: 资料主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。
        payload: 解析调度参数配置。

    Returns:
        MaterialParseResponse: 调度入队或同步完成结果。
    """
    request_dto = payload or MaterialParseRequest()
    version = material_service.trigger_parse(
        user_id=user.id,
        material_id=material_id,
        version_id=request_dto.version_id,
        sync=request_dto.sync,
    )
    message = "解析流水线同步执行完成" if request_dto.sync else "解析流水线任务已加入队列"
    return MaterialParseResponse(
        material_id=version.material_id,
        version_id=version.id,
        parse_status=version.parse_status,
        is_active=version.is_active,
        message=message,
    )


@router.get(
    "/{material_id}/versions",
    response_model=MaterialVersionListResponse,
    status_code=status.HTTP_200_OK,
    summary="查询资料历史版本列表",
)
async def list_material_versions(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
) -> MaterialVersionListResponse:
    """获取指定资料的所有不可变历史版本列表，按版本号倒序展示。

    Args:
        material_id: 目标资料主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialVersionListResponse: 包含各版本解析状态与散列摘要的列表。
    """
    versions = material_service.list_material_versions(
        user_id=user.id,
        material_id=material_id,
    )
    return MaterialVersionListResponse(
        material_id=material_id,
        versions=[
            MaterialVersionItem(
                id=v.id,
                material_id=v.material_id,
                version_number=v.version_number,
                parse_status=v.parse_status,
                content_hash=v.content_hash,
                is_active=v.is_active,
                created_at=v.created_at,
            )
            for v in versions
        ],
    )


@router.post(
    "/{material_id}/versions/{version_id}/switch",
    response_model=MaterialDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="切换当前激活版本",
)
async def switch_material_version(
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
) -> MaterialDetailResponse:
    """切换指定资料的当前激活版本，目标版本必须处于 ready 状态。

    Args:
        material_id: 资料主键。
        version_id: 待激活的版本主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialDetailResponse: 切换激活版本后的最新资料详情。
    """
    material = material_service.switch_material_version(
        user_id=user.id,
        material_id=material_id,
        version_id=version_id,
    )
    versions_count = getattr(material, "versions_count", None)
    if versions_count is None:
        versions = getattr(material, "versions", [])
        versions_count = len(versions)

    return MaterialDetailResponse(
        id=material.id,
        title=material.title,
        file_format=material.file_format,
        file_size=material.file_size,
        source_type=material.source_type,
        status=material.status,
        current_version_id=material.current_version_id,
        versions_count=versions_count,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.post(
    "/{material_id}/reshoot",
    response_model=MaterialReshootResponse,
    status_code=status.HTTP_200_OK,
    summary="就地重拍替换指定页面图片并重检",
)
async def reshoot_material_page(
    material_id: uuid.UUID,
    page_index: Annotated[int, Form(ge=1, description="重拍目标页码序号 (从 1 开始)")],
    file: Annotated[UploadFile, File(description="重新拍摄的高清图片数据流")],
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    version_id: Annotated[uuid.UUID | None, Form(description="可选指定版本标识")] = None,
) -> MaterialReshootResponse:
    """上传重新拍摄的单页高清图片，替换原页面并重新触发质检门禁。

    单页累计重拍次数达到 3 次上限且仍未达标时触发熔断。

    Args:
        material_id: 资料主键。
        page_index: 重拍的目标页码序号。
        file: 重新拍摄的图片文件二进制流。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。
        version_id: 可选指定所属版本主键。

    Returns:
        MaterialReshootResponse: 单页重检达标状态与累计重拍次数。
    """
    content = await file.read()
    page = material_service.reshoot_material_page(
        user_id=user.id,
        material_id=material_id,
        page_index=page_index,
        file_content=content,
        version_id=version_id,
    )

    ver_parse_status = "ready" if page.is_qualified else "failed"
    if hasattr(page, "version") and page.version is not None:
        ver_parse_status = getattr(page.version, "parse_status", ver_parse_status)

    page_number = getattr(page, "page_number", page_index)
    return MaterialReshootResponse(
        material_id=page.material_id,
        version_id=page.version_id,
        page_index=page_number,
        is_qualified=page.is_qualified,
        reshoot_count=page.reshoot_count,
        parse_status=ver_parse_status,
        unqualified_reason=page.unqualified_reason,
    )


@router.delete(
    "/{material_id}/hard",
    response_model=MaterialDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="物理级联销毁资料及其关联资源",
)
async def hard_delete_material(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    permanent: Annotated[bool, Query(description="物理级联销毁二次确认标记")] = True,
) -> MaterialDeleteResponse:
    """物理级联硬删除资料，清理数据库记录及对象存储文件。

    Args:
        material_id: 目标资料主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。
        permanent: 二次确认标记。

    Returns:
        MaterialDeleteResponse: 销毁完成反馈信息。
    """
    material_service.hard_delete_material(
        user_id=user.id,
        material_id=material_id,
    )
    return MaterialDeleteResponse(
        material_id=material_id,
        is_deleted=True,
        permanent=permanent,
        message="资料及历史版本与切片已物理级联销毁",
    )


@router.delete(
    "/{material_id}",
    response_model=MaterialDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="软删除学习资料 (移至回收站)",
)
async def soft_delete_material(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
) -> MaterialDeleteResponse:
    """软删除指定学习资料，将资料标记为回收站状态，保留历史答题记录。

    Args:
        material_id: 目标资料主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialDeleteResponse: 软删除完成反馈信息。
    """
    material_service.soft_delete_material(
        user_id=user.id,
        material_id=material_id,
    )
    return MaterialDeleteResponse(
        material_id=material_id,
        is_deleted=True,
        permanent=False,
        message="资料已移至回收站",
    )


__all__ = [
    "get_material_detail",
    "hard_delete_material",
    "list_material_versions",
    "list_materials",
    "reshoot_material_page",
    "router",
    "soft_delete_material",
    "switch_material_version",
    "trigger_material_parse",
    "upload_material",
]
