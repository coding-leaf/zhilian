"""_coach_context 纯拼装函数测试：概览文本与推荐话题（无数据库）。"""

import uuid
from typing import Any

from app.models.knowledge import KnowledgePoint
from app.services._coach_context import build_overview_context, pick_suggested_topics


def point(
    name: str,
    *,
    structured: dict[str, Any] | None = None,
    description: str = "",
    level: int = 1,
) -> KnowledgePoint:
    return KnowledgePoint(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        name=name,
        description=description,
        structured_content=structured,
        level=level,
        sort_order=0,
        batch_id="b",
    )


class TestBuildOverviewContext:
    def test_empty_returns_none(self) -> None:
        assert build_overview_context([]) is None

    def test_structured_content_rendered(self) -> None:
        text = build_overview_context(
            [
                point(
                    "牛顿第二定律",
                    structured={
                        "core_summary": "合力等于质量乘加速度",
                        "key_takeaways": ["矢量性", "瞬时性", "同体性", "被截断的第四条"],
                        "key_formulas": ["$F=ma$"],
                    },
                )
            ]
        )
        assert text is not None
        assert text.startswith("- 牛顿第二定律：合力等于质量乘加速度")
        assert "要点：矢量性；瞬时性；同体性" in text
        assert "第四条" not in text  # 每类最多 3 项
        assert "公式：$F=ma$" in text

    def test_falls_back_to_description_then_name(self) -> None:
        text = build_overview_context(
            [point("A", description="A 的描述"), point("B", structured={"core_summary": ""})]
        )
        assert text is not None
        lines = text.splitlines()
        assert lines[0] == "- A：A 的描述"
        assert lines[1] == "- B"

    def test_string_and_garbage_takeaways(self) -> None:
        text = build_overview_context(
            [point("X", structured={"key_takeaways": " 单条要点 ", "key_formulas": 123})]
        )
        assert text is not None
        assert "要点：单条要点" in text
        assert "公式" not in text

    def test_non_dict_structured_content_ignored(self) -> None:
        bad = point("Y", description="描述")
        bad.structured_content = ["not", "a", "dict"]  # type: ignore[assignment]
        assert build_overview_context([bad]) == "- Y：描述"

    def test_indent_by_level_capped_at_two_levels(self) -> None:
        text = build_overview_context(
            [point("L1", level=1), point("L2", level=2), point("L3", level=3), point("L9", level=9)]
        )
        assert text is not None
        lines = text.splitlines()
        assert lines[0] == "- L1"
        assert lines[1] == "  - L2"
        assert lines[2] == "    - L3"
        assert lines[3] == "    - L9"

    def test_max_chars_truncates_on_line_boundary(self) -> None:
        points = [point(f"知识点{i}", description="描" * 30) for i in range(10)]
        text = build_overview_context(points, max_chars=100)
        assert text is not None
        assert len(text) <= 100
        lines = text.splitlines()
        assert 0 < len(lines) < 10
        assert all(line.startswith("- 知识点") for line in lines)  # 不切断单行

    def test_first_line_longer_than_budget_yields_none(self) -> None:
        assert build_overview_context([point("超长", description="长" * 50)], max_chars=10) is None


class TestPickSuggestedTopics:
    def test_dedup_strip_and_limit(self) -> None:
        topics = pick_suggested_topics(
            [point(" A "), point("A"), point(""), point("  "), point("B"), point("C"), point("D")]
        )
        assert topics == ["A", "B", "C"]

    def test_custom_limit_and_empty(self) -> None:
        assert pick_suggested_topics([point("A"), point("B")], limit=1) == ["A"]
        assert pick_suggested_topics([]) == []
