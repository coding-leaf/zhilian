"""混合检索适配器模块单元测试套件。

严格遵循 AGENTS.md 规范：
- 零外部公网网络，基于 SQLite 内存库模拟数据库执行；
- 强租户隔离门禁与防越权验证；
- 粗排 20 截断、BM25 重排、打分融合与 Top 4 截断端到端验证；
- 行覆盖率与分支覆盖率门禁 >= 90%。
"""

import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    EmbeddingError,
    PermissionDeniedError,
    SearchError,
)
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.search import (
    FakeSearchAdapter,
    PgvectorHybridSearchAdapter,
    SearchOptions,
    SearchProtocol,
    SearchResult,
    SearchSnippetCandidate,
    create_search_adapter,
)
from app.models.base import Base
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.models.user import User


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    """创建 SQLite 内存库会话工厂。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


class TestSearchContracts:
    """混合检索契约与配置测试。"""

    def test_search_options_validation(self) -> None:
        """测试检索参数配置合法性校验。"""
        opts = SearchOptions(top_k=5, vector_top_k=15, fusion_method="rrf")
        assert opts.top_k == 5
        assert opts.vector_top_k == 15
        assert opts.fusion_method == "rrf"

        with pytest.raises(ValueError, match="top_k must be greater than 0"):
            SearchOptions(top_k=0)

        with pytest.raises(ValueError, match="vector_top_k must be greater than or equal to top_k"):
            SearchOptions(top_k=10, vector_top_k=5)

        with pytest.raises(ValueError, match="fusion_method must be either 'rrf' or 'weighted'"):
            SearchOptions(fusion_method="unknown")

    def test_search_snippet_candidate_repr_masks_content(self) -> None:
        """测试候选切片模型日志脱敏，严禁泄露全文。"""
        cand = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content="这是一段非常绝密的物理公式和考点文本！",
            chapter_title="第一章",
            source_info={"page": 1},
            vector_score=0.88,
            bm25_score=12.5,
            final_score=0.035,
            vector_rank=1,
            bm25_rank=2,
        )
        repr_str = repr(cand)
        assert "这是一段非常绝密" not in repr_str
        assert "score=0.0350" in repr_str
        assert "vec_rank=1" in repr_str
        assert "bm25_rank=2" in repr_str

    def test_search_result_immutability(self) -> None:
        """测试检索结果模型字段元组转换。"""
        res = SearchResult(query="测试", items=[])
        assert isinstance(res.items, tuple)
        assert res.total_candidates == 0


class TestFakeSearchAdapter:
    """Fake 混合检索适配器测试。"""

    def test_fake_search_user_id_mandatory(self) -> None:
        """测试缺少 user_id 触发权限异常。"""
        adapter = FakeSearchAdapter()
        assert isinstance(adapter, SearchProtocol)
        with pytest.raises(PermissionDeniedError, match="user_id 不能为空"):
            adapter.search("query", None)  # type: ignore[arg-type]

    def test_fake_search_canned_result(self) -> None:
        """测试预置结果精准返回。"""
        adapter = FakeSearchAdapter()
        user_id = uuid.uuid4()
        canned_res = SearchResult(query="特定查询", items=(), total_candidates=5)

        adapter.set_canned_result("特定查询", canned_res)
        res = adapter.search("特定查询", user_id)
        assert res == canned_res

        # 组合 key 优先
        compound_res = SearchResult(query="特定查询", items=(), total_candidates=10)
        adapter.set_canned_result(f"{user_id}:特定查询", compound_res)
        res2 = adapter.search("特定查询", user_id)
        assert res2 == compound_res

    def test_fake_search_canned_candidates_filtering(self) -> None:
        """测试预设切片候选集根据 material_id 与 version_id 过滤及截断。"""
        adapter = FakeSearchAdapter()
        u_id = uuid.uuid4()
        m_id1 = uuid.uuid4()
        m_id2 = uuid.uuid4()
        v_id1 = uuid.uuid4()

        cand1 = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=m_id1,
            version_id=v_id1,
            content="切片1",
            chapter_title="c1",
            source_info={},
        )
        cand2 = SearchSnippetCandidate(
            snippet_id=uuid.uuid4(),
            material_id=m_id2,
            version_id=v_id1,
            content="切片2",
            chapter_title="c2",
            source_info={},
        )
        adapter.set_canned_candidates([cand1, cand2])

        # 按 material_id 过滤
        res = adapter.search("query", u_id, material_id=m_id1)
        assert len(res.items) == 1
        assert res.items[0].snippet_id == cand1.snippet_id

        # 按 version_id 过滤
        res_ver = adapter.search("query", u_id, version_id=v_id1)
        assert len(res_ver.items) == 2
        res_ver_empty = adapter.search("query", u_id, version_id=uuid.uuid4())
        assert len(res_ver_empty.items) == 0

    def test_fake_search_latency_and_fault(self) -> None:
        """测试时延与故障注入。"""
        adapter = FakeSearchAdapter()
        u_id = uuid.uuid4()
        adapter.set_latency(0.01)

        adapter.set_fault_injection("search", SearchError("模拟检索失败"))
        with pytest.raises(SearchError, match="模拟检索失败"):
            adapter.search("query", u_id)

        adapter.reset()
        res = adapter.search("query", u_id)
        assert res.total_candidates == 0

        # 按 user_id 注入
        adapter.set_fault_injection(str(u_id), PermissionDeniedError("黑名单租户"))
        with pytest.raises(PermissionDeniedError, match="黑名单租户"):
            adapter.search("query", u_id)

        adapter.reset()
        # 按 query 注入
        adapter.set_fault_injection("恶意查询", SearchError("敏感词拦截"))
        with pytest.raises(SearchError, match="敏感词拦截"):
            adapter.search("恶意查询", u_id)

    def test_fake_search_repr(self) -> None:
        """测试 repr 脱敏展示。"""
        adapter = FakeSearchAdapter()
        assert "canned_results=0" in repr(adapter)


class TestPgvectorHybridSearchAdapter:
    """Pgvector 混合检索执行器单元测试。"""

    def test_pgvector_search_user_id_mandatory(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试缺少 user_id 强制拦截水平越权。"""
        embed_adapter = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )
        assert isinstance(search_adapter, SearchProtocol)

        with pytest.raises(PermissionDeniedError, match="user_id 不能为空"):
            search_adapter.search("考点", None)  # type: ignore[arg-type]

    def test_pgvector_multi_tenant_isolation(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试跨租户水平越权阻断：用户 A 绝不召回用户 B 的切片。"""
        embed_adapter = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )

        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        with db_session_factory() as session:
            session.add(User(id=user_a, openid="user_a"))
            session.add(User(id=user_b, openid="user_b"))
            session.commit()

            mat_b = Material(user_id=user_b, title="B的资料", file_format="pdf", file_size=100)
            session.add(mat_b)
            session.commit()

            ver_b = MaterialVersion(
                user_id=user_b,
                material_id=mat_b.id,
                version_number=1,
                storage_key="k_b",
                content_hash="h_b",
            )
            session.add(ver_b)
            session.commit()

            # 用户 B 的高相关切片
            query = "牛顿第二定律"
            b_vector = embed_adapter.embed_query(query)
            snippet_b = MaterialSnippet(
                user_id=user_b,
                material_id=mat_b.id,
                version_id=ver_b.id,
                snippet_index=0,
                content="牛顿第二定律是经典力学的核心基石：F = ma",
                char_length=25,
                start_offset=0,
                end_offset=25,
                chapter_title="力学",
                embedding=b_vector,
            )
            session.add(snippet_b)
            session.commit()

        # 用户 A 执行相同关键词查询
        result = search_adapter.search(query, user_id=user_a)
        assert result.total_candidates == 0
        assert len(result.items) == 0

    def test_pgvector_coarse_20_to_fine_4_and_fusion(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试粗排 20 截断、BM25 重排与 Top 4 截断端到端流转。"""
        embed_adapter = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )

        user_id = uuid.uuid4()
        query = "量子力学 不确定性原理"
        # 预设确定性查询向量
        query_vector = [1.0] + [0.0] * 1023
        embed_adapter.set_canned_vector(query, query_vector)

        with db_session_factory() as session:
            session.add(User(id=user_id, openid="user_physics"))
            session.commit()

            mat = Material(user_id=user_id, title="量子物理", file_format="pdf", file_size=1000)
            session.add(mat)
            session.commit()

            ver = MaterialVersion(
                user_id=user_id,
                material_id=mat.id,
                version_number=1,
                storage_key="k_qm",
                content_hash="h_qm",
            )
            session.add(ver)
            session.commit()

            # 插入 25 个切片：其中前 5 个切片包含关键词且向量高度对齐，其余为无关内容
            for i in range(25):
                if i < 5:
                    content = f"量子力学中的海森堡不确定性原理详细讨论 片段{i}"
                    snippet_vec = [0.9] + [0.0] * 1023
                else:
                    content = f"无关的经典力学背景材料描述说明 片段{i}"
                    snippet_vec = [0.0, 1.0] + [0.0] * 1022

                snip = MaterialSnippet(
                    user_id=user_id,
                    material_id=mat.id,
                    version_id=ver.id,
                    snippet_index=i,
                    content=content,
                    char_length=len(content),
                    start_offset=i * 50,
                    end_offset=(i + 1) * 50,
                    chapter_title="量子物理概论",
                    embedding=snippet_vec,
                )
                session.add(snip)
            session.commit()

        # 执行 RRF 融合检索
        result_rrf = search_adapter.search(
            query=query,
            user_id=user_id,
            options=SearchOptions(top_k=4, vector_top_k=20, fusion_method="rrf"),
        )

        assert result_rrf.total_candidates == 20  # 粗排取 top 20
        assert len(result_rrf.items) == 4  # 最终截断取 top 4
        for item in result_rrf.items:
            assert item.final_score > 0.0
            assert "量子力学" in item.content
            assert item.vector_rank is not None
            assert item.bm25_rank is not None

        # 执行加权融合检索 (weighted)
        result_weighted = search_adapter.search(
            query=query,
            user_id=user_id,
            options=SearchOptions(top_k=4, vector_top_k=20, fusion_method="weighted"),
        )
        assert len(result_weighted.items) == 4
        for item in result_weighted.items:
            assert item.final_score >= 0.0

    def test_pgvector_material_and_version_filtering(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试按 material_id 与 version_id 范围限定检索切片。"""
        embed_adapter = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )
        user_id = uuid.uuid4()
        mat1_id = uuid.uuid4()
        mat2_id = uuid.uuid4()
        ver1_id = uuid.uuid4()
        ver2_id = uuid.uuid4()

        with db_session_factory() as session:
            session.add(User(id=user_id, openid="user_filter"))
            session.commit()

            mat1 = Material(
                id=mat1_id, user_id=user_id, title="资料1", file_format="pdf", file_size=100
            )
            mat2 = Material(
                id=mat2_id, user_id=user_id, title="资料2", file_format="pdf", file_size=100
            )
            session.add_all([mat1, mat2])
            session.commit()

            ver1 = MaterialVersion(
                id=ver1_id,
                user_id=user_id,
                material_id=mat1_id,
                version_number=1,
                storage_key="k1",
                content_hash="h1",
            )
            ver2 = MaterialVersion(
                id=ver2_id,
                user_id=user_id,
                material_id=mat2_id,
                version_number=1,
                storage_key="k2",
                content_hash="h2",
            )
            session.add_all([ver1, ver2])
            session.commit()

            snip1 = MaterialSnippet(
                user_id=user_id,
                material_id=mat1_id,
                version_id=ver1_id,
                snippet_index=0,
                content="这是第一份资料的内容",
                char_length=10,
                start_offset=0,
                end_offset=10,
                embedding=[0.1] * 1024,
            )
            snip2 = MaterialSnippet(
                user_id=user_id,
                material_id=mat2_id,
                version_id=ver2_id,
                snippet_index=0,
                content="这是第二份资料的内容",
                char_length=10,
                start_offset=0,
                end_offset=10,
                embedding=[0.1] * 1024,
            )
            session.add_all([snip1, snip2])
            session.commit()
            snip1_id = snip1.id
            snip2_id = snip2.id

        # 仅限定 mat1
        res1 = search_adapter.search("资料", user_id=user_id, material_id=mat1_id)
        assert len(res1.items) == 1
        assert res1.items[0].snippet_id == snip1_id

        # 仅限定 ver2
        res2 = search_adapter.search("资料", user_id=user_id, version_id=ver2_id)
        assert len(res2.items) == 1
        assert res2.items[0].snippet_id == snip2_id

    def test_pgvector_postgres_dialect_execution_branch(self) -> None:
        """测试在模拟 PostgreSQL 方言下的 SQL 分支执行。"""
        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value.__enter__.return_value = mock_session

        mock_dialect = MagicMock()
        mock_dialect.name = "postgresql"
        mock_session.bind.dialect = mock_dialect

        fake_snippet = MagicMock()
        fake_snippet.id = uuid.uuid4()
        fake_snippet.material_id = uuid.uuid4()
        fake_snippet.version_id = uuid.uuid4()
        fake_snippet.content = "Postgres 检索切片内容"
        fake_snippet.chapter_title = "第一章"
        fake_snippet.source_info = {}
        fake_snippet.embedding = [0.1] * 1024

        mock_session.scalars.return_value.all.return_value = [fake_snippet]

        embed_adapter = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=mock_session_factory,
            embedding_adapter=embed_adapter,
        )

        res = search_adapter.search("检索词", user_id=uuid.uuid4())
        assert len(res.items) == 1
        assert res.items[0].snippet_id == fake_snippet.id

    def test_pgvector_empty_database_result(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试库内无数据时安全返回空结果。"""
        embed_adapter = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )
        res = search_adapter.search("无切片查询", uuid.uuid4())
        assert res.total_candidates == 0
        assert len(res.items) == 0

    def test_pgvector_embedding_error_propagation(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试向量化失败时异常正常向上传播。"""
        embed_adapter = FakeEmbeddingAdapter()
        embed_adapter.set_fault_injection("query", EmbeddingError("模拟向量化失败"))
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )

        with pytest.raises(EmbeddingError, match="模拟向量化失败"):
            search_adapter.search("测试查询", uuid.uuid4())

    def test_pgvector_empty_query_vector_error(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试向量化返回空列表时抛出异常。"""
        mock_embed = MagicMock()
        mock_embed.embed_query.return_value = []
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=mock_embed,
        )
        with pytest.raises(EmbeddingError, match="生成查询向量结果为空"):
            search_adapter.search("测试查询", uuid.uuid4())

    def test_pgvector_unexpected_db_error_wrapped(
        self, db_session_factory: sessionmaker[Session]
    ) -> None:
        """测试未预期数据库错误被包装为 SearchError。"""
        mock_factory = MagicMock()
        mock_factory.side_effect = RuntimeError("数据库连接池耗尽")

        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=mock_factory,
            embedding_adapter=FakeEmbeddingAdapter(),
        )
        with pytest.raises(SearchError, match="混合检索执行异常"):
            search_adapter.search("测试", uuid.uuid4())

    def test_pgvector_repr(self, db_session_factory: sessionmaker[Session]) -> None:
        """测试 repr 脱敏展示。"""
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=db_session_factory,
            embedding_adapter=FakeEmbeddingAdapter(),
        )
        assert "<PgvectorHybridSearchAdapter" in repr(search_adapter)


class TestSearchFactory:
    """混合检索工厂函数测试。"""

    def test_create_search_adapter(self, db_session_factory: sessionmaker[Session]) -> None:
        """测试不同检索适配器创建与参数校验。"""
        fake = create_search_adapter("fake")
        assert isinstance(fake, FakeSearchAdapter)

        embed_adapter = FakeEmbeddingAdapter()
        pg = create_search_adapter(
            "pgvector",
            session_factory=db_session_factory,
            embedding_adapter=embed_adapter,
        )
        assert isinstance(pg, PgvectorHybridSearchAdapter)

        # 缺少 session_factory
        with pytest.raises(SearchError, match="必须提供 session_factory"):
            create_search_adapter("pgvector", embedding_adapter=embed_adapter)

        # 缺少 embedding_adapter
        with pytest.raises(SearchError, match="必须提供 embedding_adapter"):
            create_search_adapter("pgvector", session_factory=db_session_factory)

        # 不支持的类型
        with pytest.raises(SearchError, match="不支持的检索适配器类型"):
            create_search_adapter("elastic")
