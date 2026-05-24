"""SignalStudio — FastAPI Backend"""
import asyncio
import logging
import os
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import sessionmaker, joinedload

from app.models import (
    SignalCluster, EvidenceCard, SourceItem, ActionCard,
    init_db, get_engine,
)

logger = logging.getLogger(__name__)

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

# Session 1131 Phase 1: idempotent schema migration for the new
# `external_cluster_id` column on signal_clusters. `init_db()` only
# creates missing tables — it does NOT alter existing tables to add
# columns. The ensure-schema helper handles the column add + the
# unique partial index across Postgres + SQLite.
from app.signal_ingest import (
    _ensure_schema,
    backfill_from_pull_endpoint,
    consume_fleet_events,
)
_ensure_schema(engine)


@app.on_event("startup")
async def _start_fleet_signal_ingest():
    """Kick off the fleet-event consumer + run a startup backfill.

    The consumer is a long-lived asyncio task; we don't await it. The
    backfill is run as a separate task so a slow upstream doesn't
    block startup (FastAPI's `startup` hook is awaited before the
    server starts accepting connections).

    Gated on FLEET_SERVICE_SECRET — if the env var is missing
    (cold-start dev mode, no fleet identity provisioned yet) we skip
    both. The seed fallback in seed.py keeps the UI populated.
    """
    if not os.environ.get("FLEET_SERVICE_SECRET"):
        logger.info(
            "[startup] FLEET_SERVICE_SECRET not set — skipping fleet "
            "signal ingest; seed data will remain authoritative"
        )
        return

    async def _backfill_in_background():
        try:
            n = await backfill_from_pull_endpoint(SessionLocal)
            logger.info("[startup] backfill complete; upserted %d clusters", n)
        except Exception as e:  # pragma: no cover
            logger.exception("[startup] backfill failed: %s", e)

    # Run backfill in the background — don't block server startup if
    # upstream is slow / unreachable.
    asyncio.create_task(_backfill_in_background())
    # Long-running consumer.
    asyncio.create_task(consume_fleet_events(SessionLocal))
    logger.info("[startup] fleet signal ingest tasks spawned")


@app.on_event("startup")
def _start_auto_summarizer():
    """Spin up the auto-summarize worker on a daemon thread.

    Polls every SUMMARIZER_INTERVAL_SECONDS (default 60) for any new
    raw clusters arriving from the ingest path, summarizes up to
    SUMMARIZER_BATCH_SIZE per tick. Idempotent — won't reprocess
    already-summarized rows. Daemon thread so it dies with the process.

    Disable with SUMMARIZER_ENABLED=0 if you want to backfill manually
    via the CLI instead. Worker also self-disables silently when
    OPENAI_API_KEY is missing or placeholder.
    """
    from app.signal_summarizer import start_auto_summarize_thread
    start_auto_summarize_thread(SessionLocal)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "SignalStudio", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/summarizer-status")
def summarizer_status():
    """Auto-summarize worker state — for ops visibility.

    Surfaces what the background worker has done since process start:
    ticks elapsed, total summarized/rejected/error counts, cumulative
    cost in USD, last-tick stats, and any most-recent error.
    """
    from app.signal_summarizer import get_summarizer_state
    return get_summarizer_state()


# ── Brain bridge — proxy questions to u-d-b's PA (Rigby) ───────────────────
# SignalStudio is currently auth-less so the endpoint is open. Future auth
# layer can wrap this with a Depends() guard.

class BrainAskRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    # Session 1128 Phase 2B — optional fleet routing fields. When any of
    # mode/agent/role is set, brain_client builds a `routing` block on
    # the u-d-b /api/pa/chat/ payload so the Phase 2A dispatcher can
    # force-route (or hint-route) to a specific u-d-b AGENT_MAP key.
    agent: Optional[str] = None
    role: Optional[str] = None
    mode: Optional[str] = None


@app.post("/api/brain/ask")
def brain_ask(req: BrainAskRequest):
    from app.brain_client import ask
    if not req.message.strip():
        raise HTTPException(400, "message is required")
    result = ask(
        req.message,
        conversation_id=req.conversation_id,
        workspace="signal-studio",
        app_slug="signal-studio",
        agent=req.agent,
        role=req.role,
        mode=req.mode,
    )
    if not result.get("ok"):
        raise HTTPException(502, result.get("error", "brain unreachable"))
    return result


# ── Paid-interest (Session 1138 — Decision 13 demand-gate) ─────────────────
# Free-tier users submit interest in a paid version. Per-IP rate-limit
# 3/hour + email dedup before forwarding to u-d-b (which also dedups
# server-side as the safety net). All rows live in u-d-b's
# core_fleetpaidinterest table; queryable by Jessica via Rigby's
# paid_interest_status PA tool.

class PaidInterestRequest(BaseModel):
    email: str
    use_case: str
    willing_pay: Optional[int] = None
    workspace_size: Optional[str] = None
    user_id_claim: Optional[str] = None


# Simple in-memory rate-limit. Keyed by client IP. Stores
# list[float-epoch-seconds] of recent submissions. Hour window. Single
# process per container — no Redis needed for this scope.
_RATE_LIMIT_WINDOW_SEC = 3600
_RATE_LIMIT_MAX = 3
_rate_limit_state: dict[str, list[float]] = {}


def _check_rate_limit(client_ip: str) -> bool:
    """Return True when the request is allowed, False when over limit."""
    import time as _time
    now = _time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SEC
    recent = [t for t in _rate_limit_state.get(client_ip, []) if t >= cutoff]
    if len(recent) >= _RATE_LIMIT_MAX:
        _rate_limit_state[client_ip] = recent
        return False
    recent.append(now)
    _rate_limit_state[client_ip] = recent
    return True


@app.post("/api/paid-interest")
def submit_paid_interest_view(req: PaidInterestRequest, request: Request):
    from app.brain_client import submit_paid_interest

    # ── Validation ────────────────────────────────────────────────────
    email = req.email.strip().lower()
    use_case = req.use_case.strip()
    if not email:
        raise HTTPException(400, "email is required")
    if not use_case:
        raise HTTPException(400, "use_case is required")
    if len(use_case) > 140:
        raise HTTPException(400, "use_case must be ≤140 characters")
    if req.willing_pay is not None and req.willing_pay < 0:
        raise HTTPException(400, "willing_pay must be >= 0")
    if req.workspace_size and req.workspace_size not in {"solo", "2-5", "6-20", "20+"}:
        raise HTTPException(400, "workspace_size must be one of solo/2-5/6-20/20+")

    # ── Rate-limit (per IP, in-memory) ────────────────────────────────
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            429,
            f"rate-limited — max {_RATE_LIMIT_MAX} submissions per hour per IP",
        )

    # ── Forward to u-d-b ──────────────────────────────────────────────
    result = submit_paid_interest(
        email=email,
        use_case=use_case,
        willing_pay=req.willing_pay,
        workspace_size=req.workspace_size,
        user_id_claim=req.user_id_claim,
    )
    if not result.get("ok"):
        status_code = result.get("status_code") or 502
        raise HTTPException(
            status_code if status_code >= 400 else 502,
            result.get("error", "paid-interest submission failed"),
        )
    return {
        "ok": True,
        "id": result.get("id"),
        "deduped": result.get("deduped", False),
        "message": (
            "Got it. We'll email you at launch."
            if not result.get("deduped")
            else "Already captured — you'll hear from us at launch."
        ),
    }


@app.get("/api/signals")
def list_signals(
    category: Optional[str] = None,
    limit: int = Query(default=20, le=50),
    offset: int = 0,
    include_raw: bool = Query(
        default=False,
        description=(
            "By default the response hides clusters that haven't been "
            "LLM-summarized yet OR were rejected as incoherent. Set "
            "include_raw=true to see everything regardless of quality."
        ),
    ),
    skip_dedup: bool = Query(
        default=False,
        description=(
            "By default the response collapses near-duplicate clusters "
            "(same theme summarized from different upstream clusters — "
            "see app.signal_deduper). Set skip_dedup=true to see the "
            "pre-dedup list."
        ),
    ),
):
    """List signal clusters, optionally filtered by category.

    Default response only includes `summary_quality='summarized'` rows
    so a visitor sees insight-grade content. Rejected (incoherent)
    clusters and not-yet-summarized raw clusters are hidden by default.
    A deterministic deduper then collapses near-duplicate clusters
    (e.g. four "Tableau Developer" rows → 1) so visitors don't see
    the same theme repeated. Pass `include_raw=true` to see all
    quality states; pass `skip_dedup=true` to see the pre-dedup list.

    When a row has summarized_title/blurb populated, those are
    surfaced as `title` + `summary` on the wire — the underlying
    raw meta-stat title is hidden because that's the whole point of
    this filter. Clients shouldn't need to know the difference.
    """
    from app.signal_deduper import deduplicate_clusters

    db = SessionLocal()
    try:
        q = db.query(SignalCluster).order_by(desc(SignalCluster.signal_strength))
        if category and category != "all":
            q = q.filter(SignalCluster.category == category)
        if not include_raw:
            q = q.filter(SignalCluster.summary_quality == "summarized")

        # Fetch a larger window so dedup has the full set to work over.
        # Without this we'd run dedup on the slice and miss duplicates
        # whose representative happens to fall on another page.
        pre_dedup = q.all()
        if skip_dedup:
            deduped = pre_dedup
            duplicates_merged = 0
        else:
            dedup = deduplicate_clusters(pre_dedup)
            deduped = dedup.kept
            duplicates_merged = dedup.duplicates_merged

        total = len(deduped)
        clusters = deduped[offset:offset + limit]

        return {
            "signals": [
                {
                    "id": str(c.id),
                    "title": c.summarized_title or c.title,
                    "summary": (c.summarized_blurb or c.summary or "")[:300],
                    "category": c.category,
                    "confidence_score": c.confidence_score,
                    "source_count": c.source_count,
                    "signal_strength": c.signal_strength,
                    "status": c.status,
                    "tags": (c.clean_tags if c.clean_tags else c.tags) or [],
                    "summary_quality": c.summary_quality or "raw",
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "evidence_count": len(c.evidence_cards),
                    "has_action": len(c.action_cards) > 0,
                }
                for c in clusters
            ],
            "total": total,
            "duplicates_merged": duplicates_merged,
            "offset": offset,
            "limit": limit,
        }
    finally:
        db.close()


@app.get("/api/signals/events")
async def stream_signal_events():
    """Browser-facing SSE channel for curated-set refresh notifications.

    Session 1132 (C): when u-d-b emits `signal.curated_published` and
    `signal_ingest._apply_curated_snapshot()` finishes committing the
    new top-10, this endpoint pushes a `curated:refreshed` event to
    every connected browser. The React Curated tab opens an
    EventSource here and either auto-refreshes or shows a toast on
    receipt.

    Browser-facing only — no auth in this MVP (the curated set is
    app-wide, not user-scoped). When user-personalized curation
    arrives, gate this endpoint behind a session cookie.

    Wire format:
        event: stream.opened
        data: {"event": "stream.opened", "ts": <unix>}

        event: curated:refreshed
        data: {"event": "curated:refreshed", "snapshot_id": "<uuid>",
               "top_n": 10, "ts": <unix>}

        : ping              (keep-alive every 15s when idle)
    """
    from app.browser_events import curated_event_stream

    return StreamingResponse(
        curated_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable nginx-style proxy buffering so events flush in
            # real time. Harmless when there's no nginx in front.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/signals/curated")
def list_curated_signals(limit: int = Query(default=10, le=50)):
    """List the latest curated signal clusters (Session 1131 Phase 2).

    Returns clusters in the most recent `signal.curated_published`
    snapshot, ordered by `curated_rank` ascending. Source of truth is
    u-d-b's `CuratedSignalSnapshot` table; this endpoint reads the
    convenience columns populated by the curated handler.

    Empty list means no curated snapshot has been received yet (the
    SignalCuratorAgent runs daily at 6 AM MST per the u-d-b beat
    schedule; first run won't show until that fires).
    """
    db = SessionLocal()
    try:
        # Pull MORE than `limit` so the deduper sees enough breadth.
        # Without this we'd dedup a tiny window and still surface
        # duplicates that fall just outside it.
        from app.signal_deduper import deduplicate_clusters
        pre_dedup = (
            db.query(SignalCluster)
            .filter(SignalCluster.curated_rank.isnot(None))
            # Hide curated rows that came back rejected — those wouldn't
            # have been curated by SignalCuratorAgent if upstream knew,
            # but we filter defensively at the read-side too.
            .filter(SignalCluster.summary_quality != "rejected")
            .order_by(SignalCluster.curated_rank.asc())
            .all()
        )
        deduped = deduplicate_clusters(pre_dedup).kept
        rows = deduped[:limit]
        if not rows:
            return {
                "curated": [],
                "snapshot_id": None,
                "total": 0,
            }
        snapshot_id = rows[0].curated_snapshot_id
        return {
            "curated": [
                {
                    "id": str(c.id),
                    "external_cluster_id": c.external_cluster_id,
                    "rank": c.curated_rank,
                    "curated_score": c.curated_score,
                    "title": c.summarized_title or c.title,
                    "summary": ((c.summarized_blurb or c.summary or "")[:300]),
                    "category": c.category,
                    "confidence_score": c.confidence_score,
                    "signal_strength": c.signal_strength,
                    "source_count": c.source_count,
                    "tags": (c.clean_tags if c.clean_tags else c.tags) or [],
                    "summary_quality": c.summary_quality or "raw",
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "evidence_count": len(c.evidence_cards),
                }
                for c in rows
            ],
            "snapshot_id": snapshot_id,
            "total": len(rows),
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
                "title": cluster.summarized_title or cluster.title,
                "summary": cluster.summarized_blurb or cluster.summary or "",
                "category": cluster.category,
                "confidence_score": cluster.confidence_score,
                "source_count": cluster.source_count,
                "signal_strength": cluster.signal_strength,
                "status": cluster.status,
                "tags": (cluster.clean_tags if cluster.clean_tags else cluster.tags) or [],
                "summary_quality": cluster.summary_quality or "raw",
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
            # Session 1140 (A): action_cards now carry the Session 1140
            # pre-generated fields (external_id, generated_by, outreach_draft)
            # alongside the legacy on-demand shape. Frontend uses
            # `is_curated_pregen` (derived from external_id presence) to
            # branch between the two render paths — Rigby PR-review
            # suggestion on signal-studio#18 captured for PR 3.
            "action_cards": [
                {
                    "id": str(a.id),
                    "title": a.title,
                    "steps": a.steps,
                    "action_type": a.action_type,
                    "status": a.status,
                    "outreach_draft": a.outreach_draft or "",
                    "external_id": a.external_id,
                    "generated_by": a.generated_by,
                    "is_curated_pregen": a.external_id is not None,
                }
                for a in cluster.action_cards
            ],
        }
    finally:
        db.close()


@app.get("/api/stats")
def get_stats():
    """Dashboard stats.

    Counts surface BOTH "shown to users" (summarized only) AND total
    pipeline state. Public stats badges in the frontend show
    `active_signals` which now means insight-grade only — the
    `raw_pending` + `rejected` counts are exposed for ops visibility.
    """
    from app.signal_deduper import deduplicate_clusters
    db = SessionLocal()
    try:
        summarized_rows = (
            db.query(SignalCluster)
            .filter(
                SignalCluster.status == "active",
                SignalCluster.summary_quality == "summarized",
            )
            .all()
        )
        # Show-to-user count: summarized + active, after dedup.
        dedup = deduplicate_clusters(summarized_rows)
        active = len(dedup.kept)
        duplicates_merged = dedup.duplicates_merged

        total = db.query(SignalCluster).count()
        raw_pending = (
            db.query(SignalCluster)
            .filter(SignalCluster.summary_quality == "raw")
            .count()
        )
        rejected = (
            db.query(SignalCluster)
            .filter(SignalCluster.summary_quality == "rejected")
            .count()
        )

        # Category counts on the DEDUPED set — that's what the user
        # actually sees, so showing a "Tech: 12" badge that collapses
        # to 3 after dedup would be misleading.
        categories: dict[str, int] = {}
        for c in dedup.kept:
            categories[c.category] = categories.get(c.category, 0) + 1

        avg_confidence = 0.0
        if active > 0:
            scores = [c.confidence_score for c in dedup.kept if c.confidence_score is not None]
            avg_confidence = sum(scores) / len(scores) if scores else 0.0

        return {
            "total_signals": total,
            "active_signals": active,
            "raw_pending": raw_pending,
            "rejected": rejected,
            "duplicates_merged": duplicates_merged,
            "categories": categories,
            "avg_confidence": round(avg_confidence, 2),
            "evidence_cards_total": db.query(EvidenceCard).count(),
            "action_cards_total": db.query(ActionCard).count(),
        }
    finally:
        db.close()


@app.get("/api/judge-stats")
def get_judge_stats(days: int = Query(default=7, ge=1, le=90)):
    """Session 1140 — LLM judge rejection-rate stats.

    Surfaces the auto-summarize judge's accept/reject breakdown so the
    Session 1139 entity-token clusterer can be measured against the
    legacy verb-keyword fallback. Power-source for the
    `signal_studio_judge_stats` PA tool in u-d-b (Rigby calls this so
    Chris can query rejection rate from chat without `docker exec`).

    Acceptance bar (Rigby-locked, Session 1139):
      - cluster_method='entity_token_v1' rejection_rate < 30% → victory
      - 30-60% → partial; decide on embedding approach
      - ≥ 60% → escalate

    Returns counts + rejection_rate at three levels:
      1. total — all clusters in the window
      2. by_cluster_method — entity_token_v1 vs legacy (the SLO)
      3. by_pattern_type — demand_spike, trend_emergence, etc.
         (pattern_type lives in `extra_data['pattern_type']` because
         it's never been a first-class column in this mirror)

    rejection_rate is `rejected / (rejected + summarized)` — raw rows
    (not yet judged) are excluded from the denominator, otherwise a
    backlog spike would mask quality.
    """
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)

    def _empty_bucket() -> dict:
        return {
            "total": 0,
            "summarized": 0,
            "rejected": 0,
            "raw": 0,
            "rejection_rate": 0.0,
        }

    def _finalize(bucket: dict) -> dict:
        judged = bucket["summarized"] + bucket["rejected"]
        bucket["rejection_rate"] = (
            round(bucket["rejected"] / judged, 4) if judged else 0.0
        )
        return bucket

    db = SessionLocal()
    try:
        rows = (
            db.query(
                SignalCluster.summary_quality,
                SignalCluster.cluster_method,
                SignalCluster.extra_data,
            )
            .filter(SignalCluster.created_at >= since)
            .all()
        )

        totals = _empty_bucket()
        by_cluster_method: dict[str, dict] = {}
        by_pattern_type: dict[str, dict] = {}

        for quality, method, extra in rows:
            quality = (quality or "raw").lower()
            method = (method or "legacy").lower()
            pattern_type = "unknown"
            if isinstance(extra, dict):
                pt = extra.get("pattern_type")
                if isinstance(pt, str) and pt:
                    pattern_type = pt

            cm_bucket = by_cluster_method.setdefault(method, _empty_bucket())
            pt_bucket = by_pattern_type.setdefault(pattern_type, _empty_bucket())

            for bucket in (totals, cm_bucket, pt_bucket):
                bucket["total"] += 1
                if quality == "summarized":
                    bucket["summarized"] += 1
                elif quality == "rejected":
                    bucket["rejected"] += 1
                elif quality == "raw":
                    bucket["raw"] += 1

        _finalize(totals)
        for b in by_cluster_method.values():
            _finalize(b)
        for b in by_pattern_type.values():
            _finalize(b)

        return {
            "days": days,
            "since": since.isoformat(),
            **totals,
            "by_cluster_method": by_cluster_method,
            "by_pattern_type": by_pattern_type,
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
