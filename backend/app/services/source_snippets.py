"""原文来源切片投影的共享装配实现。

题目侧（``QuestionService``）与练习侧（``PracticeService``）**共用这一份**装配逻辑：
投影形状与页码回退规则只在此处定义，禁止任何一侧另写副本——否则同一份来源模型会在
两个业务域各自漂移（见 ``quality-guidelines`` 的「原文装配只有一个实现」与
``code-reuse-thinking-guide`` 的「我是不是在从另一个文件抄代码」）。
"""

import uuid
from collections.abc import Iterable

from app.models.material import MaterialSnippet
from app.repositories.material import MaterialRepository
from app.schemas.material import SourceSnippetDTO


def resolve_snippet_page_index(snippet: MaterialSnippet) -> int:
    """解析切片页码 (优先映射列，回退 ``source_info`` 元数据)。

    Args:
        snippet: 切片 ORM 实体。

    Returns:
        int: 从 1 起算的页码；两处来源都缺失或非法时回退为 1。
    """
    page_index = getattr(snippet, "page_index", None)
    if isinstance(page_index, int) and page_index >= 1:
        return page_index
    source_info = getattr(snippet, "source_info", None)
    if isinstance(source_info, dict):
        candidate = source_info.get("page_number", source_info.get("page_index"))
        if isinstance(candidate, int) and candidate >= 1:
            return candidate
    return 1


def build_source_snippet_map(
    material_repo: MaterialRepository,
    snippet_ids: Iterable[uuid.UUID],
    user_id: uuid.UUID,
) -> dict[uuid.UUID, SourceSnippetDTO]:
    """按切片主键集合批量装载原文切片投影。

    单次 ``IN`` 查询完成装配（禁 N+1），查询强制带 ``user_id`` 租户过滤——
    他人切片查不到即不返回，不会经响应泄漏；切片缺失时映射中无该键，
    调用方据此返回 ``None``，由前端渲染空态。

    Args:
        material_repo: 资料仓储实例 (提供批量 + 租户过滤的切片查询)。
        snippet_ids: 目标切片主键集合 (可含 ``None``，会被忽略)。
        user_id: 租户用户标识。

    Returns:
        dict[uuid.UUID, SourceSnippetDTO]: 切片主键到投影对象的映射；集合为空时返回空字典。
    """
    resolved_ids = {snippet_id for snippet_id in snippet_ids if snippet_id is not None}
    if not resolved_ids:
        return {}

    return {
        snippet.id: SourceSnippetDTO(
            id=snippet.id,
            chapter_title=snippet.chapter_title or "",
            page_index=resolve_snippet_page_index(snippet),
            snippet_content=snippet.content or "",
        )
        for snippet in material_repo.list_snippets_by_ids(sorted(resolved_ids), user_id)
    }
