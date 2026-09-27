"""Unit tests for QuestionService in app/services/question.py.

Verifies:
1. Pure helpers:
   - aggregate_snippet_context: Top 4 limit, max_chars 2400 truncation, empty handling.
   - build_generation_prompt: Prompt formatting, feedback injection.
   - convert_llm_items_to_candidates: Data mapping, source snippet index clamping.
2. Retrieval before generation gate (FR-21):
   - MissingSourceSnippetError (40003, 400) when snippets empty or max similarity < 0.35.
3. Pre-condition validations:
   - MaterialNotFoundError (40004) when material does not exist or user mismatch.
   - KnowledgeNotFoundError (40007) when knowledge point does not exist or mismatch.
4. Successful generation:
   - 7 question types (SINGLE_CHOICE, MULTIPLE_CHOICE, TRUE_FALSE, FILL_IN_BLANK,
     TERM_EXPLANATION, SHORT_ANSWER, CASE_ANALYSIS) with accurate source snippet tracking.
   - 1024-dim stem vectorization and pure quality check filtering.
5. Quality check failure and retry loop:
   - Defective questions caught by pure quality check (NO_SOURCE, DUPLICATE, etc.).
   - Feedback adapted and retry succeeds.
   - Retries exhausted (max_retries reached): pending_review status assigned.
6. Question CRUD and audit logs:
   - get_question: success & QuestionNotFoundError.
   - update_question: success with QuestionAuditLog & QuestionNotFoundError.
   - delete_question: soft delete with QuestionAuditLog & QuestionNotFoundError.
7. Atomic transaction and tenant isolation:
   - Rollback on database failure.
   - Strict multi-tenant isolation.
"""

import uuid
from collections.abc import Generator, Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    KnowledgeNotFoundError,
    MaterialNotFoundError,
    MissingSourceSnippetError,
    QuestionNotFoundError,
)
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.protocol import SearchSnippetCandidate
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.models.question import (
    AuditAction,
    Question,
    QuestionQualityCheck,
    QuestionStatus,
    QuestionType,
)
from app.services.question import (
    GenerateQuestionsOptions,
    LLMGeneratedQuestionItem,
    LLMGradingPointItem,
    LLMGradingRubric,
    LLMQuestionBatchOutput,
    LLMQuestionOptionItem,
    QuestionService,
    SnippetCandidate,
    aggregate_snippet_context,
    build_generation_prompt,
    convert_llm_items_to_candidates,
)

# ==============================================================================
# 测试打桩与 Fake 适配器
# ==============================================================================


class StubQuestionLLM(LLMProtocol):
    """可配置返回题目列表的假大模型适配器。"""

    def __init__(
        self,
        canned_outputs: list[LLMQuestionBatchOutput] | None = None,
        raise_error: bool = False,
    ) -> None:
        self.canned_outputs = canned_outputs or []
        self.call_count = 0
        self.raise_error = raise_error
        self.received_messages: list[Sequence[LLMMessage]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        self.received_messages.append(messages)
        if self.raise_error:
            raise RuntimeError("LLM simulated failure")
        idx = min(self.call_count, len(self.canned_outputs) - 1)
        output = self.canned_outputs[idx] if self.canned_outputs else LLMQuestionBatchOutput()
        self.call_count += 1
        return LLMResponse(
            content=output.model_dump_json(),
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="fake-llm",
        )

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[Any],
        options: LLMOptions | None = None,
    ) -> tuple[Any, LLMResponse]:
        self.received_messages.append(messages)
        if self.raise_error:
            raise RuntimeError("LLM structured simulated failure")
        idx = min(self.call_count, len(self.canned_outputs) - 1)
        output = self.canned_outputs[idx] if self.canned_outputs else LLMQuestionBatchOutput()
        self.call_count += 1
        resp = LLMResponse(
            content=output.model_dump_json(),
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="fake-llm",
        )
        return response_model.model_validate(output.model_dump()), resp


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """提供纯内存 SQLite 数据库会话。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def helper_setup(session: Session) -> dict[str, uuid.UUID]:
    """初始化基础测试数据：资料、版本、切片与知识点。"""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    point_id = uuid.uuid4()
    snippet_id_1 = uuid.uuid4()
    snippet_id_2 = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="软件工程与敏捷实践.pdf",
        file_format="pdf",
        file_size=4096,
    )
    session.add(material)

    version = MaterialVersion(
        id=version_id,
        user_id=user_id,
        material_id=material_id,
        version_number=1,
        storage_key="materials/v1.pdf",
        content_hash="hash_se_v1",
    )
    session.add(version)

    snippet_1 = MaterialSnippet(
        id=snippet_id_1,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=0,
        content=(
            "敏捷开发（Agile）以人为本、响应变化、持续交付软件。"
            "Scrum三大角色：产品负责人、Scrum Master、开发团队。"
        ),
        char_length=60,
        start_offset=0,
        end_offset=60,
        chapter_title="第一章 敏捷开发核心",
        source_info={"similarity": 0.88},
    )
    session.add(snippet_1)

    snippet_2 = MaterialSnippet(
        id=snippet_id_2,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=1,
        content="Scrum五大事件：Sprint规划会议、每日站会、Sprint评审会议、Sprint回顾会议、Sprint。",
        char_length=55,
        start_offset=61,
        end_offset=116,
        chapter_title="第一章 敏捷开发核心",
        source_info={"similarity": 0.85},
    )
    session.add(snippet_2)

    point = KnowledgePoint(
        id=point_id,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        name="敏捷开发核心理念与 Scrum 流程",
        description="敏捷价值观与 Scrum 核心角色与事件",
        level=1,
        batch_id="batch_initial",
    )
    session.add(point)

    # 绑定切片与知识点
    session.add(
        KnowledgePointSnippet(
            user_id=user_id,
            knowledge_point_id=point_id,
            snippet_id=snippet_id_1,
        )
    )
    session.add(
        KnowledgePointSnippet(
            user_id=user_id,
            knowledge_point_id=point_id,
            snippet_id=snippet_id_2,
        )
    )
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "point_id": point_id,
        "snippet_id_1": snippet_id_1,
        "snippet_id_2": snippet_id_2,
    }


# ==============================================================================
# 纯辅助函数单元测试
# ==============================================================================


class TestQuestionHelpers:
    """Test suite for pure helpers in app/services/question.py."""

    def test_aggregate_snippet_context_normal(self) -> None:
        """Verify normal aggregation within character limit."""
        snippets = [
            SnippetCandidate(
                snippet_id=uuid.uuid4(),
                content="片段内容A",
                score=0.9,
                chapter_title="第1章",
            ),
            SnippetCandidate(
                snippet_id=uuid.uuid4(),
                content="片段内容B",
                score=0.8,
                chapter_title="第2章",
            ),
        ]
        context, metadata = aggregate_snippet_context(snippets, max_chars=2400)
        assert "片段内容A" in context
        assert "片段内容B" in context
        assert len(metadata) == 2
        assert metadata[0]["similarity"] == 0.9

    def test_aggregate_snippet_context_truncation(self) -> None:
        """Verify truncating when text exceeds max_chars."""
        long_content = "超长切片测试正文内容。" * 200  # ~2200 字符
        snippets = [
            SnippetCandidate(
                snippet_id=uuid.uuid4(),
                content=long_content,
                score=0.8,
                chapter_title="超长章节1",
            ),
            SnippetCandidate(
                snippet_id=uuid.uuid4(),
                content=long_content,
                score=0.7,
                chapter_title="超长章节2",
            ),
        ]
        context, metadata = aggregate_snippet_context(snippets, max_chars=1000)
        assert len(context) <= 1000
        assert len(metadata) >= 1

    def test_build_generation_prompt(self) -> None:
        """Verify prompt construction with and without feedback."""
        messages_without_feedback = build_generation_prompt(
            kp_name="Scrum角色",
            kp_description="Scrum团队三大核心角色",
            context_text="切片全文",
            question_types=["single_choice"],
            count=2,
            difficulty=3,
        )
        assert len(messages_without_feedback) == 2
        assert "Scrum角色" in messages_without_feedback[1].content
        assert "上一轮质检未通过反馈" not in messages_without_feedback[1].content

        messages_with_feedback = build_generation_prompt(
            kp_name="Scrum角色",
            kp_description="Scrum团队三大核心角色",
            context_text="切片全文",
            question_types=["single_choice"],
            count=2,
            difficulty=3,
            feedback="第1题重复",
        )
        assert "上一轮质检未通过反馈" in messages_with_feedback[1].content
        assert "第1题重复" in messages_with_feedback[1].content

    def test_convert_llm_items_to_candidates(self) -> None:
        """Verify converting LLM items into CandidateQuestion instances."""
        snip_id = str(uuid.uuid4())
        meta = [{"snippet_id": snip_id, "similarity": 0.85, "index": 0}]
        llm_item = LLMGeneratedQuestionItem(
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="下列属于 Scrum 角色的是？",
            options=[
                LLMQuestionOptionItem(key="A", content="Scrum Master"),
                LLMQuestionOptionItem(key="B", content="项目经理"),
            ],
            answer="A",
            analysis="Scrum 包含 PO, SM, Dev Team。",
            difficulty=2,
            source_snippet_index=0,
        )
        candidates, _ = convert_llm_items_to_candidates(
            items=[llm_item],
            snippet_metadata=meta,
            aggregated_source_text="敏捷开发与 Scrum 流程切片全文",
            embeddings=[[0.1] * 1024],
        )
        assert len(candidates) == 1
        assert candidates[0].stem == "下列属于 Scrum 角色的是？"
        assert candidates[0].source_snippet_ids == (snip_id,)
        assert candidates[0].embedding is not None
        assert len(candidates[0].embedding) == 1024

    def test_llm_generated_question_item_tolerant_normalization(self) -> None:
        """Verify tolerant normalization of answer types and grading_rubric."""
        # 1. answer as list for multiple choice
        item_mc = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "multiple_choice",
                "stem": "以下属于软件工程原则的有？",
                "options": [{"key": "A", "content": "模块化"}, {"key": "B", "content": "低耦合"}],
                "answer": ["A", "B", "C"],
            }
        )
        assert item_mc.answer == "A,B,C"

        # 2. answer as list for fill_in_blank
        item_fill = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "fill_in_blank",
                "stem": "测试题干内容描述至少六字符",
                "answer": ["填空1", "填空2"],
            }
        )
        assert item_fill.answer == "填空1; 填空2"

        # 3. answer as bool
        item_tf_true = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "true_false",
                "stem": "这是一个正确命题判断六字符",
                "answer": True,
            }
        )
        assert item_tf_true.answer == "正确"

        item_tf_false = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "true_false",
                "stem": "这是一个错误命题判断六字符",
                "answer": False,
            }
        )
        assert item_tf_false.answer == "错误"

        # 4. answer as int
        item_int = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "fill_in_blank",
                "stem": "计算结果等于几的题干六字符",
                "answer": 42,
            }
        )
        assert item_int.answer == "42"

        # 5. grading_rubric as empty string / none / invalid cleaned to None
        item_empty_rubric = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "single_choice",
                "stem": "单选题目题干内容描述测试",
                "answer": "A",
                "grading_rubric": "",
            }
        )
        assert item_empty_rubric.grading_rubric is None

        # 6. grading_rubric as list of points
        item_list_rubric = LLMGeneratedQuestionItem.model_validate(
            {
                "question_type": "short_answer",
                "stem": "请简述软件工程核心概念",
                "answer": "软件工程是...",
                "grading_rubric": [
                    {"point": "定义阐述完整", "score": 3},
                    {"point": "举例说明恰当", "score": 2},
                ],
            }
        )
        assert item_list_rubric.grading_rubric is not None
        assert item_list_rubric.grading_rubric.total_score == 5
        assert len(item_list_rubric.grading_rubric.points) == 2

    def test_llm_grading_rubric_tolerant_normalization(self) -> None:
        """Verify LLMGradingRubric and LLMGradingPointItem tolerant parsing."""
        # 1. list input
        rubric_from_list = LLMGradingRubric.model_validate(
            [{"point": "要点A", "score": 3}, {"point": "要点B", "score": 2}]
        )
        assert rubric_from_list.total_score == 5
        assert len(rubric_from_list.points) == 2

        # 2. dict missing total_score
        rubric_no_total = LLMGradingRubric.model_validate(
            {"points": [{"point": "要点A", "score": 4}]}
        )
        assert rubric_no_total.total_score == 4

        # 3. dict with alternative keys 'items' or 'criteria'
        rubric_alt_keys = LLMGradingRubric.model_validate(
            {"items": [{"description": "说明清晰", "score": "5"}]}
        )
        assert rubric_alt_keys.total_score == 5
        assert rubric_alt_keys.points[0].point == "说明清晰"
        assert rubric_alt_keys.points[0].score == 5

    def test_llm_question_batch_output_with_various_question_types(self) -> None:
        """Verify batch output parsing when LLM outputs list answers and rubric lists."""
        raw_batch_data = {
            "questions": [
                {
                    "question_type": "single_choice",
                    "stem": "单选题题干描述内容测试1",
                    "options": [{"key": "A", "content": "选项1"}, {"key": "B", "content": "选项2"}],
                    "answer": "A",
                },
                {
                    "question_type": "multiple_choice",
                    "stem": "多选题题干描述内容测试2",
                    "options": [
                        {"key": "A", "content": "选1"},
                        {"key": "B", "content": "选2"},
                        {"key": "C", "content": "选3"},
                    ],
                    "answer": ["A", "B", "C"],
                },
                {
                    "question_type": "true_false",
                    "stem": "判断题题干描述内容测试3",
                    "answer": True,
                },
                {
                    "question_type": "fill_in_blank",
                    "stem": "填空题题干描述内容测试4",
                    "answer": ["答案一", "答案二"],
                },
                {
                    "question_type": "short_answer",
                    "stem": "简答题题干描述内容测试5",
                    "answer": "标准主观答案",
                    "grading_rubric": [{"point": "得分点一", "score": 3}],
                },
            ]
        }
        batch = LLMQuestionBatchOutput.model_validate(raw_batch_data)
        assert len(batch.questions) == 5
        assert batch.questions[1].answer == "A,B,C"
        assert batch.questions[2].answer == "正确"
        assert batch.questions[3].answer == "答案一; 答案二"
        assert batch.questions[4].grading_rubric is not None
        assert batch.questions[4].grading_rubric.total_score == 3


# ==============================================================================
# QuestionService 端到端流程测试
# ==============================================================================


class TestQuestionServiceFlow:
    """Test suite for QuestionService end-to-end flows."""

    def test_generate_questions_retrieval_before_generation_empty(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify MissingSourceSnippetError (40003) when snippets are empty."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        # Create an isolated knowledge point with NO snippets
        orphan_kp = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="无切片考点",
            level=1,
            batch_id="batch_orphan",
        )
        session.add(orphan_kp)
        session.commit()

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(),
            embedding=FakeEmbeddingAdapter(),
            search_adapter=None,
        )

        with pytest.raises(MissingSourceSnippetError) as exc_info:
            service.generate_questions(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=orphan_kp.id,
            )
        assert exc_info.value.error_code == 40003
        assert exc_info.value.status_code == 400

    def test_generate_questions_retrieval_before_generation_low_similarity(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify MissingSourceSnippetError (40003) when snippet similarity < 0.35."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        low_sim_kp = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="低相似度考点",
            level=1,
            batch_id="batch_low",
        )
        low_sim_snippet = MaterialSnippet(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=10,
            content="与考点毫不相关的内容",
            char_length=15,
            start_offset=0,
            end_offset=15,
            chapter_title="其他章节",
            source_info={"similarity": 0.25},  # < 0.35 门禁
        )
        session.add(low_sim_kp)
        session.add(low_sim_snippet)
        session.add(
            KnowledgePointSnippet(
                user_id=user_id,
                knowledge_point_id=low_sim_kp.id,
                snippet_id=low_sim_snippet.id,
            )
        )
        session.commit()

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(),
            embedding=FakeEmbeddingAdapter(),
            search_adapter=None,
        )

        with pytest.raises(MissingSourceSnippetError) as exc_info:
            service.generate_questions(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=low_sim_kp.id,
            )
        assert exc_info.value.error_code == 40003

    def test_precondition_errors(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify MaterialNotFoundError (40004) and KnowledgeNotFoundError (40007)."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(),
            embedding=FakeEmbeddingAdapter(),
        )

        # 1. Non-existent material
        with pytest.raises(MaterialNotFoundError):
            service.generate_questions(
                user_id=user_id,
                material_id=uuid.uuid4(),
                version_id=version_id,
                knowledge_point_id=point_id,
            )

        # 2. Non-existent knowledge point
        with pytest.raises(KnowledgeNotFoundError):
            service.generate_questions(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=uuid.uuid4(),
            )

        # 3. Mismatched tenant user_id
        with pytest.raises(MaterialNotFoundError):
            service.generate_questions(
                user_id=uuid.uuid4(),
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
            )

    def test_generate_questions_version_fallback_tolerance(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify smart version fallback when version_id is None, material_id, or mismatched."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        expected_version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        canned_q = [
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SINGLE_CHOICE.value,
                stem="测试 敏捷开发 的核心理念？",
                options=[
                    LLMQuestionOptionItem(key="A", content="持续交付价值"),
                    LLMQuestionOptionItem(key="B", content="完全不写文档"),
                ],
                answer="A",
                source_snippet_index=0,
            )
        ]
        stub_llm = StubQuestionLLM(
            canned_outputs=[
                LLMQuestionBatchOutput(questions=canned_q),
                LLMQuestionBatchOutput(questions=canned_q),
                LLMQuestionBatchOutput(questions=canned_q),
            ]
        )
        service = QuestionService(
            session=session,
            llm=stub_llm,
            embedding=FakeEmbeddingAdapter(),
        )
        options = GenerateQuestionsOptions(
            question_types=["single_choice"],
            count=1,
            difficulty=3,
        )

        # 1. version_id is None -> auto resolves to expected_version_id
        res1 = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=None,
            knowledge_point_id=point_id,
            options=options,
        )
        assert res1.version_id == expected_version_id

        # 2. version_id == material_id -> auto resolves to expected_version_id
        res2 = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=material_id,
            knowledge_point_id=point_id,
            options=options,
        )
        assert res2.version_id == expected_version_id

        # 3. version_id is mismatched UUID -> auto resolves to expected_version_id
        res3 = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            knowledge_point_id=point_id,
            options=options,
        )
        assert res3.version_id == expected_version_id

    def test_generate_seven_question_types_success(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify generating 7 question types successfully and persisting with status available."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        # 构造符合 7 大题型的合法题目
        seven_questions = [
            # 1. 单选
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SINGLE_CHOICE.value,
                stem="在 敏捷开发 中，下列哪项体现了 响应变化 与 持续交付 软件？",
                options=[
                    LLMQuestionOptionItem(key="A", content="以人为本持续交付"),
                    LLMQuestionOptionItem(key="B", content="严格遵循文档计划"),
                ],
                answer="A",
                source_snippet_index=0,
            ),
            # 2. 多选
            LLMGeneratedQuestionItem(
                question_type=QuestionType.MULTIPLE_CHOICE.value,
                stem="在 Scrum 流程中，属于三大角色的是哪些？（包含 产品负责人 与 开发团队 ）",
                options=[
                    LLMQuestionOptionItem(key="A", content="产品负责人"),
                    LLMQuestionOptionItem(key="B", content="Scrum Master"),
                    LLMQuestionOptionItem(key="C", content="开发团队"),
                    LLMQuestionOptionItem(key="D", content="财务主管"),
                ],
                answer="A, B, C",
                source_snippet_index=0,
            ),
            # 3. 判断
            LLMGeneratedQuestionItem(
                question_type=QuestionType.TRUE_FALSE.value,
                stem="每日站会 是 Scrum 的核心事件之一吗？",
                answer="正确",
                source_snippet_index=1,
            ),
            # 4. 填空
            LLMGeneratedQuestionItem(
                question_type=QuestionType.FILL_IN_BLANK.value,
                stem="敏捷开发 的核心理念是持续交付_____软件。",
                answer="可工作的",
                source_snippet_index=0,
            ),
            # 5. 名词解释
            LLMGeneratedQuestionItem(
                question_type=QuestionType.TERM_EXPLANATION.value,
                stem="请依据材料解释什么是 Scrum Master 角色？",
                answer="Scrum三大角色之一，负责推进敏捷流程。",
                grading_rubric=LLMGradingRubric(
                    total_score=5,
                    points=[
                        LLMGradingPointItem(point="三大角色之一", score=2),
                        LLMGradingPointItem(point="推进敏捷流程", score=3),
                    ],
                ),
                source_snippet_index=0,
            ),
            # 6. 简答
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SHORT_ANSWER.value,
                stem="简述 Scrum 流程中 每日站会 与 Sprint规划会议 等五大事件的构成。",
                answer="Sprint 规划会议、每日站会、评审会、回顾会及 Sprint。",
                grading_rubric=LLMGradingRubric(
                    total_score=10,
                    points=[
                        LLMGradingPointItem(point="列举 Sprint 规划与每日站会", score=5),
                        LLMGradingPointItem(point="列举评审、回顾与 Sprint", score=5),
                    ],
                ),
                source_snippet_index=1,
            ),
            # 7. 案例分析
            LLMGeneratedQuestionItem(
                question_type=QuestionType.CASE_ANALYSIS.value,
                stem="某团队实施 敏捷开发 ，如何组织 每日站会 与 Sprint回顾会议 ？",
                answer="通过Sprint规划明确目标，每日站会同步，Sprint评审与回顾持续改进。",
                grading_rubric=LLMGradingRubric(
                    total_score=15,
                    points=[
                        LLMGradingPointItem(point="Sprint 规划与站会组织", score=7),
                        LLMGradingPointItem(point="评审与回顾实施", score=8),
                    ],
                ),
                source_snippet_index=1,
            ),
        ]

        stub_llm = StubQuestionLLM(
            canned_outputs=[LLMQuestionBatchOutput(questions=seven_questions)]
        )

        service = QuestionService(
            session=session,
            llm=stub_llm,
            embedding=FakeEmbeddingAdapter(),
        )

        options = GenerateQuestionsOptions(
            question_types=[q.question_type for q in seven_questions],
            count=7,
            difficulty=3,
        )

        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=options,
        )

        assert result.total_generated == 7
        assert len(result.qualified_questions) == 7
        assert len(result.pending_questions) == 0
        assert result.retry_count == 0

        # 验证题目状态与 1024 维向量
        for q in result.qualified_questions:
            assert q.status == QuestionStatus.AVAILABLE.value
            assert q.user_id == user_id
            assert q.embedding is not None
            assert len(q.embedding) == 1024
            assert q.source_snippet_id is not None

        # 验证质检记录落库
        assert len(result.quality_checks) > 0
        for qc in result.quality_checks:
            assert qc.user_id == user_id
            assert qc.batch_id == result.batch_id
            assert qc.is_passed is True

    def test_quality_check_failure_and_retry_adaptation(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify quality check failure triggers feedback prompt and retries successfully."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        # Attempt 1: 包含一道无来源题目 (NO_SOURCE)
        bad_question = LLMGeneratedQuestionItem(
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="量子力学薛定谔的猫态是如何演化的？",  # 无来源实词
            options=[
                LLMQuestionOptionItem(key="A", content="叠加态塌缩"),
                LLMQuestionOptionItem(key="B", content="相干性保持"),
            ],
            answer="A",
            source_snippet_index=0,
        )
        good_question_1 = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="在 敏捷开发 中，核心理念是持续交付 软件。",
            answer="正确",
            source_snippet_index=0,
        )
        attempt_1_output = LLMQuestionBatchOutput(questions=[good_question_1, bad_question])

        # Attempt 2: 修正后的合法题目
        good_question_2 = LLMGeneratedQuestionItem(
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="在 Scrum 流程中，每日站会 是五大事件之一吗？",
            options=[
                LLMQuestionOptionItem(key="A", content="包含每日站会"),
                LLMQuestionOptionItem(key="B", content="不包含任何会议"),
            ],
            answer="A",
            source_snippet_index=1,
        )
        attempt_2_output = LLMQuestionBatchOutput(questions=[good_question_2])

        stub_llm = StubQuestionLLM(canned_outputs=[attempt_1_output, attempt_2_output])

        service = QuestionService(
            session=session,
            llm=stub_llm,
            embedding=FakeEmbeddingAdapter(),
        )

        options = GenerateQuestionsOptions(count=2, max_retries=2)
        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=options,
        )

        assert result.retry_count == 1
        assert len(result.qualified_questions) == 2
        # LLM received feedback in attempt 2
        assert len(stub_llm.received_messages) == 2
        assert "上一轮质检未通过反馈" in stub_llm.received_messages[1][1].content

    def test_retry_exhausted_moves_to_pending_review(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify that when retries are exhausted, failing questions enter pending_review."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        # 始终返回包含歧义（题干过短）的题目
        ambiguous_question = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="短",  # < 6 字符，明显歧义
            answer="对",
        )
        output = LLMQuestionBatchOutput(questions=[ambiguous_question])

        stub_llm = StubQuestionLLM(canned_outputs=[output, output, output])

        service = QuestionService(
            session=session,
            llm=stub_llm,
            embedding=FakeEmbeddingAdapter(),
        )

        options = GenerateQuestionsOptions(count=1, max_retries=2)
        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=options,
        )

        assert result.retry_count == 2
        assert len(result.qualified_questions) == 0
        assert len(result.pending_questions) == 1
        assert result.pending_questions[0].status == QuestionStatus.PENDING_REVIEW.value


# ==============================================================================
# QuestionService CRUD 与审计日志单元测试
# ==============================================================================


class TestQuestionServiceCRUDAndAudit:
    """Test suite for QuestionService CRUD and audit logging."""

    def test_crud_and_audit_logging(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify get, update, and soft delete with audit log recording."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(),
            embedding=FakeEmbeddingAdapter(),
        )

        q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.TRUE_FALSE.value,
            stem="敏捷开发注重个体与互动胜过过程和工具。",
            answer="正确",
            difficulty=2,
        )
        saved = service.question_repo.create_question(q, user_id)
        session.commit()

        # 1. get_question
        fetched = service.get_question(user_id=user_id, question_id=saved.id)
        assert fetched.id == saved.id

        # Cross-tenant get raises QuestionNotFoundError
        with pytest.raises(QuestionNotFoundError):
            service.get_question(user_id=uuid.uuid4(), question_id=saved.id)

        # 2. update_question
        updated = service.update_question(
            user_id=user_id,
            question_id=saved.id,
            updates={"difficulty": 4, "analysis": "敏捷宣言四大价值观之一。"},
            reason="用户调整难度与解析",
        )
        assert updated.difficulty == 4
        assert updated.analysis == "敏捷宣言四大价值观之一。"

        # Verify audit log recorded for edit
        logs = service.question_repo.list_audit_logs_by_question(saved.id, user_id)
        assert len(logs) == 1
        assert logs[0].action == AuditAction.EDIT.value
        assert logs[0].reason == "用户调整难度与解析"
        assert "difficulty" in logs[0].changed_fields

        # 3. delete_question (soft delete)
        deleted = service.delete_question(
            user_id=user_id,
            question_id=saved.id,
            reason="用户软删除废弃题目",
        )
        assert deleted is True

        # Now get_question raises QuestionNotFoundError
        with pytest.raises(QuestionNotFoundError):
            service.get_question(user_id=user_id, question_id=saved.id)

        # Verify audit log recorded for delete
        logs_after_del = service.question_repo.list_audit_logs_by_question(saved.id, user_id)
        assert len(logs_after_del) == 2
        assert logs_after_del[0].action == AuditAction.DELETE.value
        assert logs_after_del[0].reason == "用户软删除废弃题目"

    def test_search_adapter_integration(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify integration with SearchProtocol when complementary search is performed."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        search_adapter = FakeSearchAdapter()
        search_snippet_id = uuid.uuid4()
        candidate = SearchSnippetCandidate(
            snippet_id=search_snippet_id,
            material_id=material_id,
            version_id=version_id,
            content="在 看板方法 中，其核心实践包含 可视化工作流 与限制在制品两条实践。",
            chapter_title="第二章 精益看板",
            source_info={"page": 2},
            # 真实契约：相似度门禁读取向量余弦分（0-1）；final_score 为 RRF 排名分（小量级）。
            # 若实现误用 final_score，本用例将因低于 0.35 阈值而失败，从而守住该缺陷回归。
            vector_score=0.91,
            final_score=0.032,
        )
        search_adapter.set_canned_candidates([candidate])

        valid_question = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="在 看板方法 中，其核心实践包含 可视化工作流 吗？",
            answer="正确",
            source_snippet_index=0,
        )

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(
                canned_outputs=[LLMQuestionBatchOutput(questions=[valid_question])]
            ),
            embedding=FakeEmbeddingAdapter(),
            search_adapter=search_adapter,
        )

        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=GenerateQuestionsOptions(count=1),
        )
        assert result.total_generated == 1
        assert len(result.qualified_questions) == 1

    def test_generate_options_validation(self) -> None:
        """Verify validation errors for GenerateQuestionsOptions."""
        with pytest.raises(ValueError, match="count 必须在 1 到 20 之间"):
            GenerateQuestionsOptions(count=0)

        with pytest.raises(ValueError, match="count 必须在 1 到 20 之间"):
            GenerateQuestionsOptions(count=21)

        with pytest.raises(ValueError, match="difficulty 必须在 1 到 5 之间"):
            GenerateQuestionsOptions(difficulty=0)

        with pytest.raises(ValueError, match="difficulty 必须在 1 到 5 之间"):
            GenerateQuestionsOptions(difficulty=6)

        with pytest.raises(ValueError, match="max_retries 必须在 0 到 5 之间"):
            GenerateQuestionsOptions(max_retries=-1)

        with pytest.raises(ValueError, match="max_retries 必须在 0 到 5 之间"):
            GenerateQuestionsOptions(max_retries=6)

    def test_empty_llm_output_triggers_retry_or_break(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify empty LLM output triggers retry then breaks cleanly."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        empty_output = LLMQuestionBatchOutput(questions=[])
        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(canned_outputs=[empty_output, empty_output]),
            embedding=FakeEmbeddingAdapter(),
        )

        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=GenerateQuestionsOptions(count=1, max_retries=1),
        )
        assert result.total_generated == 0
        assert result.retry_count == 1

    def test_atomic_transaction_rollback_on_error(
        self, session: Session, helper_setup: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify atomic transaction rollback when database commit fails."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        valid_question = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="在 敏捷开发 中，核心理念是持续交付 软件。",
            answer="正确",
            source_snippet_index=0,
        )
        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(
                canned_outputs=[LLMQuestionBatchOutput(questions=[valid_question])]
            ),
            embedding=FakeEmbeddingAdapter(),
        )

        # Force session commit to fail
        def failing_commit() -> None:
            raise RuntimeError("Database connection lost")

        monkeypatch.setattr(session, "commit", failing_commit)

        with pytest.raises(RuntimeError, match="Database connection lost"):
            service.generate_questions(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                options=GenerateQuestionsOptions(count=1),
            )

        # Create an existing question to test update & delete rollback
        existing_q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.TRUE_FALSE.value,
            stem="敏捷开发核心理念测试。",
            answer="正确",
        )
        saved_q = service.question_repo.create_question(existing_q, user_id)

        # Also test update_question rollback
        with pytest.raises(RuntimeError, match="Database connection lost"):
            service.update_question(
                user_id=user_id,
                question_id=saved_q.id,
                updates={"difficulty": 2},
            )

        # Re-create for delete_question rollback test
        existing_q2 = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.TRUE_FALSE.value,
            stem="敏捷开发核心理念测试2。",
            answer="正确",
        )
        saved_q2 = service.question_repo.create_question(existing_q2, user_id)

        # Also test delete_question rollback
        with pytest.raises(RuntimeError, match="Database connection lost"):
            service.delete_question(
                user_id=user_id,
                question_id=saved_q2.id,
            )

    def test_generate_questions_defer_commit_defers_to_caller(
        self, session: Session, helper_setup: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """defer_commit=True must not commit; the caller owns the boundary (QGEN-007)."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        valid_question = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="在 敏捷开发 中，核心理念是持续交付 软件。",
            answer="正确",
            source_snippet_index=0,
        )
        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(
                canned_outputs=[LLMQuestionBatchOutput(questions=[valid_question])]
            ),
            embedding=FakeEmbeddingAdapter(),
        )
        commit_spy = MagicMock(wraps=session.commit)
        monkeypatch.setattr(session, "commit", commit_spy)

        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=GenerateQuestionsOptions(count=1, max_retries=0),
            defer_commit=True,
        )

        # Rows are flushed but the service must not commit them on its own.
        assert result.total_generated == 1
        assert commit_spy.call_count == 0

        session.commit()
        assert commit_spy.call_count == 1

    def test_search_adapter_exception_handled_gracefully(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify search_adapter failure logs warning and proceeds with bound snippets."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        class FailingSearchAdapter(FakeSearchAdapter):
            def search(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("Search engine cluster degraded")

        valid_question = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="在 敏捷开发 中，核心理念是持续交付 软件。",
            answer="正确",
            source_snippet_index=0,
        )

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(
                canned_outputs=[LLMQuestionBatchOutput(questions=[valid_question])]
            ),
            embedding=FakeEmbeddingAdapter(),
            search_adapter=FailingSearchAdapter(),
        )

        result = service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            options=GenerateQuestionsOptions(count=1),
        )
        assert result.total_generated == 1

    def test_convert_llm_items_to_candidates_empty_metadata(self) -> None:
        """Verify convert_llm_items_to_candidates handles empty snippet metadata."""
        item = LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="题干内容测试大于六字符",
            answer="正确",
        )
        candidates, _ = convert_llm_items_to_candidates(
            items=[item],
            snippet_metadata=[],
            aggregated_source_text="文本",
        )
        assert len(candidates) == 1
        assert candidates[0].source_snippet_ids == ()

    def test_update_and_delete_repo_failure(
        self, session: Session, helper_setup: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify QuestionNotFoundError when repo returns None on update or False on delete."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(),
            embedding=FakeEmbeddingAdapter(),
        )

        existing_q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.TRUE_FALSE.value,
            stem="敏捷开发核心理念测试。",
            answer="正确",
        )
        saved_q = service.question_repo.create_question(existing_q, user_id)

        # Monkeypatch update_question in repo to return None
        monkeypatch.setattr(service.question_repo, "update_question", lambda *a, **kw: None)
        with pytest.raises(QuestionNotFoundError):
            service.update_question(
                user_id=user_id,
                question_id=saved_q.id,
                updates={"difficulty": 5},
            )

        # Monkeypatch soft_delete_question in repo to return False
        monkeypatch.setattr(service.question_repo, "soft_delete_question", lambda *a, **kw: False)
        with pytest.raises(QuestionNotFoundError):
            service.delete_question(
                user_id=user_id,
                question_id=saved_q.id,
            )

    def test_service_helper_methods(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify get_question_detail, list_questions, list_edit_logs, list_quality_checks."""
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        service = QuestionService(
            session=session,
            llm=StubQuestionLLM(),
            embedding=FakeEmbeddingAdapter(),
        )

        q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="题目服务辅助方法测试。",
            answer="B",
            difficulty=2,
        )
        saved = service.question_repo.create_question(q, user_id)

        # 1. get_question_detail
        fetched = service.get_question_detail(saved.id, user_id)
        assert fetched.id == saved.id

        # 2. list_questions with pagination
        items, total = service.list_questions(
            user_id=user_id,
            material_id=material_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            difficulty=2,
            page=1,
            page_size=10,
        )
        assert total >= 1
        assert any(item.id == saved.id for item in items)

        # 3. update_question and list_edit_logs
        service.update_question(
            saved.id,
            user_id,
            {"difficulty": 4},
            "测试调整难度",
        )
        logs = service.list_edit_logs(saved.id, user_id)
        assert len(logs) == 1
        assert logs[0].reason == "测试调整难度"

        # 4. list_quality_checks
        check = QuestionQualityCheck(
            user_id=user_id,
            question_id=saved.id,
            batch_id="batch_helper",
            check_type="AMBIGUITY",
            is_passed=True,
        )
        service.question_repo.batch_create_quality_checks([check], user_id)
        checks = service.list_quality_checks(material_id, user_id)
        assert len(checks) >= 1
        assert any(c.batch_id == "batch_helper" for c in checks)
