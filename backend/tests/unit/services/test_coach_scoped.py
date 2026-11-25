"""ask_scoped_coach 的 Adaptive RAG 行为测试（离线 SQLite + Fake/Scripted 适配器）。

覆盖：thread_id 会话记忆（隔离/无状态/无记忆库）、摘录整洁裁剪、概览意图、
KP 范围前缀不破坏寒暄判定、课程范围标题参与查询改写、范围兜底。
"""

import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps.auth import get_current_user
from app.api.deps.question import get_question_service
from app.api.v1.questions import router as questions_router
from app.core.errors import LLMResponseFormatError, SearchError
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.coach_graph import (
    CoachDraft,
    CoachGeneralDraft,
    CoachOverviewDraft,
    RewrittenQuery,
)
from app.integrations.llm.coach_memory import CoachSessionMemory
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.integrations.rerank.protocol import RerankItem
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.pgvector import PgvectorHybridSearchAdapter
from app.integrations.search.protocol import SearchOptions, SearchResult, SearchSnippetCandidate
from app.main import validation_error_handler
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialFolder, MaterialSnippet, MaterialVersion
from app.models.practice import MasteryLevel, MasteryRecord
from app.models.user import User
from app.repositories.question import QuestionRepository
from app.schemas.question import AskCoachHistoryItem, ScopedCoachRequest
from app.services.question import QuestionService

# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class ScriptedLLM(LLMProtocol):
    """按 response_model 排队返回结构化结果并记录每次调用的消息。"""

    def __init__(self) -> None:
        self.queues: dict[type[BaseModel], list[BaseModel]] = {}
        self.calls: list[tuple[type[BaseModel], Sequence[LLMMessage]]] = []

    def push(self, *responses: BaseModel) -> None:
        for response in responses:
            self.queues.setdefault(type(response), []).append(response)

    def calls_for(self, model: type[BaseModel]) -> list[Sequence[LLMMessage]]:
        return [messages for response_model, messages in self.calls if response_model is model]

    def generate(
        self, messages: Sequence[LLMMessage], options: LLMOptions | None = None
    ) -> LLMResponse:
        raise AssertionError("coach must only use generate_structured")

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[Any],
        options: LLMOptions | None = None,
    ) -> tuple[Any, LLMResponse]:
        self.calls.append((response_model, messages))
        queue = self.queues.get(response_model)
        if not queue:
            raise AssertionError(f"unexpected LLM call for {response_model.__name__}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        usage = LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        return item, LLMResponse(content="{}", usage=usage, model="scripted")


class RecordingSearch(FakeSearchAdapter):
    """记录每次检索的 query 与 options。"""

    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str] = []
        self.options: list[SearchOptions | None] = []

    def search(
        self,
        query: str,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        options: SearchOptions | None = None,
    ) -> SearchResult:
        self.queries.append(query)
        self.options.append(options)
        return super().search(query, user_id, material_id, version_id, options)


class ScriptedRerank:
    """按调用序返回固定最高分的精排替身（其余文档递减）。"""

    def __init__(self, *top_scores: float) -> None:
        self.top_scores = list(top_scores)
        self.calls = 0

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int | None = None
    ) -> list[RerankItem]:
        top = self.top_scores[min(self.calls, len(self.top_scores) - 1)]
        self.calls += 1
        items = [
            RerankItem(index=i, relevance_score=max(top - 0.01 * i, 0.0))
            for i in range(len(documents))
        ]
        return items[:top_n] if top_n is not None else items


# ---------------------------------------------------------------------------
# 数据装配
# ---------------------------------------------------------------------------


@dataclass
class Seed:
    user_id: uuid.UUID
    material_id: uuid.UUID
    version_id: uuid.UUID
    snippet_ids: list[uuid.UUID]
    point_ids: list[uuid.UUID]
    folder_id: uuid.UUID | None = None


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as sess:
        yield sess
    engine.dispose()


def seed_user(session: Session) -> uuid.UUID:
    user_id = uuid.uuid4()
    session.add(User(id=user_id, openid=f"openid-{user_id}"))
    session.commit()
    return user_id


def seed_material(
    session: Session,
    user_id: uuid.UUID,
    *,
    title: str = "敏捷实践.pdf",
    folder_id: uuid.UUID | None = None,
    status: str = "ready",
    contents: Sequence[str] = ("敏捷开发以人为本。",),
    points: Sequence[tuple[str, dict[str, Any] | None]] = (("敏捷核心理念", None),),
) -> Seed:
    """创建资料 + 当前版本 + 切片 + 知识点（首个知识点关联全部切片，其余为其子点）。"""
    material_id, version_id = uuid.uuid4(), uuid.uuid4()
    session.add(
        Material(
            id=material_id,
            user_id=user_id,
            title=title,
            file_format="pdf",
            file_size=1,
            folder_id=folder_id,
        )
    )
    session.flush()
    session.add(
        MaterialVersion(
            id=version_id,
            user_id=user_id,
            material_id=material_id,
            version_number=1,
            storage_key=f"k/{version_id}",
            content_hash=f"h-{version_id}",
        )
    )
    session.flush()
    material = session.get(Material, material_id)
    assert material is not None
    material.current_version_id = version_id
    material.status = status
    snippet_ids: list[uuid.UUID] = []
    for index, content in enumerate(contents):
        snippet_id = uuid.uuid4()
        snippet_ids.append(snippet_id)
        session.add(
            MaterialSnippet(
                id=snippet_id,
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                snippet_index=index,
                content=content,
                char_length=len(content),
                start_offset=index * 10,
                end_offset=index * 10 + 10,
                chapter_title="第一章",
            )
        )
    point_ids: list[uuid.UUID] = []
    for order, (name, structured) in enumerate(points):
        point_id = uuid.uuid4()
        point_ids.append(point_id)
        session.add(
            KnowledgePoint(
                id=point_id,
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=point_ids[0] if order > 0 else None,
                name=name,
                description=f"{name}的描述",
                structured_content=structured,
                level=1 if order == 0 else 2,
                sort_order=order,
                batch_id="b1",
            )
        )
    session.flush()
    for snippet_id in snippet_ids:
        if point_ids:
            session.add(
                KnowledgePointSnippet(
                    user_id=user_id, knowledge_point_id=point_ids[0], snippet_id=snippet_id
                )
            )
    session.commit()
    return Seed(user_id, material_id, version_id, snippet_ids, point_ids, folder_id)


def cand(seed: Seed, index: int, content: str, **kwargs: Any) -> SearchSnippetCandidate:
    return SearchSnippetCandidate(
        snippet_id=seed.snippet_ids[index],
        material_id=seed.material_id,
        version_id=seed.version_id,
        content=content,
        chapter_title="第一章",
        source_info=kwargs.pop("source_info", {"page_number": 1}),
        vector_score=kwargs.pop("vector_score", 0.8),
        final_score=kwargs.pop("final_score", 0.02),
        snippet_index=index,
        **kwargs,
    )


def make_service(
    session: Session,
    llm: LLMProtocol,
    search: FakeSearchAdapter | None,
    *,
    memory: CoachSessionMemory | None = None,
    reranker: Any | None = None,
) -> QuestionService:
    return QuestionService(
        session=session,
        llm=llm,
        embedding=FakeEmbeddingAdapter(),
        search_adapter=search,
        reranker=reranker,
        memory_store=memory,
    )


def user_text(messages: Sequence[LLMMessage]) -> str:
    return "\n".join(m.content for m in messages if m.role == "user" and isinstance(m.content, str))


def grounded_llm(seed: Seed, *replies: str) -> ScriptedLLM:
    llm = ScriptedLLM()
    llm.push(*[CoachDraft(reply=r, citation_ids=[seed.snippet_ids[0]]) for r in replies])
    return llm


# ---------------------------------------------------------------------------
# thread_id 会话记忆
# ---------------------------------------------------------------------------


class TestThreadMemory:
    def _service(
        self, session: Session, seed: Seed, memory: CoachSessionMemory | None
    ) -> tuple[QuestionService, ScriptedLLM, RecordingSearch]:
        search = RecordingSearch()
        search.set_canned_candidates([cand(seed, 0, "敏捷开发以人为本。")])
        llm = grounded_llm(seed, "第一轮回答：敏捷以人为本。", "第二轮回答：Scrum 有三种角色。")
        return make_service(session, llm, search, memory=memory), llm, search

    def test_second_turn_sees_first_turn(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        memory = CoachSessionMemory()
        service, llm, search = self._service(session, seed, memory)

        first = service.ask_scoped_coach(
            user_id=seed.user_id,
            material_id=seed.material_id,
            user_prompt="什么是敏捷开发？",
            thread_id="t-1",
        )
        second = service.ask_scoped_coach(
            user_id=seed.user_id,
            material_id=seed.material_id,
            user_prompt="那Scrum呢？",
            thread_id="t-1",
        )

        assert first.reply.startswith("第一轮")
        assert second.reply.startswith("第二轮")
        prompts = [user_text(m) for m in llm.calls_for(CoachDraft)]
        assert "此前对话" not in prompts[0]
        assert "什么是敏捷开发？" in prompts[1]
        assert "第一轮回答：敏捷以人为本。" in prompts[1]
        # 短追问被拼上上一轮提问用于检索
        assert "什么是敏捷开发？" in search.queries[1]

    def test_different_threads_do_not_share_history(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        service, llm, _ = self._service(session, seed, CoachSessionMemory())
        for thread in ("a", "b"):
            service.ask_scoped_coach(
                user_id=seed.user_id,
                material_id=seed.material_id,
                user_prompt="什么是敏捷开发？",
                thread_id=thread,
            )
        assert all("此前对话" not in user_text(m) for m in llm.calls_for(CoachDraft))

    def test_different_scope_same_thread_isolated(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        service, llm, _ = self._service(session, seed, CoachSessionMemory())
        service.ask_scoped_coach(
            user_id=seed.user_id,
            material_id=seed.material_id,
            user_prompt="什么是敏捷开发？",
            thread_id="shared",
        )
        service.ask_scoped_coach(
            user_id=seed.user_id,
            knowledge_point_id=seed.point_ids[0],
            user_prompt="什么是敏捷开发？",
            thread_id="shared",
        )
        assert all("此前对话" not in user_text(m) for m in llm.calls_for(CoachDraft))

    def test_different_user_same_thread_isolated(self, session: Session) -> None:
        user_a, user_b = seed_user(session), seed_user(session)
        seed_a = seed_material(session, user_a)
        seed_b = seed_material(session, user_b)
        memory = CoachSessionMemory()
        search = RecordingSearch()
        search.set_canned_candidates([cand(seed_a, 0, "A 的内容"), cand(seed_b, 0, "B 的内容")])
        llm = ScriptedLLM()
        llm.push(
            CoachDraft(reply="A 的机密回复", citation_ids=[seed_a.snippet_ids[0]]),
            CoachDraft(reply="B 的回复", citation_ids=[seed_b.snippet_ids[0]]),
        )
        service = make_service(session, llm, search, memory=memory)
        service.ask_scoped_coach(
            user_id=user_a, material_id=seed_a.material_id, user_prompt="问题甲", thread_id="same"
        )
        service.ask_scoped_coach(
            user_id=user_b, material_id=seed_b.material_id, user_prompt="问题乙", thread_id="same"
        )
        prompt_b = user_text(llm.calls_for(CoachDraft)[1])
        assert "A 的机密回复" not in prompt_b and "问题甲" not in prompt_b

    def test_no_thread_id_is_stateless(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        memory = CoachSessionMemory()
        service, llm, _ = self._service(session, seed, memory)
        for _ in range(2):
            service.ask_scoped_coach(
                user_id=seed.user_id, material_id=seed.material_id, user_prompt="什么是敏捷开发？"
            )
        assert all("此前对话" not in user_text(m) for m in llm.calls_for(CoachDraft))
        assert memory._local == {}

    def test_thread_id_without_memory_store_still_works(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        service, llm, _ = self._service(session, seed, None)
        for _ in range(2):
            result = service.ask_scoped_coach(
                user_id=seed.user_id,
                material_id=seed.material_id,
                user_prompt="什么是敏捷开发？",
                thread_id="t",
            )
            assert result.sources
        assert all("此前对话" not in user_text(m) for m in llm.calls_for(CoachDraft))

    def test_turn_recorded_in_memory(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        memory = CoachSessionMemory()
        service, _, _ = self._service(session, seed, memory)
        service.ask_scoped_coach(
            user_id=seed.user_id,
            material_id=seed.material_id,
            user_prompt="什么是敏捷开发？",
            thread_id="rec",
        )
        key = f"{seed.user_id}:mat:{seed.material_id}:rec"
        turns = memory.load(key)
        assert [(t.user, t.assistant) for t in turns] == [
            ("什么是敏捷开发？", "第一轮回答：敏捷以人为本。")
        ]


# ---------------------------------------------------------------------------
# 摘录整洁裁剪
# ---------------------------------------------------------------------------


class TestExcerpt:
    def _ask(self, session: Session, content: str) -> str:
        seed = seed_material(session, seed_user(session), contents=[content])
        search = RecordingSearch()
        search.set_canned_candidates([cand(seed, 0, content)])
        service = make_service(session, grounded_llm(seed, "回答"), search)
        result = service.ask_scoped_coach(
            user_id=seed.user_id, material_id=seed.material_id, user_prompt="解释一下公式"
        )
        assert len(result.sources) == 1
        return result.sources[0].excerpt

    def test_short_snippet_returned_verbatim(self, session: Session) -> None:
        assert self._ask(session, "短内容，$a+b$。") == "短内容，$a+b$。"

    def test_long_snippet_cut_at_sentence_boundary(self, session: Session) -> None:
        sentence = "敏捷开发强调个体与互动。"
        excerpt = self._ask(session, sentence * 60)
        assert len(excerpt) <= 480
        assert excerpt.endswith("…")
        assert excerpt[:-1].endswith("。")

    def test_never_cut_inside_formula(self, session: Session) -> None:
        sentence = "敏捷开发强调个体与互动。"
        formula = "$" + "+".join(f"a{i}" for i in range(40)) + "$"  # 约 160 字符，跨越 480 边界
        content = sentence * 37 + formula + "成立。" + sentence * 10
        excerpt = self._ask(session, content)
        assert len(excerpt) <= 480
        assert excerpt.count("$") % 2 == 0
        assert "…" in excerpt
        assert "a0+a1" not in excerpt  # 公式整体被回退到起点之前

    def test_formula_kept_whole_when_it_fits(self, session: Session) -> None:
        sentence = "敏捷开发强调个体与互动。"
        content = sentence * 30 + "速度公式 $v=\\frac{s}{t}$ 成立。" + sentence * 30
        excerpt = self._ask(session, content)
        assert len(excerpt) <= 480
        assert excerpt.count("$") % 2 == 0
        assert "$v=\\frac{s}{t}$" in excerpt


# ---------------------------------------------------------------------------
# 意图：概览 / 寒暄 / 兜底
# ---------------------------------------------------------------------------

STRUCTURED = {
    "core_summary": "以人为本的迭代式开发方法",
    "key_takeaways": ["拥抱变化", "持续交付"],
    "key_formulas": ["$v=s/t$"],
}


class TestIntents:
    def _forbid_search(self, seed: Seed) -> RecordingSearch:
        search = RecordingSearch()
        search.set_canned_candidates([cand(seed, 0, "内容")])
        search.set_fault_injection("search", AssertionError("search must not be called"))
        return search

    def test_overview_intent_uses_structured_points_without_search(self, session: Session) -> None:
        seed = seed_material(
            session,
            seed_user(session),
            points=[("敏捷核心理念", STRUCTURED), ("Scrum 角色", {"core_summary": "三种角色"})],
        )
        llm = ScriptedLLM()
        llm.push(CoachOverviewDraft(reply="本章包含两大考点。", suggestions=["讲讲 Scrum"]))
        service = make_service(session, llm, self._forbid_search(seed))

        result = service.ask_scoped_coach(
            user_id=seed.user_id, material_id=seed.material_id, user_prompt="帮我梳理本章重点"
        )

        assert result.reply == "本章包含两大考点。"
        assert result.sources == []
        assert result.suggestions == ["讲讲 Scrum"]
        assert [m for m, _ in llm.calls] == [CoachOverviewDraft]
        prompt = user_text(llm.calls[0][1])
        assert "【知识点梳理】" in prompt
        assert "敏捷核心理念" in prompt and "以人为本的迭代式开发方法" in prompt
        assert "拥抱变化" in prompt and "$v=s/t$" in prompt
        assert "Scrum 角色" in prompt

    def test_overview_pattern_without_points_falls_back_to_detail_qa(
        self, session: Session
    ) -> None:
        seed = seed_material(session, seed_user(session), points=[])
        search = RecordingSearch()
        search.set_canned_candidates([cand(seed, 0, "资料中的重点内容。")])
        llm = grounded_llm(seed, "依据资料的回答")
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=seed.user_id, material_id=seed.material_id, user_prompt="帮我梳理本章重点"
        )

        assert result.reply == "依据资料的回答"
        assert len(search.queries) == 1
        assert [m for m, _ in llm.calls] == [CoachDraft]

    def test_kp_scope_prefix_does_not_break_chitchat(self, session: Session) -> None:
        seed = seed_material(
            session,
            seed_user(session),
            points=[("敏捷核心理念", None), ("Scrum 角色", None), ("看板方法", None)],
        )
        search = self._forbid_search(seed)
        llm = ScriptedLLM()
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=seed.user_id, knowledge_point_id=seed.point_ids[0], user_prompt="你好呀"
        )

        assert "助教" in result.reply
        assert result.sources == []
        assert llm.calls == []  # 寒暄零 LLM 调用
        assert search.queries == []  # 零检索
        assert result.suggestions == [
            "讲讲「敏捷核心理念」",
            "讲讲「Scrum 角色」",
            "讲讲「看板方法」",
        ]

    def test_kp_scope_query_gets_prefix_and_pushes_allowed_ids(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session), contents=["敏捷开发以人为本。", "无关"])
        search = RecordingSearch()
        search.set_canned_candidates([cand(seed, 0, "敏捷开发以人为本。"), cand(seed, 1, "无关")])
        # KP 仅关联首个知识点的全部切片；此处再取消第二个切片的关联以验证白名单下推
        session.execute(
            delete(KnowledgePointSnippet).where(
                KnowledgePointSnippet.snippet_id == seed.snippet_ids[1]
            )
        )
        session.commit()
        llm = grounded_llm(seed, "回答")
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=seed.user_id,
            knowledge_point_id=seed.point_ids[0],
            user_prompt="敏捷强调什么",
        )

        assert search.queries == ["关于知识点「敏捷核心理念」：敏捷强调什么"]
        options = search.options[0]
        assert options is not None
        assert options.allowed_snippet_ids == (seed.snippet_ids[0],)
        assert [s.snippet_id for s in result.sources] == [seed.snippet_ids[0]]

    def test_no_evidence_gives_honest_fallback_with_topics(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session), points=[("敏捷核心理念", None)])
        search = RecordingSearch()  # 无任何候选
        llm = ScriptedLLM()
        llm.push(RewrittenQuery(query="敏捷 改写"))
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=seed.user_id, material_id=seed.material_id, user_prompt="量子纠缠是什么"
        )

        assert "没找到" in result.reply
        assert result.sources == []
        assert result.suggestions == ["讲讲「敏捷核心理念」"]
        assert len(search.queries) == 2  # 首检 + 一次改写后重检
        assert search.queries[1] == "敏捷 改写"
        assert [m for m, _ in llm.calls] == [RewrittenQuery]  # 仅一次改写，无生成调用


# ---------------------------------------------------------------------------
# 课程范围、改写与兜底
# ---------------------------------------------------------------------------


class TestFolderScope:
    def test_folder_title_in_rewrite_and_multi_material_search(self, session: Session) -> None:
        user_id = seed_user(session)
        folder_id = uuid.uuid4()
        session.add(MaterialFolder(id=folder_id, user_id=user_id, name="软件工程课"))
        session.commit()
        first = seed_material(session, user_id, title="一.pdf", folder_id=folder_id)
        second = seed_material(session, user_id, title="二.pdf", folder_id=folder_id)

        search = RecordingSearch()
        search.set_canned_candidates([cand(first, 0, "敏捷开发以人为本。")])
        llm = ScriptedLLM()
        llm.push(
            RewrittenQuery(query="敏捷开发 角色 Scrum"),
            CoachDraft(reply="Scrum 有三种角色。", citation_ids=[first.snippet_ids[0]]),
        )
        reranker = ScriptedRerank(0.3, 0.9)  # 首轮低于改写阈值 0.45 → 触发一次改写
        service = make_service(session, llm, search, reranker=reranker)

        result = service.ask_scoped_coach(
            user_id=user_id, folder_id=folder_id, user_prompt="Scrum 里谁负责排优先级呢"
        )

        assert result.reply == "Scrum 有三种角色。"
        assert [s.snippet_id for s in result.sources] == [first.snippet_ids[0]]
        rewrite_prompt = user_text(llm.calls_for(RewrittenQuery)[0])
        assert "学习范围：软件工程课" in rewrite_prompt
        assert len(search.queries) == 2
        assert search.queries[1] == "敏捷开发 角色 Scrum"
        assert search.options[0] is not None
        assert set(search.options[0].allowed_version_ids or ()) == {
            first.version_id,
            second.version_id,
        }
        assert reranker.calls == 2
        assert second.material_id != first.material_id

    def test_folder_chitchat_uses_folder_point_topics(self, session: Session) -> None:
        user_id = seed_user(session)
        folder_id = uuid.uuid4()
        session.add(MaterialFolder(id=folder_id, user_id=user_id, name="算法课"))
        session.commit()
        seed_material(session, user_id, folder_id=folder_id, points=[("动态规划", None)])
        llm = ScriptedLLM()
        service = make_service(session, llm, RecordingSearch())

        result = service.ask_scoped_coach(user_id=user_id, folder_id=folder_id, user_prompt="谢谢")

        assert llm.calls == []
        assert result.suggestions == ["讲讲「动态规划」"]


class TestScopeEdges:
    def test_not_ready_material_returns_hint_without_calls(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session), status="parsing")
        llm = ScriptedLLM()
        search = RecordingSearch()
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=seed.user_id, material_id=seed.material_id, user_prompt="问题"
        )

        assert "没有已解析完成的资料" in result.reply
        assert llm.calls == [] and search.queries == []

    def test_missing_search_adapter_raises(self, session: Session) -> None:
        seed = seed_material(session, seed_user(session))
        service = make_service(session, ScriptedLLM(), None)
        with pytest.raises(SearchError):
            service.ask_scoped_coach(
                user_id=seed.user_id, material_id=seed.material_id, user_prompt="问题"
            )

    def test_no_scope_normalizes_to_global_and_explicit_missing_id_rejected(
        self, session: Session
    ) -> None:
        llm = ScriptedLLM()
        llm.push(CoachGeneralDraft(reply="以上结合通用学科知识解答：时间复杂度衡量算法增长阶。"))
        search = RecordingSearch()
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(user_id=uuid.uuid4(), user_prompt="什么是时间复杂度？")

        assert result.mode == "general"
        assert result.sources == []
        assert "时间复杂度" in result.reply
        assert search.queries == []

        with pytest.raises(ValueError, match="课程模式必须指定 folder_id"):
            service.ask_scoped_coach(user_id=uuid.uuid4(), scope="folder", user_prompt="问题")
        with pytest.raises(ValueError, match="资料模式必须指定 material_id"):
            service.ask_scoped_coach(user_id=uuid.uuid4(), scope="material", user_prompt="问题")
        with pytest.raises(ValueError, match="考点模式必须指定 knowledge_point_id"):
            service.ask_scoped_coach(
                user_id=uuid.uuid4(), scope="knowledge_point", user_prompt="问题"
            )


class TestScopedCoachContractAndGlobal:
    def test_request_schema_scope_normalization_and_422_matrix(self) -> None:
        req_default = ScopedCoachRequest(user_prompt="什么是梯度下降？")
        assert req_default.scope == "global"
        assert req_default.history == []

        req_explicit = ScopedCoachRequest(
            scope="global",
            user_prompt="今天复习什么？",
            history=[AskCoachHistoryItem(role="user", content="你好")],
        )
        assert req_explicit.scope == "global"
        assert len(req_explicit.history) == 1

        for bad_kwargs in (
            {"scope": "folder", "user_prompt": "问题"},
            {"scope": "material", "user_prompt": "问题"},
            {"scope": "knowledge_point", "user_prompt": "问题"},
            {"scope": "global", "folder_id": uuid.uuid4(), "user_prompt": "问题"},
            {
                "folder_id": uuid.uuid4(),
                "material_id": uuid.uuid4(),
                "user_prompt": "问题",
            },
        ):
            with pytest.raises(ValidationError):
                ScopedCoachRequest(**bad_kwargs)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_coach_ask_endpoint_returns_422_for_explicit_scope_missing_id(
        self,
    ) -> None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as thread_session:
            user_id = seed_user(thread_session)
            app = FastAPI()
            app.include_router(questions_router, prefix="/api/v1")
            app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
            app.dependency_overrides[get_current_user] = lambda: User(id=user_id, openid="wx-test")
            service = make_service(thread_session, ScriptedLLM(), RecordingSearch())
            app.dependency_overrides[get_question_service] = lambda: service

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                bad_resp = await client.post(
                    "/api/v1/coach/ask",
                    json={"scope": "folder", "user_prompt": "梳理重点"},
                )
                assert bad_resp.status_code == 422

                ok_resp = await client.post(
                    "/api/v1/coach/ask",
                    json={"user_prompt": "你好"},
                )
                assert ok_resp.status_code == 200
                assert ok_resp.json()["mode"] == "chitchat"
        engine.dispose()

    def test_global_search_single_call_and_isolates_deleted_archived_stale(
        self, session: Session
    ) -> None:
        user_id = seed_user(session)
        active_folder = MaterialFolder(id=uuid.uuid4(), user_id=user_id, name="机器学习")
        archived_folder = MaterialFolder(
            id=uuid.uuid4(),
            user_id=user_id,
            name="已归档课程",
            archived_at=datetime.now(UTC),
        )
        session.add_all([active_folder, archived_folder])
        session.commit()

        m1 = seed_material(
            session,
            user_id,
            title="主成分分析.pdf",
            folder_id=active_folder.id,
            contents=("PCA 通过正交变换降维。",),
            points=(("PCA 原理", None),),
        )
        m2 = seed_material(
            session,
            user_id,
            title="未分类讲义.pdf",
            folder_id=None,
            contents=("奇异值分解可用于矩阵压缩。",),
            points=(("SVD 分解", None),),
        )
        archived_mat = seed_material(
            session,
            user_id,
            title="归档资料.pdf",
            folder_id=archived_folder.id,
            contents=("已归档课程机密切片。",),
        )
        deleted_mat = seed_material(
            session,
            user_id,
            title="已删除资料.pdf",
            contents=("已软删资料切片。",),
        )
        del_row = session.get(Material, deleted_mat.material_id)
        assert del_row is not None
        del_row.is_deleted = True
        session.commit()
        parsing_mat = seed_material(
            session,
            user_id,
            title="解析中资料.pdf",
            status="parsing",
            contents=("未就绪资料切片。",),
        )

        # 验证只读聚合仓储仅返回未删/未归档/已就绪的当前版本
        ready_versions = QuestionRepository(session).list_ready_current_versions_for_user(user_id)
        assert set(ready_versions.keys()) == {m1.material_id, m2.material_id}
        assert ready_versions[m1.material_id] == m1.version_id
        assert ready_versions[m2.material_id] == m2.version_id

        stale_cand = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=m1.material_id,
            version_id=uuid.uuid4(),
            content="旧版本过期内容",
            chapter_title="旧章",
            source_info={},
            vector_score=0.95,
            final_score=0.05,
        )
        search = RecordingSearch()
        search.set_canned_candidates(
            [
                stale_cand,
                cand(archived_mat, 0, "归档课程内容", vector_score=0.94, final_score=0.04),
                cand(deleted_mat, 0, "软删资料内容", vector_score=0.93, final_score=0.03),
                cand(parsing_mat, 0, "未就绪资料内容", vector_score=0.92, final_score=0.025),
                cand(m1, 0, "PCA 通过正交变换降维。", vector_score=0.88, final_score=0.02),
                cand(m2, 0, "奇异值分解可用于矩阵压缩。", vector_score=0.82, final_score=0.015),
            ]
        )
        llm = ScriptedLLM()
        llm.push(
            CoachDraft(
                reply="PCA 与 SVD 都可用于降维和矩阵压缩。",
                citation_ids=[m1.snippet_ids[0], m2.snippet_ids[0]],
            )
        )
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=user_id,
            scope="global",
            user_prompt="PCA 和 SVD 有什么关系？",
        )

        assert result.mode == "grounded"
        assert len(search.queries) == 1  # 多资料全局检索严格收敛为 1 次检索/Embedding
        assert search.options[0] is not None
        assert set(search.options[0].allowed_version_ids or ()) == {m1.version_id, m2.version_id}
        returned_ids = {s.snippet_id for s in result.sources}
        assert returned_ids == {m1.snippet_ids[0], m2.snippet_ids[0]}

    def test_global_general_fallback_on_miss_and_no_fabricated_citations(
        self, session: Session
    ) -> None:
        user_id = seed_user(session)
        m1 = seed_material(session, user_id, title="高数.pdf")
        m2 = seed_material(session, user_id, title="线代.pdf")
        search = RecordingSearch()  # 无命中候选
        llm = ScriptedLLM()
        llm.push(
            RewrittenQuery(query="牛顿莱布尼茨公式 通用概念"),
            CoachGeneralDraft(
                reply="以上结合通用学科知识解答：牛顿-莱布尼茨公式建立了定积分与原函数之间的联系。",
                suggestions=["举个计算例子？"],
            ),
        )
        service = make_service(session, llm, search)

        result = service.ask_scoped_coach(
            user_id=user_id,
            scope="global",
            user_prompt="什么是牛顿-莱布尼茨公式？",
        )

        assert result.mode == "general"
        assert result.sources == []
        assert len(search.queries) == 2  # 首轮 1 次 + 改写 1 次
        assert set(search.options[0].allowed_version_ids or ()) == {m1.version_id, m2.version_id}
        system_msg = next(
            m.content
            for m in llm.calls_for(CoachGeneralDraft)[0]
            if m.role == "system" and isinstance(m.content, str)
        )
        assert "严禁编造或猜测任何教材页码" in system_msg

    def test_global_study_profile_summarizes_top5_weak_points_and_history_fallback(
        self, session: Session
    ) -> None:
        user_id = seed_user(session)
        folder = MaterialFolder(id=uuid.uuid4(), user_id=user_id, name="深度学习")
        session.add(folder)
        session.commit()
        points_spec = [(f"考点{i}", None) for i in range(1, 8)]
        seed = seed_material(
            session,
            user_id,
            title="神经网络.pdf",
            folder_id=folder.id,
            points=points_spec,
        )
        # 制造 6 个薄弱考点（< 0.6），验证只取掌握度最低 Top 5
        scores = [0.15, 0.25, 0.35, 0.45, 0.55, 0.58, 0.90]
        for idx, (kp_id, score) in enumerate(zip(seed.point_ids, scores, strict=True)):
            session.add(
                MasteryRecord(
                    user_id=user_id,
                    knowledge_point_id=kp_id,
                    mastery_score=score,
                    level=MasteryLevel.WEAK.value if score < 0.4 else MasteryLevel.PROFICIENT.value,
                    practice_count=idx + 1,
                    correct_count=1,
                )
            )
        session.commit()

        llm = ScriptedLLM()
        llm.push(
            CoachGeneralDraft(
                reply="建议今天优先巩固考点1与考点2。",
                suggestions=["先练考点1？"],
            )
        )
        search = RecordingSearch()
        memory = CoachSessionMemory()
        service = make_service(session, llm, search, memory=memory)

        result = service.ask_scoped_coach(
            user_id=user_id,
            scope="global",
            user_prompt="帮我规划今天复习重点",
            thread_id="global",
            history=[
                AskCoachHistoryItem(role="user", content="我最近做题老错"),
                AskCoachHistoryItem(role="assistant", content="我们一起看看薄弱考点。"),
            ],
        )

        assert result.mode == "study_profile"
        assert result.sources == []
        assert search.queries == []
        prompt = user_text(llm.calls_for(CoachGeneralDraft)[0])
        assert "未归档课程 1 门，已就绪资料 1 份，核心考点共 7 个" in prompt
        assert "考点1" in prompt and "考点5" in prompt
        assert "考点6" not in prompt  # 只取 Top 5
        assert "我最近做题老错" in prompt
        assert len(memory.load(f"{user_id}:global:global")) == 2

    def test_pgvector_allowed_version_ids_filters_and_short_circuits(
        self, session: Session
    ) -> None:
        user_id = seed_user(session)
        s1 = seed_material(session, user_id, title="A.pdf", contents=("向量检索测试内容A",))
        s2 = seed_material(session, user_id, title="B.pdf", contents=("向量检索测试内容B",))

        class CountingEmbedding(FakeEmbeddingAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def embed_query(self, text: str) -> list[float]:
                self.calls += 1
                return super().embed_query(text)

        emb = CountingEmbedding()
        adapter = PgvectorHybridSearchAdapter(
            session_factory=lambda: session,
            embedding_adapter=emb,
        )
        # SQLite 内存测试环境下直接传入 session 测试过滤逻辑
        empty_res = adapter.search(
            "测试内容",
            user_id,
            options=SearchOptions(allowed_version_ids=()),
        )
        assert empty_res.items == ()
        assert emb.calls == 0

        # 非空白名单只召回 s1 版本（注意需用 active session）
        from app.integrations.search.pgvector import use_active_search_session

        with use_active_search_session(session):
            filtered = adapter.search(
                "测试内容",
                user_id,
                options=SearchOptions(allowed_version_ids=(s1.version_id,)),
            )
        assert emb.calls == 1
        assert len(filtered.items) == 1
        assert filtered.items[0].version_id == s1.version_id
        assert filtered.items[0].version_id != s2.version_id

    def test_pgvector_plain_fallback_keeps_4096_budget_on_format_error(
        self, session: Session
    ) -> None:
        class PlainFallbackLLM(ScriptedLLM):
            def __init__(self) -> None:
                super().__init__()
                self.plain_options: list[LLMOptions | None] = []

            def generate_structured(
                self,
                messages: Sequence[LLMMessage],
                response_model: type[Any],
                options: LLMOptions | None = None,
            ) -> tuple[Any, LLMResponse]:
                raise LLMResponseFormatError("format error")

            def generate(
                self, messages: Sequence[LLMMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                self.plain_options.append(options)
                return LLMResponse(content="通用兜底纯文本回复", usage=LLMUsage(), model="test")

        llm = PlainFallbackLLM()
        service = make_service(session, llm, RecordingSearch())
        result = service.ask_scoped_coach(
            user_id=seed_user(session),
            scope="global",
            user_prompt="什么是梯度消失？",
        )
        assert result.mode == "general"
        assert result.reply == "通用兜底纯文本回复"
        assert result.sources == []
        assert llm.plain_options[0] is not None
        assert llm.plain_options[0].max_tokens == 4096
