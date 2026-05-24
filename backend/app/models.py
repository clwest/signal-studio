"""SignalStudio — Database Models"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, JSON, Boolean, ForeignKey, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class SignalCluster(Base):
    """A cluster of related signals detected from spider/web data."""
    __tablename__ = "signal_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Session 1131 Phase 1 — u-d-b SignalCluster.id (UUID stringified).
    # Upsert key for `signal.cluster_promoted` events from the fleet
    # event stream + the GET /api/fleet/signals/clusters backfill.
    # Nullable so legacy/locally-seeded rows still parse (those rows
    # have no upstream counterpart). Indexed unique-where-not-null via
    # a partial index applied at startup; see signal_ingest._ensure_schema.
    external_cluster_id = Column(String(64), index=True, nullable=True)
    # Session 1131 Phase 2 — curated convenience fields. Populated from
    # `signal.curated_published` events; latest snapshot wins (u-d-b's
    # CuratedSignalSnapshot table is the audit-trail source of truth).
    # `curated_rank` IS NOT NULL means this cluster is in the latest
    # curated top-N; ORDER BY curated_rank ASC for the Curated tab.
    curated_rank = Column(Integer, index=True, nullable=True)
    curated_score = Column(Float, nullable=True)
    curated_snapshot_id = Column(String(64), nullable=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, default="")
    category = Column(String(100), default="general")  # tech, finance, market, career, etc.
    confidence_score = Column(Float, default=0.5)
    source_count = Column(Integer, default=0)
    signal_strength = Column(Float, default=0.0)  # 0-1 composite
    status = Column(String(50), default="active")  # active, archived, actioned
    tags = Column(JSON, default=list)
    extra_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Session 1138 quality fix — LLM-summarized fields. The original
    # title/summary/tags come from u-d-b's clustering, which currently
    # produces meta-stat summaries ("69 signals from 17 sources") and
    # poor titles. This service runs over the evidence cards underneath
    # and produces insight-grade titles + a single-sentence blurb +
    # clean entity tags. `summary_quality` is the state machine:
    #
    #   - raw         : not yet summarized (default)
    #   - summarized  : LLM extracted a coherent theme + title + blurb
    #   - rejected    : LLM determined the cluster is too incoherent
    #                   to summarize (heterogeneous evidence). Hidden
    #                   from /api/signals by default.
    #
    # `summarized_content_hash` is the SHA-256 of the inputs we sent
    # to the LLM (evidence claim_texts + source domains). Idempotency:
    # if a re-run produces the same hash, skip. Lets the backfill
    # script run safely on a cron without re-spending tokens.
    summary_quality = Column(String(16), default="raw", index=True)
    summarized_title = Column(Text, nullable=True)
    summarized_blurb = Column(Text, nullable=True)
    clean_tags = Column(JSON, nullable=True)
    summarized_at = Column(DateTime, nullable=True)
    summarized_content_hash = Column(String(64), nullable=True)

    # Session 1140 — which u-d-b clusterer produced the upstream row.
    # Mirrors `core.models_signal_intelligence.SignalCluster.cluster_method`
    # so we can break the LLM judge's reject rate down per method (the
    # SLO for the entity-token rewrite shipped in Session 1139). Default
    # 'legacy' for rows ingested before this column existed; upstream
    # default is 'entity_token_v1'. Width (32) matches u-d-b.
    cluster_method = Column(String(32), default="legacy", index=True)

    # Relationships
    evidence_cards = relationship("EvidenceCard", back_populates="cluster", cascade="all, delete-orphan")
    source_items = relationship("SourceItem", back_populates="cluster", cascade="all, delete-orphan")
    action_cards = relationship("ActionCard", back_populates="cluster", cascade="all, delete-orphan")


class EvidenceCard(Base):
    """A structured, citable evidence unit linked to a signal cluster."""
    __tablename__ = "evidence_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("signal_clusters.id"), nullable=False)
    claim_text = Column(String(500), nullable=False)
    excerpt = Column(Text, default="")
    excerpt_is_quote = Column(Boolean, default=False)
    source_title = Column(String(500), default="")
    source_domain = Column(String(200), default="")
    source_url = Column(String(2000), default="")
    source_date = Column(String(50), default="")
    confidence_score = Column(Float, default=0.5)
    citation_label = Column(String(10), default="")
    claim_type = Column(String(50), default="general")  # statistic, quote, example, trend
    created_at = Column(DateTime, default=datetime.utcnow)

    cluster = relationship("SignalCluster", back_populates="evidence_cards")


class SourceItem(Base):
    """A raw source item that contributed to a signal cluster."""
    __tablename__ = "source_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("signal_clusters.id"), nullable=False)
    title = Column(String(500), default="")
    url = Column(String(2000), default="")
    domain = Column(String(200), default="")
    snippet = Column(Text, default="")
    published_at = Column(String(50), default="")
    spider_name = Column(String(100), default="")
    relevance_score = Column(Float, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow)

    cluster = relationship("SignalCluster", back_populates="source_items")


class ActionCard(Base):
    """Generated action steps from a signal cluster.

    Two write paths populate this table:

      1. On-demand: `/api/signals/{id}/generate-action` creates one row
         per cluster with hardcoded placeholder steps. Legacy path,
         status='pending'/'in_progress'/'done'/'dismissed'.

      2. Pre-generated (Session 1140 A): u-d-b's curator runs an LLM
         action-card generator for every cluster in a curated snapshot
         and emits `signal.curated_actions_ready`. signal-studio's fleet
         event consumer ingests those into rows here keyed by
         `external_id` (the u-d-b CuratedSignalEntry.id) so re-emits
         are idempotent. status='draft'/'needs_regen'/'ready'/'dismissed'.

    The two paths share the table but use different status vocabs —
    the column is String(50) so both fit. UI should branch on
    `external_id IS NOT NULL` (pre-generated/curated) vs IS NULL
    (on-demand).
    """
    __tablename__ = "action_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("signal_clusters.id"), nullable=False)
    # Session 1140 (A) — u-d-b CuratedSignalEntry.id for the pre-generated
    # case. NULL for on-demand cards. Unique-where-not-null partial index
    # added by _ensure_schema so idempotent re-emit by external_id works.
    external_id = Column(String(64), index=True, nullable=True)
    title = Column(String(500), nullable=False)
    steps = Column(JSON, default=list)  # [{step: str, priority: str}]
    outreach_draft = Column(Text, default="")
    action_type = Column(String(50), default="investigate")  # investigate, invest, build, hire, pitch
    status = Column(String(50), default="pending")
    # Session 1140 (A) — audit metadata for the pre-generated case.
    # 'gpt-5-mini' or 'fallback_placeholder'. NULL for on-demand cards.
    generated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    cluster = relationship("SignalCluster", back_populates="action_cards")


def get_engine(database_url: str = "sqlite:///./signalstudio.db"):
    return create_engine(database_url)


def init_db(database_url: str = "sqlite:///./signalstudio.db"):
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
