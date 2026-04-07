"""SignalStudio — FastAPI Backend"""
import os
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
from sqlalchemy.orm import sessionmaker, joinedload

from app.models import (
    SignalCluster, EvidenceCard, SourceItem, ActionCard,
    init_db, get_engine,
)

app = FastAPI(title="SignalStudio", version="1.0.0")

from app.stripe_billing import router as stripe_router
app.include_router(stripe_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(",") if os.getenv("ALLOWED_ORIGINS") else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = get_engine(DATABASE_URL)
init_db(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "SignalStudio", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/signals")
def list_signals(
    category: Optional[str] = None,
    limit: int = Query(default=20, le=50),
    offset: int = 0,
):
    """List signal clusters, optionally filtered by category."""
    db = SessionLocal()
    try:
        q = db.query(SignalCluster).order_by(desc(SignalCluster.signal_strength))
        if category and category != "all":
            q = q.filter(SignalCluster.category == category)
        total = q.count()
        clusters = q.offset(offset).limit(limit).all()

        return {
            "signals": [
                {
                    "id": str(c.id),
                    "title": c.title,
                    "summary": c.summary[:200],
                    "category": c.category,
                    "confidence_score": c.confidence_score,
                    "source_count": c.source_count,
                    "signal_strength": c.signal_strength,
                    "status": c.status,
                    "tags": c.tags or [],
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "evidence_count": len(c.evidence_cards),
                    "has_action": len(c.action_cards) > 0,
                }
                for c in clusters
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    finally:
        db.close()


@app.get("/api/signals/{signal_id}")
def get_signal(signal_id: UUID):
    """Get full signal cluster detail with evidence cards and sources."""
    db = SessionLocal()
    try:
        cluster = (
            db.query(SignalCluster)
            .options(
                joinedload(SignalCluster.evidence_cards),
                joinedload(SignalCluster.source_items),
                joinedload(SignalCluster.action_cards),
            )
            .filter(SignalCluster.id == signal_id)
            .first()
        )
        if not cluster:
            raise HTTPException(status_code=404, detail="Signal not found")

        return {
            "signal": {
                "id": str(cluster.id),
                "title": cluster.title,
                "summary": cluster.summary,
                "category": cluster.category,
                "confidence_score": cluster.confidence_score,
                "source_count": cluster.source_count,
                "signal_strength": cluster.signal_strength,
                "status": cluster.status,
                "tags": cluster.tags or [],
                "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
            },
            "evidence_cards": [
                {
                    "id": str(e.id),
                    "claim_text": e.claim_text,
                    "excerpt": e.excerpt,
                    "excerpt_is_quote": e.excerpt_is_quote,
                    "source_title": e.source_title,
                    "source_domain": e.source_domain,
                    "source_url": e.source_url,
                    "confidence_score": e.confidence_score,
                    "citation_label": e.citation_label,
                    "claim_type": e.claim_type,
                }
                for e in cluster.evidence_cards
            ],
            "sources": [
                {
                    "id": str(s.id),
                    "title": s.title,
                    "url": s.url,
                    "domain": s.domain,
                    "snippet": s.snippet,
                    "spider_name": s.spider_name,
                    "relevance_score": s.relevance_score,
                }
                for s in cluster.source_items
            ],
            "action_cards": [
                {
                    "id": str(a.id),
                    "title": a.title,
                    "steps": a.steps,
                    "action_type": a.action_type,
                    "status": a.status,
                }
                for a in cluster.action_cards
            ],
        }
    finally:
        db.close()


@app.get("/api/stats")
def get_stats():
    """Dashboard stats."""
    db = SessionLocal()
    try:
        total = db.query(SignalCluster).count()
        active = db.query(SignalCluster).filter(SignalCluster.status == "active").count()
        categories = {}
        for c in db.query(SignalCluster).all():
            categories[c.category] = categories.get(c.category, 0) + 1
        avg_confidence = 0
        if total > 0:
            scores = [c.confidence_score for c in db.query(SignalCluster).all()]
            avg_confidence = sum(scores) / len(scores)

        return {
            "total_signals": total,
            "active_signals": active,
            "categories": categories,
            "avg_confidence": round(avg_confidence, 2),
            "evidence_cards_total": db.query(EvidenceCard).count(),
            "action_cards_total": db.query(ActionCard).count(),
        }
    finally:
        db.close()


@app.post("/api/signals/{signal_id}/generate-action")
def generate_action(signal_id: UUID):
    """Generate action steps for a signal using AI."""
    db = SessionLocal()
    try:
        cluster = db.query(SignalCluster).filter(SignalCluster.id == signal_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Signal not found")

        # Check if action already exists
        existing = db.query(ActionCard).filter(ActionCard.cluster_id == signal_id).first()
        if existing:
            return {
                "action_card": {
                    "id": str(existing.id),
                    "title": existing.title,
                    "steps": existing.steps,
                    "action_type": existing.action_type,
                    "status": existing.status,
                },
                "generated": False,
            }

        # For MVP, return a structured response based on the signal
        action = ActionCard(
            cluster_id=cluster.id,
            title=f"Next Steps: {cluster.title[:100]}",
            steps=[
                {"step": f"Research deeper into {cluster.category} signal", "priority": "high"},
                {"step": "Validate key claims with primary sources", "priority": "high"},
                {"step": "Identify stakeholders who need to know", "priority": "medium"},
                {"step": "Draft action plan with 30/60/90 day milestones", "priority": "medium"},
                {"step": "Set up monitoring alerts for signal changes", "priority": "low"},
            ],
            action_type="investigate",
        )
        db.add(action)
        db.commit()

        return {
            "action_card": {
                "id": str(action.id),
                "title": action.title,
                "steps": action.steps,
                "action_type": action.action_type,
                "status": action.status,
            },
            "generated": True,
        }
    finally:
        db.close()
