"""Database engine, session, and migration helpers with pgvector support."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class Show(Base):
    __tablename__ = "shows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    category: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    feed_url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    artwork_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # 'podcast_index' | 'apple' | 'manual'
    source_show_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # platform ID
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    episodes = relationship("Episode", back_populates="show", cascade="all, delete-orphan")


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    show_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    show_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    episode_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # pgvector embedding (all-MiniLM-L6-v2 → 384 dims)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)

    source_episode_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    show = relationship("Show", back_populates="episodes")

    __table_args__ = (
        Index("idx_episodes_show_published", "show_id", "published_at"),
        UniqueConstraint("show_id", "source_episode_id", name="uq_episode_per_show"),
    )


class CachedRecommendation(Base):
    __tablename__ = "cached_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(512), nullable=False)
    episode_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    summaries: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)  # list of {episode_id, summary, reason, timestamps}
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Init / migration
# ---------------------------------------------------------------------------

async def init_db():
    """Create all tables and enable pgvector extension."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def drop_db():
    """Drop all tables (dev only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Yield an async session for FastAPI dependency injection."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_session():
    """Create a sync session for scripts (migration, seeding)."""
    from sqlalchemy import create_engine as sync_engine
    from sqlalchemy.orm import Session as SyncSession

    sync_db_url = settings.database_url.replace("+asyncpg", "+psycopg2")  # fallback to psycopg2
    eng = sync_engine(sync_db_url, echo=False)
    session = SyncSession(eng)
    return session, eng


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        import asyncio

        asyncio.run(init_db())
        print("Database migrated (tables created, pgvector enabled).")
    else:
        print("Usage: python -m app.database migrate")
