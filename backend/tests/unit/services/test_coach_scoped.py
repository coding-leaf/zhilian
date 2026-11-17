"""ask_scoped_coach 的 Adaptive RAG 行为测试（离线 SQLite + Fake/Scripted 适配器）。

覆盖：thread_id 会话记忆（隔离/无状态/无记忆库）、摘录整洁裁剪、概览意图、
KP 范围前缀不破坏寒暄判定、课程范围标题参与查询改写、范围兜底。
"""

import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import SearchError
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.coach_graph import CoachDraft, CoachOverviewDraft, RewrittenQuery
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
from app.integrations.search.protocol import SearchOptions, SearchResult, SearchSnippetCandidate
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialFolder, MaterialSnippet, MaterialVersion
from app.models.user import User
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
        # 两份资料各检索一次，改写后再各一次
        assert len(search.queries) == 4
        assert search.queries[2:] == ["敏捷开发 角色 Scrum"] * 2
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

    def test_no_scope_raises_value_error(self, session: Session) -> None:
        service = make_service(session, ScriptedLLM(), RecordingSearch())
        with pytest.raises(ValueError, match="必须指定答疑范围"):
            service.ask_scoped_coach(user_id=uuid.uuid4(), user_prompt="问题")
