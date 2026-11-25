"""课程助教范围上下文：由结构化知识点生成「概览」文本与推荐话题。

纯内存拼装（不查库、不调外设），供 ``QuestionService.ask_scoped_coach`` 在
folder / material / knowledge_point 范围内为 Adaptive RAG 的 overview 与兜底提供依据。
"""

from collections.abc import Sequence
from typing import Any

from app.models.knowledge import KnowledgePoint
from app.models.material import MaterialFolder
from app.models.practice import MasteryRecord

_MAX_OVERVIEW_CHARS = 3200
_MAX_GLOBAL_CHARS = 2800
_MAX_LIST_ITEMS = 3
_WEAK_MASTERY_THRESHOLD = 0.60
_DEFAULT_WEAK_LIMIT = 5


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _format_point(point: KnowledgePoint) -> str:
    structured = point.structured_content if isinstance(point.structured_content, dict) else {}
    summary = str(structured.get("core_summary") or point.description or "").strip()
    parts = [f"{point.name}：{summary}" if summary else point.name]
    takeaways = _as_text_list(structured.get("key_takeaways"))[:_MAX_LIST_ITEMS]
    if takeaways:
        parts.append("要点：" + "；".join(takeaways))
    formulas = _as_text_list(structured.get("key_formulas"))[:_MAX_LIST_ITEMS]
    if formulas:
        parts.append("公式：" + "；".join(formulas))
    derivations = _as_text_list(structured.get("derivation_steps"))[:_MAX_LIST_ITEMS]
    if derivations:
        parts.append("步骤：" + " → ".join(derivations))
    mistakes = _as_text_list(structured.get("common_mistakes"))[:_MAX_LIST_ITEMS]
    if mistakes:
        parts.append("易错：" + "；".join(mistakes))
    indent = "  " * min(max(point.level - 1, 0), 2)
    return f"{indent}- " + " | ".join(parts)


def build_overview_context(
    points: Sequence[KnowledgePoint], *, max_chars: int = _MAX_OVERVIEW_CHARS
) -> str | None:
    """把知识点（含结构化内容）渲染成层级化概览文本；无知识点返回 None。"""
    lines: list[str] = []
    total = 0
    for point in points:
        line = _format_point(point)
        if total + len(line) + 1 > max_chars:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else None


def pick_suggested_topics(points: Sequence[KnowledgePoint], *, limit: int = 3) -> list[str]:
    """选取靠前的知识点名称作为寒暄/兜底时的可问方向。"""
    seen: list[str] = []
    for point in points:
        name = point.name.strip()
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            break
    return seen


def _rank_weak_records(
    points: Sequence[KnowledgePoint],
    mastery_records: Sequence[MasteryRecord],
    *,
    limit: int = _DEFAULT_WEAK_LIMIT,
) -> list[tuple[KnowledgePoint, MasteryRecord]]:
    point_by_id = {point.id: point for point in points}
    weak_pairs = [
        (point_by_id[record.knowledge_point_id], record)
        for record in mastery_records
        if record.knowledge_point_id in point_by_id
        and record.mastery_score < _WEAK_MASTERY_THRESHOLD
    ]
    weak_pairs.sort(key=lambda pair: (pair[1].mastery_score, -pair[1].practice_count))
    return weak_pairs[:limit]


def pick_global_suggested_topics(
    points: Sequence[KnowledgePoint],
    mastery_records: Sequence[MasteryRecord],
    *,
    limit: int = 3,
) -> list[str]:
    """全局模式下优先推荐薄弱考点名称，其次补充前序核心考点。"""
    seen: list[str] = []
    for point, _ in _rank_weak_records(points, mastery_records, limit=_DEFAULT_WEAK_LIMIT):
        name = point.name.strip()
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            return seen
    for point in points:
        name = point.name.strip()
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            break
    return seen


def build_global_study_context(
    *,
    folders: Sequence[MaterialFolder],
    ready_materials_count: int,
    points: Sequence[KnowledgePoint],
    mastery_records: Sequence[MasteryRecord],
    max_chars: int = _MAX_GLOBAL_CHARS,
    weak_limit: int = _DEFAULT_WEAK_LIMIT,
) -> str:
    """汇总全局学习画像：就绪资料数、考点总数、课程清单与薄弱考点 Top 5。"""
    lines = [
        f"【个人学习概览】未归档课程 {len(folders)} 门，"
        f"已就绪资料 {ready_materials_count} 份，核心考点共 {len(points)} 个。"
    ]
    if folders:
        folder_names = "、".join(folder.name for folder in folders[:10])
        lines.append(f"课程清单：{folder_names}")

    weak_pairs = _rank_weak_records(points, mastery_records, limit=weak_limit)
    if weak_pairs:
        lines.append(f"薄弱考点 Top {len(weak_pairs)}（掌握度由低到高）：")
        for point, record in weak_pairs:
            pct = round(record.mastery_score * 100)
            lines.append(
                f"- {point.name}（掌握度 {pct}%，练习 {record.practice_count} 次/"
                f"答对 {record.correct_count} 次）"
            )
    elif points:
        sample_names = "、".join(pick_suggested_topics(points, limit=8))
        lines.append(f"暂无薄弱考点记录；代表性考点：{sample_names}")
    else:
        lines.append("当前资料库暂无已解析资料与练习记录。")

    rendered: list[str] = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > max_chars:
            break
        rendered.append(line)
        total += len(line) + 1
    return "\n".join(rendered)


__all__ = [
    "build_global_study_context",
    "build_overview_context",
    "pick_global_suggested_topics",
    "pick_suggested_topics",
]
