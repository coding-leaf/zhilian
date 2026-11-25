"""课程助教范围上下文：由结构化知识点生成「概览」文本与推荐话题。

纯内存拼装（不查库、不调外设），供 ``QuestionService.ask_scoped_coach`` 在
folder / material / knowledge_point 范围内为 Adaptive RAG 的 overview 与兜底提供依据。
"""

from collections.abc import Sequence
from typing import Any

from app.models.knowledge import KnowledgePoint

_MAX_OVERVIEW_CHARS = 3200
_MAX_LIST_ITEMS = 3


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


__all__ = ["build_overview_context", "pick_suggested_topics"]
