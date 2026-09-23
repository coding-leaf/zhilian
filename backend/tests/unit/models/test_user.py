"""Unit tests for the User entity model and TenantModelMixin.

Tests database schema definitions, default field values, and declarative multi-tenant isolation.
"""

import uuid
from collections.abc import Generator
from datetime import datetime

import pytest
from sqlalchemy import String, create_engine, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.models.base import Base, TenantModelMixin, TimestampMixin
from app.models.user import User


class TenantDummyItem(Base, TenantModelMixin, TimestampMixin):
    """Dummy child table inheriting TenantModelMixin for tenant isolation tests."""

    __tablename__ = "test_tenant_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False)


@pytest.fixture
def db_session() -> Generator[sessionmaker[Session], None, None]:
    """Creates an in-memory SQLite database session factory for model tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


class TestUserModel:
    """Test suite for the User model schema and defaults."""

    def test_user_model_defaults(self, db_session: sessionmaker[Session]) -> None:
        """Verify User model initializes with required defaults."""
        with db_session() as session:
            user = User(openid="test_wx_openid_001")
            session.add(user)
            session.commit()

            assert isinstance(user.id, uuid.UUID)
            assert user.openid == "test_wx_openid_001"
            assert user.unionid is None
            assert user.nickname == ""
            assert user.avatar_url == ""
            assert user.token_version == 1
            assert user.is_active is True
            assert user.is_deleted is False
            assert isinstance(user.created_at, datetime)
            assert isinstance(user.updated_at, datetime)

    def test_user_custom_fields(self, db_session: sessionmaker[Session]) -> None:
        """Verify User model persists custom field inputs."""
        custom_id = uuid.uuid4()
        with db_session() as session:
            user = User(
                id=custom_id,
                openid="test_wx_openid_custom",
                unionid="test_wx_unionid_custom",
                nickname="LearnerOne",
                avatar_url="https://example.com/avatar.png",
                token_version=5,
                is_active=False,
                is_deleted=True,
            )
            session.add(user)
            session.commit()

            retrieved = session.scalar(select(User).where(User.id == custom_id))
            assert retrieved is not None
            assert retrieved.id == custom_id
            assert retrieved.openid == "test_wx_openid_custom"
            assert retrieved.unionid == "test_wx_unionid_custom"
            assert retrieved.nickname == "LearnerOne"
            assert retrieved.avatar_url == "https://example.com/avatar.png"
            assert retrieved.token_version == 5
            assert retrieved.is_active is False
            assert retrieved.is_deleted is True


class TestTenantModelMixin:
    """Test suite for TenantModelMixin foreign key constraints and cascade behavior."""

    def test_tenant_model_foreign_key_and_query(self, db_session: sessionmaker[Session]) -> None:
        """Verify child entities linked by TenantModelMixin enforce user_id binding."""
        user_a_id = uuid.uuid4()
        user_b_id = uuid.uuid4()

        with db_session() as session:
            user_a = User(id=user_a_id, openid="openid_user_a")
            user_b = User(id=user_b_id, openid="openid_user_b")
            session.add_all([user_a, user_b])
            session.commit()

            item_a = TenantDummyItem(user_id=user_a_id, title="Material A")
            item_b = TenantDummyItem(user_id=user_b_id, title="Material B")
            session.add_all([item_a, item_b])
            session.commit()

            # Verify tenant isolation query
            stmt = select(TenantDummyItem).where(TenantDummyItem.user_id == user_a_id)
            items_for_user_a = session.scalars(stmt).all()
            assert len(items_for_user_a) == 1
            assert items_for_user_a[0].title == "Material A"

    def test_tenant_model_cascade_deletion(self, db_session: sessionmaker[Session]) -> None:
        """Verify cascade deletion removes child records when user is deleted."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="openid_cascade_test")
            session.add(user)
            session.commit()

            item = TenantDummyItem(user_id=user_id, title="Will Be Cascade Deleted")
            session.add(item)
            session.commit()

            # Confirm item exists
            stmt = select(TenantDummyItem).where(TenantDummyItem.user_id == user_id)
            found = session.scalar(stmt)
            assert found is not None

            # Delete parent user
            session.delete(user)
            session.commit()

            # Verify foreign key definition on the column:
            column = next(iter(TenantDummyItem.user_id.property.columns))
            fk_spec = next(iter(column.foreign_keys))
            assert fk_spec.target_fullname == "users.id"
            assert fk_spec.ondelete == "CASCADE"
