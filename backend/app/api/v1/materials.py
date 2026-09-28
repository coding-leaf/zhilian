"""学习资料管理与解析调度 API 路由控制模块。

处理学习资料文件上传、状态查询与生命周期编排。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

import logging
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
    Request,
    UploadFile,
    status,
)

from app.api.deps.auth import get_current_user
from app.api.deps.folder import get_folder_service
from app.api.deps.material import get_material_service
from app.container import AppContainer
from app.core.errors import MaterialInvalidError
from app.core.security import generate_user_ref
from app.models.material import MaterialStatus
from app.models.user import User
from app.schemas.material import (
    MaterialDeleteResponse,
    MaterialDetailResponse,
    MaterialFolderMoveRequest,
    MaterialListItem,
    MaterialListResponse,
    MaterialOCRPageItem,
    MaterialOCRPagesResponse,
    MaterialParseRequest,
    MaterialParseResponse,
    MaterialReshootResponse,
    MaterialUploadResponse,
    MaterialVersionItem,
    MaterialVersionListResponse,
)
from app.services.folder import FolderService
from app.services.material import MAX_FILE_SIZES, MaterialService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/materials", tags=["materials"])

# 依据：全局单文件上传上限 = 各格式上限的最大值 (20MB)，另加 multipart 信封容差；
# 攻击者可借超限请求体放大内存，故在读取前先校验 Content-Length，读取时再流式累计。
MAX_UPLOAD_BYTES: int = max(MAX_FILE_SIZES.values())
CONTENT_LENGTH_TOLERANCE_BYTES: int = 512 * 1024
_UPLOAD_CHUNK_BYTES: int = 64 * 1024
_HTTP_413_PAYLOAD_TOO_LARGE: int = 413


async def _read_upload_content_guarded(file: UploadFile, request: Request) -> bytes:
    """在读取请求体之前与读取过程中双重执行体积门禁，杜绝内存放大 DoS。

    先校验 ``Content-Length`` 声明体积，超限立即拒绝且不读取任何字节；
    再按 64KB 分块流式读取并累计字节数，一旦超过全局上限立刻中止。

    Args:
        file: 上传文件流对象。
        request: 当前 HTTP 请求，用于读取 Content-Length 请求头。

    Returns:
        bytes: 校验通过后的完整文件内容。

    Raises:
        MaterialInvalidError: 声明体积或实际读取体积超过全局单文件上限 (HTTP 413)。
    """
    max_bytes = MAX_UPLOAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_len = int(declared)
        except ValueError:
            declared_len = -1
        if declared_len > max_bytes + CONTENT_LENGTH_TOLERANCE_BYTES:
            raise MaterialInvalidError(
                f"上传请求体积过大，最大允许 {max_bytes // (1024 * 1024)}MB",
                status_code=_HTTP_413_PAYLOAD_TOO_LARGE,
                details={"declared_bytes": declared_len, "max_bytes": max_bytes},
            )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise MaterialInvalidError(
                f"上传文件体积过大，最大允许 {max_bytes // (1024 * 1024)}MB",
                status_code=_HTTP_413_PAYLOAD_TOO_LARGE,
                details={"actual_bytes": total, "max_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_folder_filter(folder_id: str | None) -> tuple[uuid.UUID | None, bool]:
    """解析课程过滤查询参数为 (课程主键, 是否未分类) 二元组。

    ``__none__`` 表示仅返回未分类资料；合法的 UUID 字符串表示按课程过滤；
    缺省或空串表示不按课程限定；非法格式抛出参数校验异常。

    Args:
        folder_id: 原始课程过滤查询参数。

    Returns:
        tuple[uuid.UUID | None, bool]: (课程主键, 是否未分类)。

    Raises:
        MaterialInvalidError: 课程过滤参数格式非法 (HTTP 400)。
    """
    if folder_id is None:
        return None, False
    trimmed = folder_id.strip()
    if not trimmed:
        return None, False
    if trimmed == "__none__":
        return None, True
    try:
        return uuid.UUID(trimmed), False
    except ValueError as exc:
        raise MaterialInvalidError(
            "课程过滤参数格式非法",
            details={"folder_id": trimmed},
        ) from exc


def run_material_pipeline_background(
    container: AppContainer,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """后台异步任务：以独立数据库 Session 生命周期执行资料解析与知识树抽取闭环。

    严格遵循 Session 隔离铁律：
    严禁复用请求级 Session；显式使用 container.get_session() 开启全新独立会话。

    Args:
        container: 全局应用装配容器。
        material_id: 资料主键。
        version_id: 版本主键。
        user_id: 租户用户主键。
    """
    user_ref = generate_user_ref(user_id)
    logger.info(
        "starting background material parsing",
        extra={
            "user_ref": user_ref,
            "target_id": str(material_id),
            "error_code": 0,
        },
    )
    try:
        with container.get_session() as session:
            material_service = container.create_material_service(session=session)
            material_service.parse_material_pipeline(
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
            )
    except Exception as exc:
        logger.error(
            "background material parsing failed",
            extra={
                "user_ref": user_ref,
                "target_id": str(material_id),
                "error_code": 50001,
                "details": str(exc),
            },
        )


run_parse_material_background = run_material_pipeline_background


@router.post(
    "/upload",
    response_model=MaterialUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传并创建学习资料",
)
async def upload_material(
    request: Request,
    file: Annotated[UploadFile, File(description="待解析学习资料文件二进制流")],
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    title: Annotated[str | None, Form(description="资料展示标题 (为空时使用文件名)")] = None,
    source_type: Annotated[str, Form(description="资料来源渠道 (local/wechat)")] = "local",
    folder_id: Annotated[uuid.UUID | None, Form(description="归属课程文件夹标识 (缺省=未分类)")] = (
        None
    ),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MaterialUploadResponse:
    """上传文件并创建待解析资料，不自动调度解析。

    读取文件流并委托 MaterialService 执行格式魔数校验与持久化。
    读取前先做 Content-Length 与流式累计双重体积门禁，防范内存放大 DoS。

    Args:
        request: 当前 HTTP 请求对象 (体积门禁读取 Content-Length)。
        file: 客户端上传的文件流对象。
        title: 可选的资料展示标题。
        source_type: 导入来源渠道 (local/wechat)。
        folder_id: 可选的归属课程文件夹标识。
        idempotency_key: 可选的请求防重幂等键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialUploadResponse: 创建就绪的资料与版本初始元数据。
    """
    content = await _read_upload_content_guarded(file, request)
    material, version = material_service.import_material_file(
        user_id=user.id,
        file_content=content,
        filename=file.filename,
        title=title,
        source_type=source_type,
        idempotency_key=idempotency_key,
        folder_id=folder_id,
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
    folder_id: Annotated[
        str | None,
        Query(description="课程过滤：课程 UUID 或未分类占位符 __none__"),
    ] = None,
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
        folder_id: 可选课程过滤器（UUID 或 __none__ 未分类）。

    Returns:
        MaterialListResponse: 包含资料列表与分页总数的分页响应。
    """
    calc_limit = limit if limit is not None else page_size
    calc_offset = offset if offset is not None else (page - 1) * calc_limit
    calc_page = (calc_offset // calc_limit) + 1 if limit is not None else page

    cleaned_status: str | None = None
    if status_filter:
        trimmed = status_filter.strip().lower()
        # 同时接纳资料主状态与前端语义别名（completed/retake_required），
        # 仅将空串、占位符（all/undefined/null）等伪状态清洗为不加过滤。
        valid_statuses = {s.value for s in MaterialStatus} | {"completed", "retake_required"}
        if trimmed in valid_statuses:
            cleaned_status = trimmed

    resolved_folder_id, unclassified = _parse_folder_filter(folder_id)

    items, total = material_service.list_materials(
        user_id=user.id,
        keyword=keyword,
        status=cleaned_status,
        page=calc_page,
        page_size=calc_limit,
        limit=calc_limit,
        offset=calc_offset,
        folder_id=resolved_folder_id,
        unclassified=unclassified,
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
                folder_id=item.folder_id,
                parse_status=getattr(item, "parse_status", None),
                progress_percentage=getattr(item, "progress_percentage", None),
                key_points_count=getattr(item, "key_points_count", None),
                page_count=getattr(item, "page_count", None),
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
        folder_id=material.folder_id,
        parse_status=getattr(material, "parse_status", None),
        progress_percentage=getattr(material, "progress_percentage", None),
        versions_count=versions_count,
        key_points_count=getattr(material, "key_points_count", None),
        page_count=getattr(material, "page_count", None),
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.get(
    "/{material_id}/ocr-pages",
    response_model=MaterialOCRPagesResponse,
    status_code=status.HTTP_200_OK,
    summary="查询资料页级 OCR 质检记录",
)
async def list_material_ocr_pages(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    only_unqualified: Annotated[bool, Query(description="是否仅返回未达标页面")] = False,
) -> MaterialOCRPagesResponse:
    """查询指定资料当前激活（或最新）版本的页级 OCR 质检记录。

    前端「待重拍」入口据此获取真实的不合格页面清单并驱动逐页重拍。

    Args:
        material_id: 目标资料主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。
        only_unqualified: 是否仅返回未达标页面。

    Returns:
        MaterialOCRPagesResponse: 版本标识与页级质检记录列表。
    """
    version_id, pages = material_service.list_ocr_pages(
        material_id=material_id,
        user_id=user.id,
        only_unqualified=only_unqualified,
    )
    return MaterialOCRPagesResponse(
        material_id=material_id,
        version_id=version_id,
        items=[
            MaterialOCRPageItem(
                page_number=page.page_number,
                is_qualified=page.is_qualified,
                reshoot_count=page.reshoot_count,
                unqualified_reason=page.unqualified_reason,
            )
            for page in pages
        ],
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
        folder_id=material.folder_id,
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


@router.post(
    "/{material_id}/retry",
    response_model=MaterialDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="一键重试学习资料解析流水线",
)
async def retry_material_pipeline(
    material_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
) -> MaterialDetailResponse:
    """重试解析失败的学习资料流水线。

    校验租户归属，将最新版本的状态由 FAILED 重置为 QUEUED，清空失败原因，
    将资料状态重置为 PENDING，并重新拉起异步流水线。

    Args:
        material_id: 资料主键。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。

    Returns:
        MaterialDetailResponse: 重新进入就绪队列的资料详情。
    """
    material, version = material_service.retry_material_pipeline(
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
        current_version_id=material.current_version_id or version.id,
        folder_id=material.folder_id,
        versions_count=versions_count,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@router.patch(
    "/{material_id}/folder",
    response_model=MaterialDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="移动资料归属课程",
)
async def move_material_folder(
    material_id: uuid.UUID,
    payload: MaterialFolderMoveRequest,
    user: Annotated[User, Depends(get_current_user)],
    material_service: Annotated[MaterialService, Depends(get_material_service)],
    folder_service: Annotated[FolderService, Depends(get_folder_service)],
) -> MaterialDetailResponse:
    """移动指定资料的归属课程（folder_id 为 null 表示移回未分类）。

    目标课程必须归属当前用户且未归档，否则返回 4xx。

    Args:
        material_id: 资料主键。
        payload: 移动请求体（目标课程标识，null 表示未分类）。
        user: 当前登录租户用户对象。
        material_service: 资料领域编排服务。
        folder_service: 课程文件夹领域编排服务。

    Returns:
        MaterialDetailResponse: 移动后的资料详情。
    """
    folder_service.move_material(
        user_id=user.id,
        material_id=material_id,
        folder_id=payload.folder_id,
    )
    material = material_service.get_material_detail(material_id=material_id, user_id=user.id)
    versions_count = getattr(material, "versions_count", None)
    if versions_count is None:
        versions_count = len(getattr(material, "versions", []))

    return MaterialDetailResponse(
        id=material.id,
        title=material.title,
        file_format=material.file_format,
        file_size=material.file_size,
        source_type=material.source_type,
        status=material.status,
        current_version_id=material.current_version_id,
        folder_id=material.folder_id,
        parse_status=getattr(material, "parse_status", None),
        progress_percentage=getattr(material, "progress_percentage", None),
        versions_count=versions_count,
        key_points_count=getattr(material, "key_points_count", None),
        page_count=getattr(material, "page_count", None),
        created_at=material.created_at,
        updated_at=material.updated_at,
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
    "list_material_ocr_pages",
    "list_material_versions",
    "list_materials",
    "move_material_folder",
    "reshoot_material_page",
    "retry_material_pipeline",
    "router",
    "run_material_pipeline_background",
    "run_parse_material_background",
    "soft_delete_material",
    "switch_material_version",
    "trigger_material_parse",
    "upload_material",
]
