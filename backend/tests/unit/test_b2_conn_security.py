"""Unit tests for Track B2: connection stability, auth security, CORS/500, and pool hardening."""

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.container import AppContainer
from app.core.config import (
    AppSettings,
    DatabaseSettings,
    IdempotencySettings,
    QueueSettings,
    RedisSettings,
    validate_wechat_credentials,
)
from app.core.errors import (
    AuthenticationError,
    LLMAuthError,
    LLMTimeoutError,
    MaterialInvalidError,
    StorageConnectionError,
)
from app.integrations._http_retry import RetryableAdapterError, run_with_retry
from app.integrations.container import ProviderRegistry
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.embedding.openai import OpenAICompatibleEmbeddingAdapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.idempotency.redis import RedisIdempotencyAdapter
from app.integrations.llm.agent_graph import call_model_node
from app.integrations.llm.openai import OpenAICompatibleLLMAdapter
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMResponse, LLMUsage
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.redis import RedisQueueAdapter
from app.integrations.queue.rq_adapter import RQQueueAdapter
from app.integrations.redis_client import build_redis_client
from app.integrations.rerank.siliconflow import SiliconFlowRerankAdapter
from app.integrations.search.pgvector import PgvectorHybridSearchAdapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.integrations.storage.s3 import S3StorageAdapter
from app.main import app, build_cors_options, lifespan, unhandled_exception_handler
from app.models.base import Base
from app.models.material import (
    Material,
    MaterialSnippet,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
)
from app.services.auth import AuthService
from app.services.knowledge import KnowledgeService
from app.services.material import MaterialService

# ---------------------------------------------------------------------------
# R4.1: Production Auth Backdoor Fix & WeChat Credentials Fail-Fast
# ---------------------------------------------------------------------------


class TestProductionAuthSecurity:
    """Verify dev/mock codes and credential-less fallback are blocked in production."""

    @pytest.fixture
    def db_session(self) -> Any:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as sess:
            yield sess
        engine.dispose()

    @pytest.mark.parametrize("code", ["dev_code", "dev_alice", "mock_user_1"])
    def test_production_rejects_dev_and_mock_codes(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
        code: str,
    ) -> None:
        prod_settings = AppSettings(
            env="production",
            secret_key=SecretStr("prod-secret-key-strong-32-bytes-minimum!!"),
            wechat_app_id="wx_prod_app_id",
            wechat_app_secret=SecretStr("wx_prod_secret"),
        )
        monkeypatch.setattr("app.services.auth.get_settings", lambda: prod_settings)
        service = AuthService(db_session)

        with pytest.raises(AuthenticationError, match="生产环境禁止使用开发测试登录凭证"):
            service.login_with_wechat(code=code)

    def test_production_rejects_credentialless_fallback(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        prod_settings = AppSettings(
            env="production",
            secret_key=SecretStr("prod-secret-key-strong-32-bytes-minimum!!"),
            wechat_app_id=None,
            wechat_app_secret=None,
        )
        monkeypatch.setattr("app.services.auth.get_settings", lambda: prod_settings)
        service = AuthService(db_session)

        with pytest.raises(AuthenticationError, match="生产环境未配置微信登录凭据"):
            service.login_with_wechat(code="real_looking_wx_code_12345")

    def test_development_preserves_dev_code_shortcuts(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dev_settings = AppSettings(env="development", wechat_app_id=None, wechat_app_secret=None)
        monkeypatch.setattr("app.services.auth.get_settings", lambda: dev_settings)
        service = AuthService(db_session)

        user1, _ = service.login_with_wechat(code="dev_code")
        assert user1.openid == "wx_dev_deterministic_user"
        user2, _ = service.login_with_wechat(code="mock_student")
        assert user2.openid == "wx_dev_mock_student"

    def test_validate_wechat_credentials_fail_fast_in_production(self) -> None:
        missing_id = AppSettings(
            env="production",
            secret_key=SecretStr("prod-secret-key-strong-32-bytes-minimum!!"),
            wechat_app_id="",
            wechat_app_secret=SecretStr("secret"),
        )
        with pytest.raises(RuntimeError, match="ZHILIAN_WECHAT_APP_ID"):
            validate_wechat_credentials(missing_id)

        missing_secret = AppSettings(
            env="production",
            secret_key=SecretStr("prod-secret-key-strong-32-bytes-minimum!!"),
            wechat_app_id="wx_123",
            wechat_app_secret=SecretStr("   "),
        )
        with pytest.raises(RuntimeError, match="ZHILIAN_WECHAT_APP_SECRET"):
            validate_wechat_credentials(missing_secret)

        valid_prod = AppSettings(
            env="production",
            secret_key=SecretStr("prod-secret-key-strong-32-bytes-minimum!!"),
            wechat_app_id="wx_123",
            wechat_app_secret=SecretStr("secret_xyz"),
        )
        validate_wechat_credentials(valid_prod)

    @pytest.mark.asyncio
    async def test_lifespan_fails_fast_when_production_wechat_creds_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        prod_settings = AppSettings(
            env="production",
            secret_key=SecretStr("prod-secret-key-strong-32-bytes-minimum!!"),
            wechat_app_id=None,
            wechat_app_secret=None,
            db=DatabaseSettings(db_url="sqlite:///:memory:"),
        )
        monkeypatch.setattr("app.main.get_settings", lambda: prod_settings)
        test_app = FastAPI()

        with pytest.raises(RuntimeError, match="ZHILIAN_WECHAT_APP_ID"):
            async with lifespan(test_app):
                pass


# ---------------------------------------------------------------------------
# R3.6: CORS Hygiene, Global 500 JSON Handler, Health Redis Probe & .env.example
# ---------------------------------------------------------------------------


class TestMainCorsAndHealth:
    """Verify CORS rules, sanitized 500 JSON responses, health Redis probe, and .env.example."""

    def test_cors_never_pairs_wildcard_with_credentials(self) -> None:
        dev_settings = AppSettings(cors_allow_origins=["*"])
        dev_cors = build_cors_options(dev_settings)
        assert dev_cors["allow_origins"] == ["*"]
        assert dev_cors["allow_credentials"] is False

        prod_settings = AppSettings(
            cors_allow_origins=["https://zhilian.example.com", "https://admin.example.com"]
        )
        prod_cors = build_cors_options(prod_settings)
        assert prod_cors["allow_origins"] == [
            "https://zhilian.example.com",
            "https://admin.example.com",
        ]
        assert prod_cors["allow_credentials"] is True

        csv_settings = AppSettings(cors_allow_origins="https://a.com, https://b.com")  # type: ignore[arg-type]
        assert csv_settings.cors_allow_origins == ["https://a.com", "https://b.com"]

    def test_global_500_exception_handler_returns_sanitized_json(self) -> None:
        test_app = FastAPI()
        test_app.add_exception_handler(Exception, unhandled_exception_handler)

        @test_app.get("/boom")
        def _boom() -> dict[str, str]:
            raise RuntimeError("secret-db-password-leak")

        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body == {
            "code": 50000,
            "message": "服务暂时繁忙，请稍后重试",
            "details": {},
        }
        assert "secret-db-password-leak" not in resp.text

    def test_health_check_probes_redis_when_enabled(self) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        settings = AppSettings(
            db=DatabaseSettings(db_url="sqlite:///:memory:"),
            queue=QueueSettings(provider="redis"),
            idempotency=IdempotencySettings(provider="memory"),
        )
        registry = ProviderRegistry.create_default(
            AppSettings(
                db=DatabaseSettings(db_url="sqlite:///:memory:"),
                queue=QueueSettings(provider="memory"),
                idempotency=IdempotencySettings(provider="memory"),
            )
        )
        registry.register_queue(RQQueueAdapter(redis_client=mock_redis))
        container = AppContainer.create(settings=settings, registry=registry)

        healthy = container.check_health()
        assert healthy["status"] == "ok"
        assert healthy["redis"] == {"status": "connected"}
        mock_redis.ping.assert_called_once()

        # Simulate Redis failure -> degraded + /health HTTP 503
        mock_redis.ping.side_effect = ConnectionError("redis unreachable")
        degraded = container.check_health()
        assert degraded["status"] == "degraded"
        assert degraded["redis"]["status"] == "disconnected"
        assert "redis unreachable" in degraded["redis"]["error"]

        app.state.container = container
        try:
            client = TestClient(app)
            resp = client.get("/health")
            assert resp.status_code == 503
            assert resp.json()["status"] == "degraded"
        finally:
            if hasattr(app.state, "container"):
                delattr(app.state, "container")

    def test_env_example_uses_psycopg_driver(self) -> None:
        env_example = Path(__file__).resolve().parents[2] / ".env.example"
        content = env_example.read_text(encoding="utf-8")
        assert "postgresql+psycopg://" in content
        assert "postgresql+asyncpg://" not in content


# ---------------------------------------------------------------------------
# R3.1 & R4.6: Redis Client Builder, Adapter Close, S3 Timeouts, MemoryIdempotency LRU
# ---------------------------------------------------------------------------


class TestRedisS3AndMemoryIdempotency:
    """Verify Redis timeouts/close, S3 Config/close, and bounded MemoryIdempotencyAdapter."""

    def test_build_redis_client_honors_settings_and_blocking_mode(self) -> None:
        redis_settings = RedisSettings(
            redis_url="redis://:pwd@redis.local:6379/1",
            timeout=3.5,
            max_connections=32,
        )
        with patch("redis.from_url") as mock_from_url:
            build_redis_client(settings=redis_settings, decode_responses=True)
            mock_from_url.assert_called_once_with(
                "redis://:pwd@redis.local:6379/1",
                socket_connect_timeout=3.5,
                socket_timeout=3.5,
                health_check_interval=30,
                max_connections=32,
                retry_on_timeout=True,
                decode_responses=True,
            )

        with patch("redis.from_url") as mock_blocking:
            build_redis_client(settings=redis_settings, blocking=True)
            mock_blocking.assert_called_once_with(
                "redis://:pwd@redis.local:6379/1",
                socket_connect_timeout=3.5,
                socket_timeout=None,
                health_check_interval=30,
                max_connections=32,
                retry_on_timeout=True,
                decode_responses=False,
            )

    @pytest.mark.asyncio
    async def test_redis_and_s3_adapters_close_in_container_shutdown(self) -> None:
        mock_queue_redis = MagicMock()
        mock_idem_redis = MagicMock()
        mock_s3_client = MagicMock()

        rq_adapter = RQQueueAdapter(redis_client=mock_queue_redis)
        redis_queue_adapter = RedisQueueAdapter(redis_client=MagicMock())
        idem_adapter = RedisIdempotencyAdapter(redis_client=mock_idem_redis)
        s3_adapter = S3StorageAdapter(
            endpoint_url="http://minio:9000",
            access_key="ak",
            secret_key="sk",  # noqa: S106
            client=mock_s3_client,
        )

        registry = ProviderRegistry.create_default(
            AppSettings(
                db=DatabaseSettings(db_url="sqlite:///:memory:"),
                queue=QueueSettings(provider="memory"),
            )
        )
        registry.register_queue(rq_adapter)
        registry.register_idempotency(idem_adapter)
        registry.register_storage(s3_adapter)

        container = AppContainer.create(
            settings=AppSettings(
                db=DatabaseSettings(db_url="sqlite:///:memory:"),
                queue=QueueSettings(provider="memory"),
            ),
            registry=registry,
        )
        await container.shutdown()

        mock_queue_redis.close.assert_called_once()
        mock_queue_redis.connection_pool.disconnect.assert_called_once()
        mock_idem_redis.close.assert_called_once()
        mock_idem_redis.connection_pool.disconnect.assert_called_once()
        mock_s3_client.close.assert_called_once()

        redis_queue_adapter.close()
        redis_queue_adapter._client.close.assert_called_once()

    def test_s3_init_client_sets_explicit_timeouts_and_pool_limit(self) -> None:
        fake_boto3 = MagicMock()
        fake_config_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"boto3": fake_boto3, "botocore.client": MagicMock(Config=fake_config_cls)},
        ):
            S3StorageAdapter(
                endpoint_url="http://minio:9000",
                access_key="ak",
                secret_key="sk",  # noqa: S106
            )

        fake_config_cls.assert_called_once_with(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=30,
            max_pool_connections=20,
        )

    def test_memory_idempotency_lru_eviction_and_expired_cleanup(self) -> None:
        now = 1000.0
        adapter = MemoryIdempotencyAdapter(max_entries=3)
        adapter.set_clock(lambda: now)

        adapter.set_result("k1", "u1", {"v": 1}, ttl_seconds=60)
        adapter.set_result("k2", "u1", {"v": 2}, ttl_seconds=60)
        adapter.set_result("k3", "u1", {"v": 3}, ttl_seconds=60)

        # Access k1 so k2 becomes the least recently used entry
        assert adapter.get_result("k1", "u1") == {"v": 1}

        # Writing k4 must evict k2 (LRU), preserving k1, k3, k4
        adapter.set_result("k4", "u1", {"v": 4}, ttl_seconds=60)
        assert adapter.get_result("k2", "u1") is None
        assert adapter.get_result("k1", "u1") == {"v": 1}
        assert adapter.get_result("k3", "u1") == {"v": 3}
        assert adapter.get_result("k4", "u1") == {"v": 4}

        # Advance clock past TTL -> write-path cleans up expired keys
        now = 2000.0
        adapter.set_result("k5", "u1", {"v": 5}, ttl_seconds=60)
        assert len(adapter._records) == 1
        assert adapter.get_result("k5", "u1") == {"v": 5}


# ---------------------------------------------------------------------------
# R3.2: LLM Timeout Fix, Persistent httpx.Client & Retry Backoff Jitter
# ---------------------------------------------------------------------------


class _SimpleSchema(BaseModel):
    answer: str


class TestLLMTimeoutHttpxReuseAndJitter:
    """Verify LLMOptions.timeout=None, persistent httpx.Client reuse, and retry jitter."""

    def test_llm_options_default_timeout_is_none_and_respects_adapter_timeout(self) -> None:
        opts = LLMOptions(temperature=0.2)
        assert opts.timeout is None

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            timeout=75.0,
            client=mock_client,
        )
        adapter.generate([LLMMessage(role="user", content="hi")], options=opts)
        _, kwargs = mock_client.post.call_args
        assert kwargs["timeout"] == 75.0

        # Explicit non-None timeout still overrides adapter timeout
        adapter.generate(
            [LLMMessage(role="user", content="hi")],
            options=LLMOptions(timeout=18.0),
        )
        _, kwargs_override = mock_client.post.call_args
        assert kwargs_override["timeout"] == 18.0

    def test_agent_graph_preserves_none_timeout_when_options_omitted(self) -> None:
        captured_options: list[LLMOptions | None] = []

        class _CaptureLLM:
            def generate(
                self,
                messages: Any,
                options: LLMOptions | None = None,
            ) -> LLMResponse:
                captured_options.append(options)
                return LLMResponse(
                    content=json.dumps({"answer": "ok"}),
                    usage=LLMUsage(),
                    model="fake",
                )

            def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
                raise NotImplementedError

        call_model_node(
            {
                "adapter": _CaptureLLM(),  # type: ignore[typeddict-item]
                "messages": [LLMMessage(role="user", content="test")],
                "options": None,
                "response_model": _SimpleSchema,
            }
        )
        assert len(captured_options) == 1
        assert captured_options[0] is not None
        assert captured_options[0].timeout is None

    def test_http_adapters_reuse_persistent_httpx_client_and_close(self) -> None:
        llm = OpenAICompatibleLLMAdapter(api_key="sk-test", timeout=40.0)
        c1 = llm._get_client()
        c2 = llm._get_client()
        assert c1 is c2
        assert isinstance(c1, httpx.Client)
        assert c1.timeout.read == 40.0
        llm.close()
        assert c1.is_closed

        emb = OpenAICompatibleEmbeddingAdapter(api_key="sk-test", timeout=25.0)
        e1 = emb._get_client()
        e2 = emb._get_client()
        assert e1 is e2
        assert isinstance(e1, httpx.Client)
        emb.close()
        assert e1.is_closed

        rerank = SiliconFlowRerankAdapter(api_key="sk-test", timeout=15.0)
        r1 = rerank._get_client()
        r2 = rerank._get_client()
        assert r1 is r2
        assert isinstance(r1, httpx.Client)
        rerank.close()
        assert r1.is_closed

    def test_run_with_retry_applies_jitter_to_backoff(self) -> None:
        attempts = 0
        sleeps: list[float] = []

        def _op() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RetryableAdapterError(RuntimeError("transient"))
            return "ok"

        result = run_with_retry(
            _op,
            max_retries=3,
            retry_delay_base=1.0,
            sleep_fn=sleeps.append,
            jitter_fn=lambda lo, hi: 1.25 if (lo, hi) == (0.5, 1.5) else 1.0,
        )
        assert result == "ok"
        # attempt 0: 1.0 * 1 * 1.25 = 1.25; attempt 1: 1.0 * 2 * 1.25 = 2.5
        assert sleeps == [1.25, 2.5]


# ---------------------------------------------------------------------------
# R3.3 & R4.6: SQLite WAL, PG pool_recycle, pgvector Nested-Session & Short-Tx
# ---------------------------------------------------------------------------


class TestDBResiliencePgvectorAndShortTx:
    """Verify SQLite WAL, PG pool_recycle, pgvector session reuse, and material/knowledge tx."""

    def test_sqlite_container_enables_wal_busy_timeout_and_foreign_keys(
        self, tmp_path: Path
    ) -> None:
        db_file = tmp_path / "wal_check.db"
        settings = AppSettings(
            db=DatabaseSettings(db_url=f"sqlite:///{db_file.as_posix()}"),
            queue=QueueSettings(provider="memory"),
        )
        container = AppContainer.create(settings=settings)
        try:
            with container.engine.connect() as conn:
                journal_mode = str(conn.execute(text("PRAGMA journal_mode")).scalar()).lower()
                busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
                foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert journal_mode == "wal"
            assert busy_timeout == 15000
            assert foreign_keys == 1
        finally:
            container.engine.dispose()

    def test_postgresql_engine_configures_pool_recycle_and_keepalives(self) -> None:
        settings = AppSettings(
            db=DatabaseSettings(
                db_url="postgresql+psycopg://u:p@localhost:5432/zhilian",
                pool_size=12,
                max_overflow=24,
                pool_timeout=25.0,
            ),
            queue=QueueSettings(provider="memory"),
        )
        fake_engine = MagicMock()
        with (
            patch("app.container.create_engine", return_value=fake_engine) as mock_ce,
            patch("app.container.sessionmaker", return_value=MagicMock()),
        ):
            AppContainer.create(settings=settings)

        _, kwargs = mock_ce.call_args
        assert kwargs["pool_recycle"] == 1800
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["connect_args"]["keepalives"] == 1
        assert kwargs["connect_args"]["connect_timeout"] == 5

    def test_pgvector_reuses_active_session_without_pool_deadlock(self, tmp_path: Path) -> None:
        """With pool_size=1, max_overflow=0, nested search inside get_session must NOT deadlock."""
        db_file = tmp_path / "single_conn.db"
        engine = create_engine(
            f"sqlite:///{db_file.as_posix()}",
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=1.0,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        embed = FakeEmbeddingAdapter()
        search_adapter = PgvectorHybridSearchAdapter(session_factory=sf, embedding_adapter=embed)

        settings = AppSettings(
            db=DatabaseSettings(db_url=f"sqlite:///{db_file.as_posix()}"),
            queue=QueueSettings(provider="memory"),
        )
        registry = ProviderRegistry.create_default(settings=settings, session_factory=sf)
        registry.register_search(search_adapter)
        container = AppContainer.create(
            settings=settings,
            registry=registry,
            engine=engine,
            session_factory=sf,
        )

        user_id = uuid.uuid4()
        mat_id = uuid.uuid4()
        ver_id = uuid.uuid4()
        try:
            with container.get_session() as sess:
                sess.add(
                    Material(
                        id=mat_id,
                        user_id=user_id,
                        title="算法讲义",
                        file_format="txt",
                        file_size=100,
                    )
                )
                sess.add(
                    MaterialVersion(
                        id=ver_id,
                        material_id=mat_id,
                        user_id=user_id,
                        version_number=1,
                        storage_key="k",
                        content_hash="h",
                    )
                )
                vec = embed.embed_query("二分查找算法复杂度")
                sess.add_all(
                    [
                        MaterialSnippet(
                            id=uuid.uuid4(),
                            user_id=user_id,
                            material_id=mat_id,
                            version_id=ver_id,
                            snippet_index=0,
                            content="前置切片内容",
                            char_length=6,
                            start_offset=0,
                            end_offset=6,
                            embedding=vec,
                            source_info={"page_number": 1},
                        ),
                        MaterialSnippet(
                            id=uuid.uuid4(),
                            user_id=user_id,
                            material_id=mat_id,
                            version_id=ver_id,
                            snippet_index=1,
                            content="二分查找算法复杂度为 O(log n)",
                            char_length=18,
                            start_offset=6,
                            end_offset=24,
                            embedding=vec,
                            source_info={"page_number": 1},
                        ),
                    ]
                )
                sess.commit()

            # Now hold the ONLY connection in the pool (select starts a tx on Connection #1)
            # and invoke search + fetch_neighbor_snippets on the same thread: must NOT deadlock!
            with container.get_session() as sess:
                assert sess.execute(text("SELECT 1")).scalar() == 1
                result = search_adapter.search("二分查找算法复杂度", user_id=user_id)
                assert len(result.items) >= 1
                neighbors = search_adapter.fetch_neighbor_snippets(
                    result.items[:1], user_id=user_id, window=1
                )
                assert len(neighbors) >= 1
        finally:
            engine.dispose()

    def test_material_pipeline_retryable_infra_error_does_not_mark_failed(self) -> None:
        """Retryable infra error must rollback and raise WITHOUT marking MaterialStatus.FAILED."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        storage = MemoryStorageAdapter()
        storage.ensure_bucket_exists("zhilian-materials")

        with sf() as sess:
            mock_knowledge = MagicMock(spec=KnowledgeService)
            mock_knowledge.extract_and_build_knowledge_tree.side_effect = LLMTimeoutError(
                "上游大模型超时"
            )
            service = MaterialService(
                session=sess,
                storage_adapter=storage,
                ocr_adapter=FakeOCRAdapter(),
                embedding_adapter=FakeEmbeddingAdapter(),
                queue_adapter=MemoryQueueAdapter(),
                knowledge_service=mock_knowledge,
                bucket="zhilian-materials",
            )
            user_id = uuid.uuid4()
            content = "操作系统进程调度与死锁预防核心原理详解。" * 10
            mat, ver = service.create_material(
                user_id=user_id,
                title="os.txt",
                file_format="txt",
                file_size=len(content.encode("utf-8")),
                file_content=content.encode("utf-8"),
            )

            with pytest.raises(LLMTimeoutError):
                service.parse_material_pipeline(
                    material_id=mat.id,
                    version_id=ver.id,
                    user_id=user_id,
                )

            refreshed_mat = service.repo.get_material_by_id(mat.id, user_id)
            refreshed_ver = service.repo.get_version_by_id(ver.id, user_id)
            assert refreshed_mat is not None and refreshed_ver is not None
            assert refreshed_mat.status == MaterialStatus.PARSING.value
            assert refreshed_ver.parse_status == ParseStatus.EXTRACTING_KNOWLEDGE.value

            # Non-retryable business/auth error MUST immediately mark FAILED
            mock_knowledge.extract_and_build_knowledge_tree.side_effect = LLMAuthError(
                "API Key 无效"
            )
            with pytest.raises(LLMAuthError):
                service.parse_material_pipeline(
                    material_id=mat.id,
                    version_id=ver.id,
                    user_id=user_id,
                )
            refreshed_mat2 = service.repo.get_material_by_id(mat.id, user_id)
            refreshed_ver2 = service.repo.get_version_by_id(ver.id, user_id)
            assert refreshed_mat2 is not None and refreshed_ver2 is not None
            assert refreshed_mat2.status == MaterialStatus.FAILED.value
            assert refreshed_ver2.parse_status == ParseStatus.FAILED.value

        engine.dispose()

    def test_storage_connection_error_is_retryable_and_invalid_error_is_not(self) -> None:
        assert MaterialService._is_retryable_infra_error(StorageConnectionError("down")) is True
        assert MaterialService._is_retryable_infra_error(TimeoutError("timed out")) is True
        assert MaterialService._is_retryable_infra_error(MaterialInvalidError("bad")) is False
        assert MaterialService._is_retryable_infra_error(LLMAuthError("401")) is False

    def test_short_tx_releases_db_before_s3_and_llm_io(self) -> None:
        """Verify DB transaction is NOT held open during S3 put_object or Knowledge LLM calls."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        tx_states_during_s3: list[bool] = []
        tx_states_during_llm: list[bool] = []

        class _TxObservingStorage(MemoryStorageAdapter):
            def __init__(self, observed_session: Session) -> None:
                super().__init__()
                self._observed_session = observed_session

            def put_object(
                self,
                bucket: str,
                key: str,
                data: bytes,
                content_type: str = "application/octet-stream",
            ) -> Any:
                tx_states_during_s3.append(self._observed_session.in_transaction())
                return super().put_object(bucket, key, data, content_type)

        class _TxObservingLLM:
            def __init__(self, observed_session: Session) -> None:
                self._observed_session = observed_session

            def generate(self, *args: Any, **kwargs: Any) -> LLMResponse:
                return LLMResponse(content="{}", usage=LLMUsage(), model="fake")

            def generate_structured(
                self,
                messages: Any,
                response_model: type[Any],
                options: LLMOptions | None = None,
            ) -> tuple[Any, LLMResponse]:
                tx_states_during_llm.append(self._observed_session.in_transaction())
                payload = {
                    "knowledge_points": [
                        {
                            "temp_id": "kp_1",
                            "name": "进程调度",
                            "level": 1,
                            "parent_temp_id": None,
                            "chapter_title": "第一章",
                            "description": "进程调度核心概念与策略",
                            "source_snippet_indices": [0],
                        }
                    ]
                }
                return response_model.model_validate(payload), LLMResponse(
                    content=json.dumps(payload),
                    usage=LLMUsage(),
                    model="fake",
                )

        with sf() as sess:
            storage = _TxObservingStorage(sess)
            storage.ensure_bucket_exists("zhilian-materials")
            knowledge_svc = KnowledgeService(
                session=sess,
                llm=_TxObservingLLM(sess),  # type: ignore[arg-type]
                embedding=FakeEmbeddingAdapter(),
            )
            service = MaterialService(
                session=sess,
                storage_adapter=storage,
                ocr_adapter=FakeOCRAdapter(),
                embedding_adapter=FakeEmbeddingAdapter(),
                queue_adapter=MemoryQueueAdapter(),
                knowledge_service=knowledge_svc,
                bucket="zhilian-materials",
            )
            user_id = uuid.uuid4()
            content = "进程调度决定就绪队列中哪个进程获得 CPU 执行权。" * 15
            mat, ver = service.create_material(
                user_id=user_id,
                title="sched.txt",
                file_format="txt",
                file_size=len(content.encode("utf-8")),
                file_content=content.encode("utf-8"),
            )
            ready = service.parse_material_pipeline(
                material_id=mat.id,
                version_id=ver.id,
                user_id=user_id,
            )
            assert ready.parse_status == ParseStatus.READY.value

        # Neither S3 uploads nor LLM extraction held an active DB transaction!
        assert len(tx_states_during_s3) >= 2
        assert all(in_tx is False for in_tx in tx_states_during_s3)
        assert len(tx_states_during_llm) >= 1
        assert all(in_tx is False for in_tx in tx_states_during_llm)

        engine.dispose()

    def test_pgvector_uses_fresh_short_session_when_outer_session_not_in_transaction(
        self, tmp_path: Path
    ) -> None:
        """After outer session releases its tx, pgvector search must not re-open outer tx."""
        db_file = tmp_path / "released_outer.db"
        engine = create_engine(
            f"sqlite:///{db_file.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        search_adapter = PgvectorHybridSearchAdapter(
            session_factory=sf, embedding_adapter=FakeEmbeddingAdapter()
        )
        settings = AppSettings(
            db=DatabaseSettings(db_url=f"sqlite:///{db_file.as_posix()}"),
            queue=QueueSettings(provider="memory"),
        )
        registry = ProviderRegistry.create_default(settings=settings, session_factory=sf)
        registry.register_search(search_adapter)
        container = AppContainer.create(
            settings=settings, registry=registry, engine=engine, session_factory=sf
        )
        try:
            with container.get_session() as sess:
                assert sess.in_transaction() is False
                search_adapter.search(
                    query="调度算法",
                    user_id=uuid.uuid4(),
                    material_id=uuid.uuid4(),
                )
                assert sess.in_transaction() is False
        finally:
            engine.dispose()

    def test_worker_container_rebuilds_after_pid_change_without_closing_parent(self) -> None:
        """Simulating POSIX fork: child PID builds a fresh container without closing parent's."""
        from app import worker as worker_mod

        parent_container = MagicMock()
        child_container = MagicMock()
        created = iter([parent_container, child_container])

        worker_mod.shutdown_worker_container()
        with (
            patch.object(AppContainer, "create", side_effect=lambda: next(created)),
            patch.object(worker_mod.os, "getpid", return_value=1001),
        ):
            first = worker_mod.get_worker_container()
            assert first is parent_container

        with (
            patch.object(AppContainer, "create", side_effect=lambda: next(created)),
            patch.object(worker_mod.os, "getpid", return_value=2002),
        ):
            second = worker_mod.get_worker_container()
            assert second is child_container
            parent_container.shutdown.assert_not_called()

        # Clean up child container
        with patch.object(worker_mod.os, "getpid", return_value=2002):
            worker_mod.shutdown_worker_container()
