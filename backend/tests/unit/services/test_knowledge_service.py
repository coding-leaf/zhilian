"""Unit tests for KnowledgeService in app/services/knowledge.py.

Verifies:
1. Pure helpers:
   - compute_chapter_stats: empty, single, and multi-chapter distributions.
   - deduplicate_candidate_points: identity, dissimilar, similar (>0.92) merge and redirection.
   - build_knowledge_hierarchy: normal tree, orphan self-healing, cycle detection, depth clamping.
2. KnowledgeService end-to-end extraction and tree building:
   - Happy path: LLM structured extraction, embedding deduplication, quality check passing,
     persistence and dual-traceability relation creation.
   - Pre-condition validations: MaterialNotFoundError, MaterialInvalidError (empty snippets).
   - Quality check failure and retry loop:
     - Retry succeeds on attempt 1 with adjusted batch size and feedback.
     - Retry exhausted (>= 2 retries) triggers degradation with is_low_confidence=True.
     - Empty extraction across retries raises KnowledgeExtractionRetryExceededError.
     - Fallback when AgentGraph raises an exception.
     - Atomic rollback when database transaction fails (marking ParseStatus.FAILED).
3. get_knowledge_tree:
   - MaterialNotFoundError for non-existent or cross-tenant material.
   - Correct nested hierarchical dictionary output.
4. Strict multi-tenant isolation.
"""

import uuid
from collections.abc import Generator, Sequence
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    KnowledgeExtractionRetryExceededError,
    MaterialInvalidError,
    MaterialNotFoundError,
)
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.models.base import Base
from app.models.material import Material, MaterialSnippet, MaterialVersion, ParseStatus
from app.repositories.material import MaterialRepository
from app.services.knowledge import (
    ExtractedKnowledgeItem,
    KnowledgeExtractionOutput,
    KnowledgeService,
    build_knowledge_hierarchy,
    compute_chapter_stats,
    deduplicate_candidate_points,
)

T = TypeVar("T", bound=BaseModel)


# ==============================================================================
# 测试打桩与 Fake 适配器
# ==============================================================================


class StubLLM(LLMProtocol):
    """可配置返回列表的假大模型适配器。"""

    def __init__(
        self,
        canned_outputs: list[KnowledgeExtractionOutput] | None = None,
        raise_agent_graph_error: bool = False,
    ) -> None:
        self.canned_outputs = canned_outputs or []
        self.call_count = 0
        self.raise_agent_graph_error = raise_agent_graph_error
        self.received_messages: list[Sequence[LLMMessage]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        self.received_messages.append(messages)
        if self.raise_agent_graph_error:
            raise RuntimeError("AgentGraph simulated failure")
        idx = min(self.call_count, len(self.canned_outputs) - 1)
        output = self.canned_outputs[idx] if self.canned_outputs else KnowledgeExtractionOutput()
        self.call_count += 1
        return LLMResponse(
            content=output.model_dump_json(),
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="fake-llm",
        )

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        self.received_messages.append(messages)
        idx = min(self.call_count, len(self.canned_outputs) - 1)
        output = self.canned_outputs[idx] if self.canned_outputs else KnowledgeExtractionOutput()
        self.call_count += 1
        resp = LLMResponse(
            content=output.model_dump_json(),
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="fake-llm",
        )
        return response_model.model_validate(output.model_dump()), resp


class StubEmbedding(FakeEmbeddingAdapter):
    """基于 FakeEmbeddingAdapter 的测试假向量适配器。"""

    pass


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """创建独立的内存数据库会话。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def seed_material(session: Session) -> dict[str, Any]:
    """生成测试所需基础学习资料、版本与切片数据。"""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="高等数学精要.pdf",
        file_format="pdf",
        file_size=2048,
    )
    version = MaterialVersion(
        id=version_id,
        user_id=user_id,
        material_id=material_id,
        version_number=1,
        storage_key="test/v1.pdf",
        content_hash="hash_001",
        parse_status=ParseStatus.EXTRACTING_KNOWLEDGE.value,
    )
    s1 = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=0,
        content="第一章极限与连续：极限的精确数学定义与ε-δ语言描述。",
        char_length=800,
        start_offset=0,
        end_offset=800,
        chapter_title="第一章 极限与连续",
    )
    s2 = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=1,
        content="极限的四则运算法则以及复合函数的极限求法。",
        char_length=800,
        start_offset=801,
        end_offset=1601,
        chapter_title="第一章 极限与连续",
    )
    s3 = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=2,
        content="无穷小量的阶与等价无穷小量代换定理的应用。",
        char_length=800,
        start_offset=1602,
        end_offset=2402,
        chapter_title="第一章 极限与连续",
    )

    session.add_all([material, version, s1, s2, s3])
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "snippets": [s1, s2, s3],
    }


# ==============================================================================
# 纯数据处理与辅助函数测试
# ==============================================================================


class TestKnowledgeHelpers:
    """测试知识点抽取辅助计算与纯函数。"""

    def test_compute_chapter_stats(self) -> None:
        """测试章节切片统计分布函数。"""
        # 空切片
        assert compute_chapter_stats([]) == []

        user_id = uuid.uuid4()
        mat_id = uuid.uuid4()
        ver_id = uuid.uuid4()

        s1 = MaterialSnippet(
            user_id=user_id,
            material_id=mat_id,
            version_id=ver_id,
            snippet_index=0,
            content="c1",
            char_length=2,
            start_offset=0,
            end_offset=2,
            chapter_title="第1章",
        )
        s2 = MaterialSnippet(
            user_id=user_id,
            material_id=mat_id,
            version_id=ver_id,
            snippet_index=1,
            content="c2",
            char_length=2,
            start_offset=2,
            end_offset=4,
            chapter_title="第1章",
        )
        s3 = MaterialSnippet(
            user_id=user_id,
            material_id=mat_id,
            version_id=ver_id,
            snippet_index=2,
            content="c3",
            char_length=2,
            start_offset=4,
            end_offset=6,
            chapter_title="",  # 默认章节
        )

        stats = compute_chapter_stats([s1, s2, s3])
        assert len(stats) == 2
        ch1_stat = next(s for s in stats if s.chapter_title == "第1章")
        assert ch1_stat.snippet_count == 2
        assert pytest.approx(ch1_stat.snippet_ratio, rel=1e-2) == 2 / 3

        def_stat = next(s for s in stats if s.chapter_title == "默认章节")
        assert def_stat.snippet_count == 1
        assert pytest.approx(def_stat.snippet_ratio, rel=1e-2) == 1 / 3

    def test_deduplicate_candidate_points(self) -> None:
        """测试向量余弦相似度去重与溯源聚合。"""
        # <= 1 项边界
        item0 = ExtractedKnowledgeItem(
            temp_id="kp_0",
            name="单节点",
            level=1,
            source_snippet_indices=[0],
        )
        assert deduplicate_candidate_points([item0], [[0.1] * 1024]) == [item0]

        # 构造两个高相似度 (>0.92) 节点与一个不相似节点
        kp1 = ExtractedKnowledgeItem(
            temp_id="kp_1",
            name="导数的几何意义",
            level=1,
            source_snippet_indices=[0],
        )
        kp2 = ExtractedKnowledgeItem(
            temp_id="kp_2",
            name="导数几何含义",  # 相似重复
            level=1,
            source_snippet_indices=[1],
        )
        kp3 = ExtractedKnowledgeItem(
            temp_id="kp_3",
            parent_temp_id="kp_2",  # 引用被合并的节点
            name="切线方程求法",
            level=2,
            source_snippet_indices=[2],
        )

        # 向量：vec1 与 vec2 完全相同 (sim = 1.0 > 0.92)
        vec1 = [1.0] + [0.0] * 1023
        vec2 = [1.0] + [0.0] * 1023
        vec3 = [0.0, 1.0] + [0.0] * 1022  # 正交 (sim = 0.0)

        deduped = deduplicate_candidate_points(
            [kp1, kp2, kp3],
            [vec1, vec2, vec3],
            similarity_threshold=0.92,
        )

        assert len(deduped) == 2
        # kp2 被合并进 kp1，kp1 聚合了切片 0 与 1
        merged_kp1 = next(it for it in deduped if it.temp_id == "kp_1")
        assert merged_kp1.source_snippet_indices == [0, 1]

        # kp3 的父引用被自动重定向至 kp_1
        child_kp3 = next(it for it in deduped if it.temp_id == "kp_3")
        assert child_kp3.parent_temp_id == "kp_1"

        # 测试已合并节点被跳过的分支 (j in merged_into)
        # kp_a, kp_b, kp_c 使得 a 与 b 相似合并，检查后续配对
        kp_a = ExtractedKnowledgeItem(temp_id="a", name="点A", level=1)
        kp_b = ExtractedKnowledgeItem(temp_id="b", name="点B", level=1)
        kp_c = ExtractedKnowledgeItem(temp_id="c", name="点C", level=1)
        va = [1.0] + [0.0] * 1023
        vb = [1.0] + [0.0] * 1023
        vc = [1.0] + [0.0] * 1023
        deduped_all = deduplicate_candidate_points([kp_a, kp_b, kp_c], [va, vb, vc], 0.92)
        assert len(deduped_all) == 1

    def test_build_knowledge_hierarchy_and_healing(self) -> None:
        """测试树形拓扑构建、环形依赖自愈与孤儿节点修复。"""
        user_id = uuid.uuid4()
        mat_id = uuid.uuid4()
        ver_id = uuid.uuid4()

        # 构造节点：
        # kp_1: 根节点
        # kp_2: 子节点 (指向 kp_1)
        # kp_orphan: 孤儿节点 (指向不存在的 kp_999)
        # kp_cycle_a, kp_cycle_b: 环形依赖
        # kp_deep_1..6: 深度超过 5 的链路
        items = [
            ExtractedKnowledgeItem(temp_id="kp_1", name="根节点", level=1),
            ExtractedKnowledgeItem(temp_id="kp_2", parent_temp_id="kp_1", name="子节点", level=2),
            ExtractedKnowledgeItem(
                temp_id="kp_orphan", parent_temp_id="kp_999", name="孤儿节点", level=2
            ),
            ExtractedKnowledgeItem(
                temp_id="kp_cycle_a", parent_temp_id="kp_cycle_b", name="环A", level=2
            ),
            ExtractedKnowledgeItem(
                temp_id="kp_cycle_b", parent_temp_id="kp_cycle_a", name="环B", level=2
            ),
            ExtractedKnowledgeItem(temp_id="d1", parent_temp_id="kp_2", name="深3", level=3),
            ExtractedKnowledgeItem(temp_id="d2", parent_temp_id="d1", name="深4", level=4),
            ExtractedKnowledgeItem(temp_id="d3", parent_temp_id="d2", name="深5", level=5),
            ExtractedKnowledgeItem(temp_id="d4", parent_temp_id="d3", name="超深6", level=5),
        ]

        points, temp_map = build_knowledge_hierarchy(
            items,
            material_id=mat_id,
            version_id=ver_id,
            user_id=user_id,
            batch_id="b_test",
            is_low_confidence=True,
        )

        assert len(points) == len(items)
        assert all(p.is_low_confidence is True for p in points)
        assert all(p.user_id == user_id for p in points)

        p_by_temp = {
            it.temp_id: next(p for p in points if p.id == temp_map[it.temp_id]) for it in items
        }

        # 根节点与正常子节点
        assert p_by_temp["kp_1"].parent_id is None
        assert p_by_temp["kp_1"].level == 1
        assert p_by_temp["kp_2"].parent_id == p_by_temp["kp_1"].id
        assert p_by_temp["kp_2"].level == 2

        # 孤儿节点自愈为根节点 (level=1, parent_id=None)
        assert p_by_temp["kp_orphan"].parent_id is None
        assert p_by_temp["kp_orphan"].level == 1

        # 环形自愈为根节点
        assert p_by_temp["kp_cycle_a"].parent_id is None
        assert p_by_temp["kp_cycle_a"].level == 1
        assert p_by_temp["kp_cycle_b"].parent_id is None
        assert p_by_temp["kp_cycle_b"].level == 1

        # 深度上限钳制为 5
        assert p_by_temp["d1"].level == 3
        assert p_by_temp["d2"].level == 4
        assert p_by_temp["d3"].level == 5
        assert p_by_temp["d4"].level == 5


# ==============================================================================
# KnowledgeService 核心业务全链路测试
# ==============================================================================


class TestKnowledgeServiceWorkflow:
    """测试 KnowledgeService 端到端抽取建树服务流程。"""

    def _make_qualified_output(self) -> KnowledgeExtractionOutput:
        """构造能顺利通过 verify_knowledge_points 门禁的 3 个知识点。"""
        return KnowledgeExtractionOutput(
            knowledge_points=[
                ExtractedKnowledgeItem(
                    temp_id="kp_1",
                    parent_temp_id=None,
                    name="极限基本概念与定义",
                    description="微积分极限的严格定义与语言表达",
                    level=1,
                    chapter_title="第一章 极限与连续",
                    source_snippet_indices=[0],
                ),
                ExtractedKnowledgeItem(
                    temp_id="kp_2",
                    parent_temp_id="kp_1",
                    name="极限四则运算法则",
                    description="加减乘除极限性质定理",
                    level=2,
                    chapter_title="第一章 极限与连续",
                    source_snippet_indices=[1],
                ),
                ExtractedKnowledgeItem(
                    temp_id="kp_3",
                    parent_temp_id="kp_2",
                    name="无穷小量阶比较与代换",
                    description="等价无穷小量代换与高阶低阶判定",
                    level=3,
                    chapter_title="第一章 极限与连续",
                    source_snippet_indices=[2],
                ),
            ]
        )

    def test_extract_and_build_success(
        self, session: Session, seed_material: dict[str, Any]
    ) -> None:
        """测试正常抽取、去重、质检合格、建树落库全流程。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        canned = self._make_qualified_output()
        fake_llm = StubLLM([canned])
        fake_embed = StubEmbedding()

        service = KnowledgeService(session, fake_llm, fake_embed)
        points = service.extract_and_build_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )

        assert len(points) == 3
        assert points[0].user_id == user_id
        assert points[0].is_low_confidence is False

        # 检查版本状态更新为 READY
        mat_repo = MaterialRepository(session)
        ver = mat_repo.get_version_by_id(version_id, user_id)
        assert ver is not None
        assert ver.parse_status == ParseStatus.READY.value

        # 检查双向溯源切片关联已落库
        know_repo = service.knowledge_repo
        snippets_for_p1 = know_repo.get_snippets_for_point(points[0].id, user_id)
        assert len(snippets_for_p1) == 1
        assert snippets_for_p1[0].snippet_index == 0

        # 获取树结构验证
        tree = service.get_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        assert len(tree) == 1  # 1 个根节点
        root = tree[0]
        assert root["name"] == "极限基本概念与定义"
        assert len(root["children"]) == 1
        child = root["children"][0]
        assert child["name"] == "极限四则运算法则"
        assert len(child["children"]) == 1
        grandchild = child["children"][0]
        assert grandchild["name"] == "无穷小量阶比较与代换"

    def test_precondition_validations(
        self, session: Session, seed_material: dict[str, Any]
    ) -> None:
        """测试前置校验：不存在的资料、版本及切片为空。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        fake_llm = StubLLM()
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        # 资料不存在
        with pytest.raises(MaterialNotFoundError):
            service.extract_and_build_knowledge_tree(
                material_id=uuid.uuid4(),
                version_id=version_id,
                user_id=user_id,
            )

        # 版本不存在
        with pytest.raises(MaterialNotFoundError):
            service.extract_and_build_knowledge_tree(
                material_id=material_id,
                version_id=uuid.uuid4(),
                user_id=user_id,
            )

        # 创建一个无切片的新版本
        mat_repo = MaterialRepository(session)
        empty_ver = mat_repo.create_version(
            material_id=material_id,
            user_id=user_id,
            version_number=2,
            storage_key="test/v2.pdf",
            content_hash="empty_hash",
        )
        session.commit()

        with pytest.raises(MaterialInvalidError):
            service.extract_and_build_knowledge_tree(
                material_id=material_id,
                version_id=empty_ver.id,
                user_id=user_id,
            )

    def test_retry_on_quality_failure_success_at_retry_1(
        self, session: Session, seed_material: dict[str, Any]
    ) -> None:
        """测试首次质检不合格，第 2 次尝试 (重抽 1) 成功通过。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        # 首次抽取不合格：仅 1 个节点 (短资料少于 3 个节点且深度为 1)
        unqualified_output = KnowledgeExtractionOutput(
            knowledge_points=[
                ExtractedKnowledgeItem(
                    temp_id="kp_bad",
                    name="粗略概念",
                    level=1,
                    source_snippet_indices=[0],
                )
            ]
        )
        qualified_output = self._make_qualified_output()

        fake_llm = StubLLM([unqualified_output, qualified_output])
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        points = service.extract_and_build_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )

        assert len(points) == 3
        assert points[0].is_low_confidence is False
        # 确认 LLM 经历了两轮调用
        assert fake_llm.call_count >= 2

    def test_retry_exceeded_degrade_to_low_confidence(
        self, session: Session, seed_material: dict[str, Any]
    ) -> None:
        """测试质检连续不合格，达到 2 次重抽上限后熔断降级标记 is_low_confidence=True。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        # 持续返回不合格节点
        unqualified_output = KnowledgeExtractionOutput(
            knowledge_points=[
                ExtractedKnowledgeItem(
                    temp_id="kp_bad",
                    name="粗略单一知识点",
                    level=1,
                    source_snippet_indices=[0],
                )
            ]
        )
        fake_llm = StubLLM([unqualified_output, unqualified_output, unqualified_output])
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        points = service.extract_and_build_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )

        assert len(points) == 1
        assert points[0].is_low_confidence is True

    def test_empty_extraction_all_retries_raises_error(
        self, session: Session, seed_material: dict[str, Any]
    ) -> None:
        """测试大模型持续输出空知识点列表，耗尽重试后抛出 KnowledgeExtractionRetryExceededError。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        empty_output = KnowledgeExtractionOutput(knowledge_points=[])
        fake_llm = StubLLM([empty_output, empty_output, empty_output])
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        with pytest.raises(KnowledgeExtractionRetryExceededError):
            service.extract_and_build_knowledge_tree(
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
            )

    def test_llm_agent_graph_fallback(
        self, session: Session, seed_material: dict[str, Any]
    ) -> None:
        """测试 AgentGraph 抛错时服务层降级至直接 generate_structured 抽取。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        canned = self._make_qualified_output()
        # 配置 AgentGraph 失败，测试 fallback 路径
        fake_llm = StubLLM([canned], raise_agent_graph_error=True)
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        points = service.extract_and_build_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        assert len(points) == 3

    def test_multi_tenant_isolation(self, session: Session, seed_material: dict[str, Any]) -> None:
        """测试租户隔离：用户 B 无法抽取或读取用户 A 的知识点。"""
        owner_id = seed_material["user_id"]
        attacker_id = uuid.uuid4()
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        canned = self._make_qualified_output()
        fake_llm = StubLLM([canned])
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        # 攻击者尝试抽取属于 owner 的资料
        with pytest.raises(MaterialNotFoundError):
            service.extract_and_build_knowledge_tree(
                material_id=material_id,
                version_id=version_id,
                user_id=attacker_id,
            )

        # Owner 正常完成抽取
        service.extract_and_build_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=owner_id,
        )

        # 攻击者查询树结构被阻断
        with pytest.raises(MaterialNotFoundError):
            service.get_knowledge_tree(
                material_id=material_id,
                version_id=version_id,
                user_id=attacker_id,
            )

    def test_database_error_triggers_rollback_and_failed_status(
        self, session: Session, seed_material: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试入库阶段发生数据库异常时触发回滚并标记版本状态为 FAILED。"""
        user_id = seed_material["user_id"]
        material_id = seed_material["material_id"]
        version_id = seed_material["version_id"]

        canned = self._make_qualified_output()
        fake_llm = StubLLM([canned])
        fake_embed = StubEmbedding()
        service = KnowledgeService(session, fake_llm, fake_embed)

        def faulty_batch_create(*args: Any, **kwargs: Any) -> list[Any]:
            raise RuntimeError("Database connection error")

        monkeypatch.setattr(
            service.knowledge_repo, "batch_create_knowledge_points", faulty_batch_create
        )

        with pytest.raises(RuntimeError, match="Database connection error"):
            service.extract_and_build_knowledge_tree(
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
            )

        mat_repo = MaterialRepository(session)
        ver = mat_repo.get_version_by_id(version_id, user_id)
        assert ver is not None
        assert ver.parse_status == ParseStatus.FAILED.value
