"""Unit tests for deterministic KP dedup, cross-batch outline passing, and structured_content."""

import json
import uuid
from collections.abc import Generator, Sequence
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.algorithms.knowledge_tree import (
    ExtractedKnowledgeItem,
    KnowledgeExtractionOutput,
    deduplicate_candidate_points,
    normalize_kp_name,
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
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.schemas.folder import FolderKnowledgePointItem
from app.schemas.knowledge import KnowledgePointDetailResponse, KnowledgeTreeNodeResponse
from app.services.knowledge import KnowledgeService

T = TypeVar("T", bound=BaseModel)


class _MultiBatchOutlineCapturingLLM(LLMProtocol):
    """Stub LLM recording prompts across batches and emitting structured KP fields."""

    def __init__(self) -> None:
        self.user_prompts: list[str] = []
        self.system_prompts: list[str] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="{}", model="stub", usage=LLMUsage())

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        self.system_prompts.append(messages[0].content)
        self.user_prompts.append(messages[-1].content)
        call_idx = len(self.user_prompts)
        if call_idx == 1:
            items = [
                ExtractedKnowledgeItem(
                    temp_id="b1_kp_1",
                    parent_temp_id=None,
                    name="线性空间定义",
                    description="线性空间与运算封闭性核心定义描述。",
                    core_summary="满足加法与数乘封闭性的集合结构。",
                    key_takeaways=["加法结合律与交换律", "零元与负元存在"],
                    key_formulas=["$\\alpha + \\beta \\in V$", "$k\\alpha \\in V$"],
                    boundary_notes=["数域必须事先给定"],
                    level=1,
                    chapter_title="第一章 线性空间",
                    source_snippet_indices=[0],
                ),
                ExtractedKnowledgeItem(
                    temp_id="b1_kp_2",
                    parent_temp_id="b1_kp_1",
                    name="零元与负元唯一性",
                    description="由群公理直接推导零元和负元的唯一性结论。",
                    core_summary="任意线性空间中零元和负元均唯一存在。",
                    key_takeaways=["反证法证明唯一性"],
                    level=2,
                    chapter_title="第一章 线性空间",
                    source_snippet_indices=[1],
                ),
            ]
        else:
            items = [
                ExtractedKnowledgeItem(
                    temp_id="b2_kp_1",
                    parent_temp_id="b1_kp_1",
                    name="线性相关与线性无关",
                    description="向量组线性相关性的等价判定准则。",
                    core_summary="不全为零的系数线性组合为零即线性相关。",
                    key_takeaways=["齐次方程存在非零解等价于相关"],
                    key_formulas=["$\\sum k_i \\alpha_i = 0$"],
                    boundary_notes=["零向量单独构成相关组"],
                    level=2,
                    chapter_title="第一章 线性空间",
                    source_snippet_indices=[2],
                ),
                ExtractedKnowledgeItem(
                    temp_id="b2_kp_2",
                    parent_temp_id="b1_kp_2",
                    name="极大线性无关组与维数",
                    description="极大线性无关组个数确定线性空间的维数与基底。",
                    core_summary="任意基底向量数量相等且等于空间维数。",
                    key_takeaways=["任意两个极大无关组等价"],
                    level=3,
                    chapter_title="第一章 线性空间",
                    source_snippet_indices=[3],
                ),
            ]
        output = KnowledgeExtractionOutput(knowledge_points=items)
        return response_model.model_validate(output.model_dump()), LLMResponse(
            content=json.dumps(output.model_dump(), ensure_ascii=False),
            model="stub",
            usage=LLMUsage(),
        )


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def test_deterministic_name_dedup_runs_before_vector_dedup_and_redirects_children() -> None:
    """Exact normalized-name duplicates merge metadata and redirect child parent_temp_ids."""
    assert normalize_kp_name("  Newton  Second-Law (F=ma) ") == "newtonsecondlawf=ma"

    items = [
        ExtractedKnowledgeItem(
            temp_id="kp_1",
            parent_temp_id=None,
            name="  Gauss-Jordan Elimination ",
            core_summary="用初等行变换化简增广矩阵为最简行阶梯形。",
            key_takeaways=["只允许使用行变换"],
            key_formulas=["$[A|b] \\to [I|x]$"],
            boundary_notes=["注意零行判定无解"],
            level=1,
            source_snippet_indices=[0],
        ),
        ExtractedKnowledgeItem(
            temp_id="kp_2",
            parent_temp_id=None,
            name="gauss jordan elimination",
            core_summary="",
            key_takeaways=["可同时求逆矩阵", "只允许使用行变换"],
            key_formulas=["$[A|I] \\to [I|A^{-1}]$"],
            boundary_notes=["奇异矩阵无法化为单位阵"],
            level=1,
            source_snippet_indices=[2],
        ),
        ExtractedKnowledgeItem(
            temp_id="kp_3",
            parent_temp_id="kp_2",
            name="主元选取策略",
            core_summary="列主元消去降低舍入误差。",
            level=2,
            source_snippet_indices=[3],
        ),
    ]
    # Orthogonal embeddings guarantee vector cosine < 0.92; merge must still happen via name!
    orthogonal_embeddings: list[Sequence[float]] = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]

    deduped = deduplicate_candidate_points(items, orthogonal_embeddings, similarity_threshold=0.92)
    assert len(deduped) == 2

    merged_parent = deduped[0]
    assert merged_parent.temp_id == "kp_1"
    assert merged_parent.source_snippet_indices == [0, 2]
    assert merged_parent.key_takeaways == ["只允许使用行变换", "可同时求逆矩阵"]
    assert merged_parent.key_formulas == ["$[A|b] \\to [I|x]$", "$[A|I] \\to [I|A^{-1}]$"]
    assert merged_parent.boundary_notes == ["注意零行判定无解", "奇异矩阵无法化为单位阵"]

    child = deduped[1]
    assert child.temp_id == "kp_3"
    assert child.parent_temp_id == "kp_1"


def test_extract_and_build_tree_passes_cross_batch_outline_and_persists_structured_content(
    session: Session,
) -> None:
    """Multi-batch extraction passes outline skeleton, sets structured_content & sort_order."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    material = Material(
        id=material_id,
        user_id=user_id,
        title="高等代数精讲",
        file_format="pdf",
        file_size=2048,
    )
    version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/algebra.pdf",
        content_hash="alg_hash",
    )
    snippet_texts = [
        "第一章 线性空间引入向量加法和数乘两条运算，并要求满足八条运算律及封闭性条件。" * 18,
        "零元与负元在任意线性空间中唯一存在，可用抽象向量公理严格推导证明。" * 18,
        "线性相关性指存在不全为零的标量系数使向量组线性组合为零向量。" * 18,
        "极大线性无关组确定了向量空间的维数与基底构造的基础方法。" * 18,
    ]
    snippets = [
        MaterialSnippet(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=idx,
            content=text,
            char_length=len(text),
            start_offset=idx * 60,
            end_offset=idx * 60 + len(text),
            chapter_title="第一章 线性空间",
        )
        for idx, text in enumerate(snippet_texts)
    ]
    session.add_all([material, version, *snippets])
    session.commit()

    llm = _MultiBatchOutlineCapturingLLM()
    service = KnowledgeService(
        session=session,
        llm=llm,
        embedding=FakeEmbeddingAdapter(),
    )
    created = service.extract_and_build_knowledge_tree(
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        batch_size=2,
    )

    # Batch 1 did not have outline; Batch 2 received Batch 1 skeleton
    assert len(llm.user_prompts) == 2
    assert "已抽取知识点骨架" not in llm.user_prompts[0]
    assert "已抽取知识点骨架" in llm.user_prompts[1]
    assert "b1_kp_1" in llm.user_prompts[1]
    assert "线性空间定义" in llm.user_prompts[1]
    # System prompt explicitly forbids fabricating exam frequency / importance
    assert "高频" in llm.system_prompts[0]
    assert "严禁" in llm.system_prompts[0]

    assert len(created) == 4
    ordered = sorted(created, key=lambda item: item.sort_order)
    assert [kp.sort_order for kp in ordered] == [0, 1, 2, 3]

    first = ordered[0]
    assert first.structured_content is not None
    assert set(first.structured_content.keys()) == {
        "core_summary",
        "key_takeaways",
        "key_formulas",
        "boundary_notes",
    }
    serialized = json.dumps(first.structured_content, ensure_ascii=False)
    assert "高频" not in serialized
    assert "必考" not in serialized

    # Tree and schemas expose structured_content and sort_order cleanly
    tree = service.get_knowledge_tree(material_id=material_id, user_id=user_id)
    root_node = KnowledgeTreeNodeResponse.model_validate(tree[0])
    assert root_node.structured_content == first.structured_content
    assert root_node.sort_order == 0

    detail_dto = KnowledgePointDetailResponse.model_validate(first)
    assert detail_dto.structured_content == first.structured_content
    assert detail_dto.sort_order == 0

    # Folder item schema coerces None sort_order cleanly to 0
    folder_payload: dict[str, Any] = {
        "id": first.id,
        "material_id": material_id,
        "material_title": "高等代数精讲",
        "name": first.name,
        "description": first.description,
        "structured_content": first.structured_content,
        "sort_order": None,
        "level": first.level,
        "mastery_score": 0.0,
        "mastery_level": "unlearned",
        "question_count": 0,
    }
    folder_item = FolderKnowledgePointItem.model_validate(folder_payload)
    assert folder_item.sort_order == 0
    assert folder_item.structured_content == first.structured_content
