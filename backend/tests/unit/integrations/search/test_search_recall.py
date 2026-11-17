"""召回增强测试：白名单、全库关键词通道、邻接上下文（离线 SQLite/Fake/SQL 编译）。"""

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import PermissionDeniedError, SearchError
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.search import (
    FakeSearchAdapter,
    NeighborSearchProtocol,
    PgvectorHybridSearchAdapter,
    SearchOptions,
    SearchSnippetCandidate,
)
from app.integrations.search.pgvector import (
    _escape_like,
    build_keyword_statement,
    extract_keyword_tokens,
)
from app.models.base import Base
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.models.user import User

QUERY_VEC = [1.0] + [0.0] * 1023
ORTHO_VEC = [0.0, 1.0] + [0.0] * 1022


@pytest.fixture
def factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


class Corpus:
    """单用户单版本语料的构造结果。"""

    def __init__(self) -> None:
        self.user_id = uuid.uuid4()
        self.material_id = uuid.uuid4()
        self.version_id = uuid.uuid4()
        self.snippet_ids: list[uuid.UUID] = []


def seed(
    factory: sessionmaker[Session],
    rows: list[tuple[str, list[float], dict[str, Any]]],
) -> Corpus:
    """写入一份语料：rows 为 (content, embedding, source_info)，snippet_index 顺序递增。"""
    corpus = Corpus()
    with factory() as session:
        session.add(User(id=corpus.user_id, openid=f"u-{corpus.user_id}"))
        session.commit()
        session.add(
            Material(
                id=corpus.material_id,
                user_id=corpus.user_id,
                title="m",
                file_format="pdf",
                file_size=1,
            )
        )
        session.commit()
        session.add(
            MaterialVersion(
                id=corpus.version_id,
                user_id=corpus.user_id,
                material_id=corpus.material_id,
                version_number=1,
                storage_key=f"k-{corpus.version_id}",
                content_hash=f"h-{corpus.version_id}",
            )
        )
        session.commit()
        for i, (content, vec, info) in enumerate(rows):
            snippet = MaterialSnippet(
                user_id=corpus.user_id,
                material_id=corpus.material_id,
                version_id=corpus.version_id,
                snippet_index=i,
                content=content,
                char_length=len(content),
                start_offset=i * 10,
                end_offset=i * 10 + 10,
                chapter_title="c",
                source_info=info,
                embedding=vec,
            )
            session.add(snippet)
            session.flush()
            corpus.snippet_ids.append(snippet.id)
        session.commit()
    return corpus


def make_adapter(
    factory: sessionmaker[Session], embed: Any | None = None
) -> PgvectorHybridSearchAdapter:
    if embed is None:
        embed = FakeEmbeddingAdapter()
        embed.set_canned_vector("mc2", QUERY_VEC)
    return PgvectorHybridSearchAdapter(session_factory=factory, embedding_adapter=embed)


class TestContracts:
    def test_defaults_and_tuple_coercion(self) -> None:
        assert SearchOptions().allowed_snippet_ids is None
        ids = [uuid.uuid4()]
        opts = SearchOptions(allowed_snippet_ids=ids)  # type: ignore[arg-type]
        assert opts.allowed_snippet_ids == tuple(ids)
        cand = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content="x",
            chapter_title="",
            source_info={},
        )
        assert cand.snippet_index is None

    def test_adapters_satisfy_neighbor_protocol(self, factory: sessionmaker[Session]) -> None:
        assert isinstance(FakeSearchAdapter(), NeighborSearchProtocol)
        assert isinstance(make_adapter(factory), NeighborSearchProtocol)


class TestKeywordHelpers:
    def test_extract_tokens_prefers_long_unique_and_caps(self) -> None:
        tokens = extract_keyword_tokens(
            "alpha alpha b beta gamma delta eps zeta eta theta iota kappa"
        )
        assert len(tokens) == 8
        assert len(set(tokens)) == 8
        assert "b" not in tokens
        assert (
            tokens[0] == "alpha"
        )  # 最长者优先 (alpha/gamma/delta/theta/iota... 长度 5 同级按出现序)

    def test_extract_tokens_single_char_fallback_and_empty(self) -> None:
        assert extract_keyword_tokens("a") == ["a"]
        assert extract_keyword_tokens("") == []
        assert extract_keyword_tokens("!!! ???") == []

    def test_escape_like(self) -> None:
        assert _escape_like("50%_a\\b") == "50\\%\\_a\\\\b"

    def test_build_statement_none_without_tokens(self) -> None:
        assert build_keyword_statement("!!!", [], limit=5) is None

    def test_postgres_compilation(self) -> None:
        stmt = build_keyword_statement(
            "mc2 force", [MaterialSnippet.user_id == uuid.uuid4()], limit=7
        )
        sql = str(stmt.compile(dialect=postgresql.dialect())).upper()
        assert "ILIKE" in sql
        assert "ESCAPE" in sql
        assert "LIMIT" in sql
        assert "USER_ID" in sql


class TestAllowedSnippetIds:
    def test_empty_allowed_short_circuits_without_embedding(
        self, factory: sessionmaker[Session]
    ) -> None:
        embed = MagicMock()
        adapter = make_adapter(factory, embed)
        res = adapter.search("mc2", uuid.uuid4(), options=SearchOptions(allowed_snippet_ids=()))
        assert res.items == ()
        assert res.total_candidates == 0
        embed.embed_query.assert_not_called()

    def test_allowed_restricts_both_channels_and_sets_index(
        self, factory: sessionmaker[Session]
    ) -> None:
        corpus = seed(
            factory,
            [
                ("mc2 energy relation", QUERY_VEC, {}),
                ("mc2 energy again", QUERY_VEC, {}),
                ("mc2 energy third", QUERY_VEC, {}),
            ],
        )
        keep = corpus.snippet_ids[1]
        res = make_adapter(factory).search(
            "mc2",
            corpus.user_id,
            options=SearchOptions(allowed_snippet_ids=(keep,)),
        )
        assert [c.snippet_id for c in res.items] == [keep]
        assert res.items[0].snippet_index == 1

    def test_postgres_statements_push_allowed_ids_and_keyword_channel(self) -> None:
        statements: list[Any] = []
        session = MagicMock()
        session.bind.dialect.name = "postgresql"

        def capture(stmt: Any) -> Any:
            statements.append(stmt)
            result = MagicMock()
            result.all.return_value = []
            return result

        session.scalars.side_effect = capture
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = session
        embed = FakeEmbeddingAdapter()
        adapter = PgvectorHybridSearchAdapter(session_factory, embed)
        allowed = (uuid.uuid4(), uuid.uuid4())

        adapter.search(
            "mc2 force",
            uuid.uuid4(),
            options=SearchOptions(allowed_snippet_ids=allowed),
        )

        assert len(statements) == 2
        vector_sql = str(statements[0].compile(dialect=postgresql.dialect())).upper()
        keyword_sql = str(statements[1].compile(dialect=postgresql.dialect())).upper()
        assert "<=>" in vector_sql and "IN (" in vector_sql
        assert "ILIKE" in keyword_sql and "IN (" in keyword_sql


class TestFullCorpusKeywordRecall:
    def test_keyword_hit_outside_vector_topk_is_recalled(
        self, factory: sessionmaker[Session]
    ) -> None:
        rows: list[tuple[str, list[float], dict[str, Any]]] = [
            (f"filler paragraph {i}", QUERY_VEC, {}) for i in range(5)
        ]
        rows.append(("the formula mc2 is famous", ORTHO_VEC, {}))
        corpus = seed(factory, rows)
        target = corpus.snippet_ids[-1]

        res = make_adapter(factory).search(
            "mc2",
            corpus.user_id,
            options=SearchOptions(top_k=5, vector_top_k=5, vector_weight=0.0, keyword_weight=1.0),
        )
        # 向量通道仅 5 条填充文本；关键词通道补入第 6 条 => 并集 6
        assert res.total_candidates == 6
        assert res.items[0].snippet_id == target
        assert res.items[0].vector_score == pytest.approx(0.0)
        assert res.items[0].bm25_rank == 1

    def test_keyword_channel_respects_tenant_isolation(
        self, factory: sessionmaker[Session]
    ) -> None:
        corpus = seed(factory, [("the formula mc2 is famous", ORTHO_VEC, {})])
        res = make_adapter(factory).search("mc2", uuid.uuid4())
        assert res.total_candidates == 0
        assert corpus.snippet_ids  # 语料确实存在，只是不属于该租户


NEIGHBOR_ROWS: list[tuple[str, list[float], dict[str, Any]]] = [
    ("s0", QUERY_VEC, {"page_number": 1}),
    ("s1", QUERY_VEC, {"page_number": 1}),
    ("s2", QUERY_VEC, {"page_number": 2}),
    ("s3", QUERY_VEC, {"page_number": 2}),
    ("s4", QUERY_VEC, {}),
    ("s5", QUERY_VEC, {"page_number": 3}),
]


def to_candidate(corpus: Corpus, index: int) -> SearchSnippetCandidate:
    content, _, info = NEIGHBOR_ROWS[index]
    return SearchSnippetCandidate(
        snippet_id=corpus.snippet_ids[index],
        material_id=corpus.material_id,
        version_id=corpus.version_id,
        content=content,
        chapter_title="c",
        source_info=info,
        vector_score=0.9,
        final_score=0.9,
        vector_rank=1,
        snippet_index=index,
    )


class TestPgvectorNeighbors:
    def test_same_page_neighbors_only_and_scores_zero(self, factory: sessionmaker[Session]) -> None:
        corpus = seed(factory, NEIGHBOR_ROWS)
        adapter = make_adapter(factory)
        out = adapter.fetch_neighbor_snippets([to_candidate(corpus, 2)], user_id=corpus.user_id)
        # s1 在第 1 页被排除，s3 同页保留
        assert [c.content for c in out] == ["s3"]
        assert out[0].snippet_index == 3
        assert out[0].vector_score == 0.0 and out[0].final_score == 0.0

    def test_unknown_page_is_compatible_and_inputs_excluded(
        self, factory: sessionmaker[Session]
    ) -> None:
        corpus = seed(factory, NEIGHBOR_ROWS)
        adapter = make_adapter(factory)
        out = adapter.fetch_neighbor_snippets(
            [to_candidate(corpus, 3), to_candidate(corpus, 2)],
            user_id=corpus.user_id,
            window=2,
        )
        # 输入 s2/s3 被排除；s1(页1) 对 s2 不兼容；s4(无页码) 兼容；s5(页3) 对 s3(页2) 不兼容
        assert [c.content for c in out] == ["s4"]

    def test_ordered_by_index_and_window_two(self, factory: sessionmaker[Session]) -> None:
        corpus = seed(
            factory,
            [(f"t{i}", QUERY_VEC, {"page_number": 1}) for i in range(7)],
        )
        cand = SearchSnippetCandidate(
            snippet_id=corpus.snippet_ids[3],
            material_id=corpus.material_id,
            version_id=corpus.version_id,
            content="t3",
            chapter_title="c",
            source_info={"page_number": 1},
            snippet_index=3,
        )
        out = make_adapter(factory).fetch_neighbor_snippets(
            [cand], user_id=corpus.user_id, window=2
        )
        assert [c.snippet_index for c in out] == [1, 2, 4, 5]

    def test_tenant_isolation(self, factory: sessionmaker[Session]) -> None:
        corpus = seed(factory, NEIGHBOR_ROWS)
        out = make_adapter(factory).fetch_neighbor_snippets(
            [to_candidate(corpus, 2)], user_id=uuid.uuid4()
        )
        assert out == []

    def test_noop_cases_and_errors(self, factory: sessionmaker[Session]) -> None:
        adapter = make_adapter(factory)
        uid = uuid.uuid4()
        assert adapter.fetch_neighbor_snippets([], user_id=uid) == []
        no_index = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content="x",
            chapter_title="",
            source_info={},
        )
        assert adapter.fetch_neighbor_snippets([no_index], user_id=uid) == []
        indexed = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content="x",
            chapter_title="",
            source_info={},
            snippet_index=1,
        )
        assert adapter.fetch_neighbor_snippets([indexed], user_id=uid, window=0) == []
        with pytest.raises(PermissionDeniedError):
            adapter.fetch_neighbor_snippets([indexed], user_id=None)  # type: ignore[arg-type]

    def test_db_error_wrapped(self) -> None:
        boom = MagicMock(side_effect=RuntimeError("down"))
        adapter = PgvectorHybridSearchAdapter(boom, FakeEmbeddingAdapter())
        cand = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content="x",
            chapter_title="",
            source_info={},
            snippet_index=1,
        )
        with pytest.raises(SearchError, match="邻接切片查询异常"):
            adapter.fetch_neighbor_snippets([cand], user_id=uuid.uuid4())


class TestFakeAdapter:
    def _candidates(self) -> list[SearchSnippetCandidate]:
        version = uuid.uuid4()
        material = uuid.uuid4()
        return [
            SearchSnippetCandidate(
                snippet_id=uuid.uuid4(),
                material_id=material,
                version_id=version,
                content=f"c{i}",
                chapter_title="",
                source_info={"page_number": 1 if i < 3 else 2},
            )
            for i in range(5)
        ]

    def test_snippet_index_auto_assigned(self) -> None:
        adapter = FakeSearchAdapter()
        adapter.set_canned_candidates(self._candidates())
        res = adapter.search("q", uuid.uuid4(), options=SearchOptions(top_k=5, vector_top_k=5))
        assert [c.snippet_index for c in res.items] == [0, 1, 2, 3, 4]

    def test_explicit_index_preserved(self) -> None:
        import dataclasses

        adapter = FakeSearchAdapter()
        cands = self._candidates()
        cands[0] = dataclasses.replace(cands[0], snippet_index=10)
        adapter.set_canned_candidates(cands)
        res = adapter.search("q", uuid.uuid4(), options=SearchOptions(top_k=5, vector_top_k=5))
        assert res.items[0].snippet_index == 10
        assert res.items[1].snippet_index == 11

    def test_allowed_snippet_ids_honored(self) -> None:
        adapter = FakeSearchAdapter()
        cands = self._candidates()
        adapter.set_canned_candidates(cands)
        uid = uuid.uuid4()
        keep = (cands[1].snippet_id, cands[3].snippet_id)
        res = adapter.search("q", uid, options=SearchOptions(allowed_snippet_ids=keep))
        assert [c.snippet_id for c in res.items] == list(keep)
        assert res.total_candidates == 2
        empty = adapter.search("q", uid, options=SearchOptions(allowed_snippet_ids=()))
        assert empty.items == () and empty.total_candidates == 0

    def test_fetch_neighbors(self) -> None:
        adapter = FakeSearchAdapter()
        cands = self._candidates()
        adapter.set_canned_candidates(cands)
        uid = uuid.uuid4()
        res = adapter.search("q", uid, options=SearchOptions(top_k=5, vector_top_k=5))
        hit = res.items[2]  # index 2, page 1
        out = adapter.fetch_neighbor_snippets([hit], user_id=uid)
        # idx1 同页保留；idx3 属第 2 页被排除
        assert [c.snippet_index for c in out] == [1]
        assert out[0].final_score == 0.0 and out[0].vector_score == 0.0
        assert adapter.fetch_neighbor_snippets([], user_id=uid) == []
        with pytest.raises(PermissionDeniedError):
            adapter.fetch_neighbor_snippets([hit], user_id=None)  # type: ignore[arg-type]
