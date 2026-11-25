"""Tests for the autonomous AI quality verification, repair, and zero pending_review loop."""

import math
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.algorithms.question_quality import (
    CandidateQuestion,
    ExistingQuestionReference,
    QualityCheckType,
    QualitySeverity,
    QuestionQualityConfig,
    QuestionType,
    evaluate_single_question,
)
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol, LLMResponse, LLMUsage
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialSnippet, MaterialStatus, MaterialVersion
from app.models.question import Question, QuestionStatus
from app.models.user import User
from app.services._question_generation import GenerateQuestionsOptions, run_question_generation_loop
from app.services._question_llm_schemas import (
    LLMGeneratedQuestionItem,
    LLMQuestionBatchOutput,
    LLMQuestionOptionItem,
)
from app.services._question_quality_judge import (
    AI_JUDGE_CHECK_TYPE,
    LLMQuestionJudgeBatchOutput,
    LLMQuestionJudgeDecision,
)
from app.services.question import QuestionService


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


class _ScriptedQualityLLM(LLMProtocol):
    """Stub LLM supporting separate scripted responses for generation and AI Judge."""

    def __init__(
        self,
        *,
        generation_batches: list[LLMQuestionBatchOutput],
        judge_batches: list[LLMQuestionJudgeBatchOutput | Exception] | None = None,
    ) -> None:
        self.generation_batches = generation_batches
        self.judge_batches = judge_batches or []
        self.generation_options: list[LLMOptions | None] = []
        self.generation_prompts: list[str] = []
        self.judge_options: list[LLMOptions | None] = []
        self.judge_call_count = 0
        self._gen_idx = 0

    def generate(
        self, messages: Sequence[LLMMessage], options: LLMOptions | None = None
    ) -> LLMResponse:
        raise NotImplementedError

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[Any],
        options: LLMOptions | None = None,
    ) -> tuple[Any, LLMResponse]:
        resp = LLMResponse(content="{}", model="stub-llm", usage=LLMUsage())
        if response_model is LLMQuestionJudgeBatchOutput:
            self.judge_options.append(options)
            idx = min(self.judge_call_count, len(self.judge_batches) - 1)
            self.judge_call_count += 1
            if not self.judge_batches:
                return LLMQuestionJudgeBatchOutput(decisions=[]), resp
            payload = self.judge_batches[idx]
            if isinstance(payload, Exception):
                raise payload
            return payload, resp

        self.generation_options.append(options)
        self.generation_prompts.append(messages[-1].content)
        idx = min(self._gen_idx, len(self.generation_batches) - 1)
        self._gen_idx += 1
        batch = self.generation_batches[idx]
        return response_model.model_validate(batch.model_dump()), resp


def test_llm_schema_normalizes_option_answer_prefixes_without_corrupting_text() -> None:
    """Option prefixes like 'A. 内容', '(B) 内容', '选项 C' normalize to keys."""
    options = [
        {"key": "A", "content": "最大间隔超平面"},
        {"key": "B", "content": "最小二乘拟合"},
        {"key": "C", "content": "决策树剪枝"},
    ]
    item_single_dot = LLMGeneratedQuestionItem.model_validate(
        {
            "question_type": "single_choice",
            "stem": "支持向量机的核心优化目标是什么？",
            "options": options,
            "answer": "A. 最大间隔超平面",
        }
    )
    assert item_single_dot.answer == "A"

    item_single_paren = LLMGeneratedQuestionItem.model_validate(
        {
            "question_type": "single_choice",
            "stem": "关于支持向量机，下列说法正确的是？",
            "options": options,
            "answer": "选项 B",
        }
    )
    assert item_single_paren.answer == "B"

    item_multi = LLMGeneratedQuestionItem.model_validate(
        {
            "question_type": "multiple_choice",
            "stem": "关于优化算法，以下哪些正确？",
            "options": options,
            "answer": "A. 最大间隔超平面; (C) 决策树剪枝",
        }
    )
    assert item_multi.answer == "A,C"

    # Multi-key single choice stays invalid so check_ambiguity catches it
    item_bad_single = LLMGeneratedQuestionItem.model_validate(
        {
            "question_type": "single_choice",
            "stem": "错误的单选多答案示例",
            "options": options,
            "answer": "A, B",
        }
    )
    assert item_bad_single.answer == "A,B"

    # Fill-in-blank text answer must NOT be stripped
    item_fill = LLMGeneratedQuestionItem.model_validate(
        {
            "question_type": "fill_in_blank",
            "stem": "提出图灵测试的学者是_____。",
            "options": [],
            "answer": "A. Turing",
        }
    )
    assert item_fill.answer == "A. Turing"


def test_chinese_svm_math_stem_passes_deterministic_grounding_and_severity_tiers() -> None:
    """Chinese SVM + LaTeX stems pass NO_SOURCE; 0.88..0.95 & low overlap yield SOFT_FLAG."""
    config = QuestionQualityConfig()
    svm_source = (
        "支持向量机（SVM）旨在寻找将两类样本分开的最大几何间隔超平面。"
        "设超平面方程为 w^T x + b = 0，拉格朗日对偶问题受 KKT 条件约束。"
    )
    svm_cand = CandidateQuestion(
        question_id="q-svm-1",
        stem=(
            r"在支持向量机（SVM）中，若分类超平面方程为 $\mathbf{w}^T \mathbf{x} + b = 0$，"
            r"则样本点到超平面的几何间隔与 $\min \frac{1}{2}\sum \alpha_i$ 遵循什么条件？"
        ),
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A",
        options=(
            {"key": "A", "content": "KKT 条件与最大几何间隔"},
            {"key": "B", "content": "欧氏距离最小化"},
        ),
        source_snippet_ids=("s1",),
        source_text=svm_source,
        embedding=(1.0, 0.0),
    )
    res_pass, _ = evaluate_single_question(svm_cand, (), (), config)
    assert res_pass.is_qualified is True
    assert res_pass.severity == QualitySeverity.PASS

    # Low overlap paraphrased math stem -> SOFT_FLAG (NOT HARD_DEFECT)
    paraphrased = CandidateQuestion(
        question_id="q-svm-soft",
        stem="在间隔最大化理论中，对偶松弛变量与惩罚系数之间存在怎样的平衡机制？",
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A",
        options=(
            {"key": "A", "content": "抑制异常点过拟合"},
            {"key": "B", "content": "消除所有支撑向量"},
        ),
        source_snippet_ids=("s1",),
        source_text=svm_source,
        embedding=(0.0, 1.0),
    )
    res_soft, _ = evaluate_single_question(paraphrased, (), (), config)
    assert res_soft.is_qualified is False
    assert res_soft.severity == QualitySeverity.SOFT_FLAG
    assert res_soft.unqualified_type == QualityCheckType.NO_SOURCE

    # Vector similarity 0.92 (between 0.90 and 0.95) -> SOFT_FLAG DUPLICATE
    existing = ExistingQuestionReference(
        question_id="ex-1",
        stem="支持向量机寻找最大几何间隔超平面的核心目标是什么？",
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A",
        embedding=(0.92, math.sqrt(1 - 0.92**2)),
    )
    res_dup_soft, _ = evaluate_single_question(svm_cand, (existing,), (), config)
    assert res_dup_soft.severity == QualitySeverity.SOFT_FLAG
    assert res_dup_soft.unqualified_type == QualityCheckType.DUPLICATE

    # Vector similarity 0.97 (>= 0.95) -> HARD_DEFECT DUPLICATE
    existing_hard = ExistingQuestionReference(
        question_id="ex-2",
        stem="另一道高度同义的题目表述",
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A",
        embedding=(0.97, math.sqrt(1 - 0.97**2)),
    )
    res_dup_hard, _ = evaluate_single_question(svm_cand, (existing_hard,), (), config)
    assert res_dup_hard.severity == QualitySeverity.HARD_DEFECT

    # Missing answer key in options -> HARD_DEFECT AMBIGUITY
    bad_key_cand = CandidateQuestion(
        question_id="q-bad-key",
        stem=svm_cand.stem,
        question_type=QuestionType.SINGLE_CHOICE,
        answer="Z",
        options=svm_cand.options,
        source_snippet_ids=("s1",),
        source_text=svm_source,
        embedding=(0.0, 1.0),
    )
    res_bad_key, _ = evaluate_single_question(bad_key_cand, (), (), config)
    assert res_bad_key.severity == QualitySeverity.HARD_DEFECT
    assert res_bad_key.unqualified_type == QualityCheckType.AMBIGUITY


def test_batched_ai_judge_approve_repair_reject_and_escalating_temperature_loop() -> None:
    """Verify 1 batched judge call enforces approve/repair/reject rules and temperature ramp."""
    context_text = (
        "--- [切片 0] (章节: 第3章 SVM) ---\n"
        "支持向量机（SVM）通过最大化分类间隔寻找最优超平面 w^T x + b = 0。"
        "软间隔引入松弛变量并利用 KKT 条件求解对偶问题。"
    )
    snippet_meta = [{"snippet_id": str(uuid.uuid4()), "similarity": 0.9, "index": 0}]

    # Round 0 (target=3):
    # [0] SOFT_FLAG (NO_SOURCE low overlap) -> Judge says approve -> ACCEPTED
    # [1] HARD_DEFECT (AMBIGUITY: answer 'Z' not in options) -> approve -> FORCE REJECT!
    # [2] HARD_DEFECT (AMBIGUITY: duplicate options) -> Judge repairs -> ACCEPTED
    q_soft = LLMGeneratedQuestionItem(
        question_type="single_choice",
        stem="关于松弛变量在软间隔模型中的惩罚权衡机制，下列描述准确的是？",
        options=[
            LLMQuestionOptionItem(key="A", content="平衡分类间隔与误分代价"),
            LLMQuestionOptionItem(key="B", content="强制全部样本线性可分"),
        ],
        answer="A",
        source_snippet_index=0,
    )
    q_hard_bad_approve = LLMGeneratedQuestionItem(
        question_type="single_choice",
        stem="支持向量机最优超平面的对偶求解依赖什么条件？",
        options=[
            LLMQuestionOptionItem(key="A", content="KKT 条件"),
            LLMQuestionOptionItem(key="B", content="最小二乘条件"),
        ],
        answer="Z",  # HARD_DEFECT: answer not in options
        source_snippet_index=0,
    )
    q_hard_repair = LLMGeneratedQuestionItem(
        question_type="single_choice",
        stem="在 SVM 中引入软间隔后，对偶问题如何求解？",
        options=[
            LLMQuestionOptionItem(key="A", content="重复选项"),
            LLMQuestionOptionItem(key="B", content="重复选项"),
        ],
        answer="A",
        source_snippet_index=0,
    )
    q_repaired = LLMGeneratedQuestionItem(
        question_type="single_choice",
        stem="在支持向量机（SVM）引入软间隔后，对偶问题依赖什么条件求解？",
        options=[
            LLMQuestionOptionItem(key="A", content="利用 KKT 条件与松弛变量求解"),
            LLMQuestionOptionItem(key="B", content="仅使用无约束梯度下降"),
        ],
        answer="A",
        source_snippet_index=0,
    )

    # Round 1 (needed_count = 1): generates 1 valid PASS question
    q_round1_pass = LLMGeneratedQuestionItem(
        question_type="true_false",
        stem="支持向量机（SVM）通过最大化分类间隔寻找最优超平面，这一目标是否准确？",
        answer="正确",
        source_snippet_index=0,
    )

    llm = _ScriptedQualityLLM(
        generation_batches=[
            LLMQuestionBatchOutput(questions=[q_soft, q_hard_bad_approve, q_hard_repair]),
            LLMQuestionBatchOutput(questions=[q_round1_pass]),
        ],
        judge_batches=[
            LLMQuestionJudgeBatchOutput(
                decisions=[
                    LLMQuestionJudgeDecision(
                        question_index=0,
                        verdict="approve",
                        reason="数学表述准确且忠于切片",
                    ),
                    LLMQuestionJudgeDecision(
                        question_index=1,
                        verdict="approve",
                        reason="模型误放行硬缺陷",
                    ),
                    LLMQuestionJudgeDecision(
                        question_index=2,
                        verdict="repair",
                        reason="去重选项",
                        repaired_question=q_repaired,
                    ),
                ]
            )
        ],
    )

    outcome = run_question_generation_loop(
        llm=llm,
        embedding=FakeEmbeddingAdapter(),
        user_id=uuid.uuid4(),
        batch_id="batch_gate_test",
        kp_name="支持向量机",
        kp_description="SVM 最大间隔与 KKT 条件",
        context_text=context_text,
        snippet_metadata=snippet_meta,
        existing_refs=(),
        options=GenerateQuestionsOptions(count=3, max_retries=2),
    )

    assert len(outcome.qualified_questions) == 3
    assert outcome.retry_count == 1
    assert llm.judge_call_count == 1
    assert llm.judge_options[0] is not None
    assert llm.judge_options[0].max_tokens == 4096

    # Escalating temperatures 0.3 -> 0.5 and passed-stem dedup hint in round 1
    assert [opt.temperature for opt in llm.generation_options if opt is not None] == [0.3, 0.5]
    assert "已通过质检的题干摘要" in llm.generation_prompts[1]
    assert "预期" not in llm.generation_prompts[1]

    # Approved & repaired questions carry AI_JUDGE audit record
    judge_checks = [
        check
        for checks in outcome.candidate_checks_map.values()
        for check in checks
        if check.check_type == AI_JUDGE_CHECK_TYPE
    ]
    assert len(judge_checks) == 2


def test_list_questions_defaults_to_available_only(session: Session) -> None:
    """list_questions without explicit status excludes legacy pending_review rows."""
    user = User(id=uuid.uuid4(), openid="wx_default_avail", nickname="u")
    session.add(user)
    material = Material(
        id=uuid.uuid4(),
        user_id=user.id,
        title="线性代数.pdf",
        file_format="pdf",
        file_size=1024,
        status=MaterialStatus.READY.value,
    )
    session.add(material)
    version = MaterialVersion(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_number=1,
        storage_key="raw/la.pdf",
        content_hash="la_hash",
        parse_status="completed",
    )
    session.add(version)
    kp = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        name="特征值",
        description="特征值与特征向量",
        level=1,
        batch_id="kp-batch-1",
    )
    session.add(kp)
    snippet = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        snippet_index=0,
        chapter_title="第1章",
        content="特征值满足 Ax = lambda x",
        char_length=20,
        start_offset=0,
        end_offset=20,
    )
    session.add(snippet)
    session.add(
        KnowledgePointSnippet(user_id=user.id, knowledge_point_id=kp.id, snippet_id=snippet.id)
    )
    session.add(
        Question(
            user_id=user.id,
            material_id=material.id,
            version_id=version.id,
            knowledge_point_id=kp.id,
            question_type=QuestionType.TRUE_FALSE.value,
            status=QuestionStatus.AVAILABLE.value,
            stem="特征值必须是非零实数吗？",
            answer="错误",
        )
    )
    session.add(
        Question(
            user_id=user.id,
            material_id=material.id,
            version_id=version.id,
            knowledge_point_id=kp.id,
            question_type=QuestionType.TRUE_FALSE.value,
            status=QuestionStatus.PENDING_REVIEW.value,
            stem="历史遗留待审核题目不应对学生可见",
            answer="正确",
        )
    )
    session.commit()

    service = QuestionService(
        session=session,
        llm=FakeLLMAdapter(),
        embedding=FakeEmbeddingAdapter(),
    )
    items, total = service.list_questions(user_id=user.id, material_id=material.id)
    assert total == 1
    assert len(items) == 1
    assert items[0].status == QuestionStatus.AVAILABLE.value
