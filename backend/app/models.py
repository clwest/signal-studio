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
    title = Column(String(500), nullable=False)
    summary = Column(Text, default="")
    category = Column(String(100), default="general")  # tech, finance, market, career, etc.
    confidence_score = Column(Float, default=0.5)
    source_count = Column(Integer, default=0)
    signal_strength = Column(Float, default=0.0)  # 0-1 composite
    status = Column(String(50), default="active")  # active, archived, actioned
    tags = Column(JSON, default=list)
    metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    """Generated action steps from a signal cluster."""
    __tablename__ = "action_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("signal_clusters.id"), nullable=False)
    title = Column(String(500), nullable=False)
    steps = Column(JSON, default=list)  # [{step: str, priority: str}]
    outreach_draft = Column(Text, default="")
    action_type = Column(String(50), default="investigate")  # investigate, invest, build, hire, pitch
    status = Column(String(50), default="pending")  # pending, in_progress, done, dismissed
    created_at = Column(DateTime, default=datetime.utcnow)

    cluster = relationship("SignalCluster", back_populates="action_cards")


def get_engine(database_url: str = "sqlite:///./signalstudio.db"):
    return create_engine(database_url)


def init_db(database_url: str = "sqlite:///./signalstudio.db"):
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
