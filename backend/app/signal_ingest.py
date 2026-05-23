"""Fleet event consumer + signal-cluster backfill (Session 1131 Phase 1).

Connects signal-studio to u-d-b's `SignalCluster` pipeline via the
fleet event stream (Move 3 R1+R2) and the new `GET /api/fleet/signals/
clusters` pull endpoint shipped in PR #2138.

Two halves:

1. **Backfill** — on startup, drain
   `GET /api/fleet/signals/clusters?since=<max(seq)>&limit=50` until
   exhausted; upsert each envelope into SignalCluster by
   `external_cluster_id`. Closes any gap that happened while
   signal-studio was offline.

2. **Live consume** — long-running asyncio task that calls
   `subscribe_fleet_events()` (the byte-identical primitive in
   `brain_events.py`) and dispatches each envelope through a
   prefix-based HANDLERS router. Rigby's lock C: a single subscriber
   with one router, so adding `signal.*` doesn't proliferate parallel
   listeners. Future event prefixes plug in by adding a (prefix,
   handler_fn) tuple to HANDLERS.

The router is the only piece in this module that's intended to grow.
Everything else stays focused on the `signal.cluster_promoted` event
shipped in Phase 1.

────────────────────────────────────────────────────────────────────────
Quality-bar contract (locked Session 1131, conversation pa-d19c1674b936):
    status == 'active' AND cluster_size >= 3 AND strength >= 0.6
The bar is enforced u-d-b-side (both the pull endpoint and the emit
predicate). signal-studio does NOT re-check the bar; we trust upstream
and surface whatever crosses it. If we tighten upstream later we don't
need a signal-studio redeploy.
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Callable, Coroutine

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.brain_events import subscribe_fleet_events
from app.fleet_signer import fleet_signature_headers
from app.models import EvidenceCard, SignalCluster, SourceItem


logger = logging.getLogger(__name__)


# ─── Schema migration (idempotent) ────────────────────────────────────


def _ensure_schema(engine) -> None:
    """Add `external_cluster_id` column + unique partial index if missing.

    SignalStudio uses `Base.metadata.create_all()` which is great for
    fresh tables but does NOT alter existing tables to add new columns.
    Phase 1 introduces `external_cluster_id`; this helper adds it on
    startup for installs that pre-date the change. Idempotent across
    both Postgres (signal_studio_postgres) and SQLite (dev fallback).

    The unique-where-not-null partial index lets us keep
    locally-seeded rows (no upstream counterpart) alongside fleet
    rows without forcing a placeholder UUID on the legacy ones.
    """
    dialect = engine.dialect.name  # "postgresql" or "sqlite"

    with engine.begin() as conn:
        # 1. Inspect current columns on signal_clusters.
        existing_cols = set()
        if dialect == "sqlite":
            rows = conn.exec_driver_sql("PRAGMA table_info(signal_clusters)").fetchall()
            existing_cols = {r[1] for r in rows}
        else:
            rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'signal_clusters'"
            )).fetchall()
            existing_cols = {r[0] for r in rows}

        if "external_cluster_id" not in existing_cols:
            logger.info(
                "[signal-ingest] adding signal_clusters.external_cluster_id column"
            )
            conn.exec_driver_sql(
                "ALTER TABLE signal_clusters "
                "ADD COLUMN external_cluster_id VARCHAR(64)"
            )

        # Session 1131 Phase 2 — curated convenience columns. Idempotent
        # ALTER + index across Postgres + SQLite. Same pattern as the
        # Phase 1 external_cluster_id add.
        if "curated_rank" not in existing_cols:
            logger.info(
                "[signal-ingest] adding signal_clusters.curated_rank column"
            )
            conn.exec_driver_sql(
                "ALTER TABLE signal_clusters ADD COLUMN curated_rank INTEGER"
            )
        if "curated_score" not in existing_cols:
            conn.exec_driver_sql(
                "ALTER TABLE signal_clusters ADD COLUMN curated_score REAL"
            )
        if "curated_snapshot_id" not in existing_cols:
            conn.exec_driver_sql(
                "ALTER TABLE signal_clusters ADD COLUMN curated_snapshot_id VARCHAR(64)"
            )
        # Index on curated_rank for cheap "list curated set" queries.
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_signal_clusters_curated_rank "
            "ON signal_clusters(curated_rank)"
        )

        # 2. Unique partial index on external_cluster_id — works on both
        #    dialects. IF NOT EXISTS keeps it idempotent.
        if dialect == "sqlite":
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_signal_clusters_external_cluster_id_uniq "
                "ON signal_clusters(external_cluster_id) "
                "WHERE external_cluster_id IS NOT NULL"
            )
        else:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_signal_clusters_external_cluster_id_uniq "
                "ON signal_clusters(external_cluster_id) "
                "WHERE external_cluster_id IS NOT NULL"
            )


# ─── Envelope upsert ──────────────────────────────────────────────────


def _parse_envelope_created_at(value: Any) -> datetime:
    """ISO 8601 → datetime. Falls back to utcnow() on parse failure."""
    if not value:
        return datetime.utcnow()
    try:
        # Strip trailing 'Z' if present; fromisoformat doesn't accept it
        # on Python 3.10 (containers run 3.11 but defensive is cheap).
        s = value.rstrip("Z")
        # Python's fromisoformat handles offsets like +00:00 in 3.11+.
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def upsert_cluster_from_envelope(session: Session, envelope: dict) -> SignalCluster | None:
    """Upsert one SignalCluster row from a u-d-b envelope.

    Envelope shape matches both the GET /api/fleet/signals/clusters per-
    cluster object and the `signal.cluster_promoted` event payload —
    they're byte-identical by design (Rigby's gotcha A: one consumer
    code path).

    Returns the upserted row, or None if the envelope is malformed.
    """
    external_id = envelope.get("external_cluster_id")
    if not external_id:
        logger.warning(
            "[signal-ingest] envelope missing external_cluster_id; skipping"
        )
        return None

    row = (
        session.query(SignalCluster)
        .filter(SignalCluster.external_cluster_id == external_id)
        .first()
    )

    # Translate envelope → ORM fields.
    title = envelope.get("title") or "Untitled cluster"
    summary = envelope.get("summary") or ""
    category = envelope.get("category") or "general"
    confidence_score = float(envelope.get("confidence_score") or 0.0)
    signal_strength = float(envelope.get("signal_strength") or 0.0)
    cluster_size = int(envelope.get("cluster_size") or 0)
    tags = envelope.get("tags") or []
    created_at = _parse_envelope_created_at(envelope.get("created_at"))

    is_new = row is None
    if is_new:
        row = SignalCluster(
            external_cluster_id=external_id,
            title=title,
            summary=summary,
            category=category,
            confidence_score=confidence_score,
            signal_strength=signal_strength,
            source_count=cluster_size,
            tags=tags,
            status="active",
            created_at=created_at,
            extra_data={"pattern_type": envelope.get("pattern_type")},
        )
        session.add(row)
    else:
        row.title = title
        row.summary = summary
        row.category = category
        row.confidence_score = confidence_score
        row.signal_strength = signal_strength
        row.source_count = cluster_size
        row.tags = tags
        row.status = "active"
        extra = dict(row.extra_data or {})
        extra["pattern_type"] = envelope.get("pattern_type")
        row.extra_data = extra

    session.flush()  # assign row.id for evidence linking on new rows

    # Refresh evidence cards on every upsert — they're a small,
    # bounded set per cluster (cap=5 upstream).
    if not is_new:
        session.query(EvidenceCard).filter(EvidenceCard.cluster_id == row.id).delete()
    for i, ev in enumerate(envelope.get("evidence") or []):
        if not isinstance(ev, dict):
            continue
        headline = ev.get("headline") or ""
        session.add(EvidenceCard(
            cluster_id=row.id,
            claim_text=headline[:500],
            excerpt=headline,
            source_title=ev.get("source") or "",
            source_domain=ev.get("source") or "",
            source_url=ev.get("url") or "",
            confidence_score=confidence_score,
            citation_label=f"[{i+1}]",
            claim_type="general",
        ))

    return row


def upsert_envelope(session_factory: sessionmaker, envelope: dict) -> str | None:
    """Sync wrapper around upsert_cluster_from_envelope.

    Each call gets its own session so a single bad envelope can't
    poison the consumer loop (rollback isolated). Returns the
    external_cluster_id on success, None on failure.
    """
    session = session_factory()
    try:
        row = upsert_cluster_from_envelope(session, envelope)
        if row is None:
            session.rollback()
            return None
        session.commit()
        return row.external_cluster_id
    except Exception as e:
        session.rollback()
        logger.exception(
            "[signal-ingest] upsert failed for external_cluster_id=%s: %s",
            envelope.get("external_cluster_id"), e,
        )
        return None
    finally:
        session.close()


# ─── Startup backfill ─────────────────────────────────────────────────


BACKFILL_PAGE_LIMIT = 50
MAX_BACKFILL_PAGES = 50  # bounded at 50 * 50 = 2500 clusters per run


def _max_seen_seq(session_factory: sessionmaker) -> int:
    """Return the highest u-d-b seq we've already ingested.

    u-d-b's cluster envelope carries a `seq` field but signal-studio's
    SignalCluster model doesn't have a dedicated column for it — we
    stash it in `extra_data['seq']`. The first backfill on a fresh
    install returns 0 (drain everything).
    """
    session = session_factory()
    try:
        # Pull the few hundred candidate rows and find the max seq in
        # extra_data. Tiny set; no need for a JSON index yet.
        rows = (
            session.query(SignalCluster.extra_data)
            .filter(SignalCluster.external_cluster_id.isnot(None))
            .all()
        )
        max_seq = 0
        for (extra,) in rows:
            if not isinstance(extra, dict):
                continue
            s = extra.get("seq")
            if isinstance(s, int) and s > max_seq:
                max_seq = s
        return max_seq
    finally:
        session.close()


async def backfill_from_pull_endpoint(session_factory: sessionmaker) -> int:
    """Drain GET /api/fleet/signals/clusters?since=<max_seq> until empty.

    Returns the number of envelopes upserted. Bounded by
    MAX_BACKFILL_PAGES so a long cold-start can't block startup
    indefinitely; truncation gets logged.
    """
    base = os.environ.get("BRAIN_URL", "http://host.docker.internal:8000").rstrip("/")
    host_override = os.environ.get("BRAIN_HOST_HEADER", "localhost")
    path = "/api/fleet/signals/clusters"
    timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)

    since = _max_seen_seq(session_factory)
    logger.info(
        "[signal-ingest] backfill starting from since=%d", since
    )

    pages = 0
    upserted = 0
    async with httpx.AsyncClient(timeout=timeout) as client:
        while pages < MAX_BACKFILL_PAGES:
            query = f"since={since}&limit={BACKFILL_PAGE_LIMIT}"
            headers = fleet_signature_headers(
                method="GET", path=path, query=query, body=b""
            )
            if headers is None:
                logger.warning(
                    "[signal-ingest] FLEET_* env vars not set; skipping backfill"
                )
                return upserted
            headers = dict(headers)
            headers["Host"] = host_override
            url = f"{base}{path}?{query}"
            try:
                resp = await client.get(url, headers=headers)
            except Exception as e:
                logger.warning(
                    "[signal-ingest] backfill request failed since=%d: %s",
                    since, e,
                )
                return upserted
            if resp.status_code != 200:
                logger.warning(
                    "[signal-ingest] backfill HTTP %d since=%d: %s",
                    resp.status_code, since, resp.text[:300],
                )
                return upserted
            try:
                doc = resp.json()
            except Exception as e:
                logger.warning(
                    "[signal-ingest] backfill JSON decode failed since=%d: %s",
                    since, e,
                )
                return upserted

            clusters = doc.get("clusters") or []
            for env in clusters:
                # Stash seq in extra_data before upsert so _max_seen_seq
                # picks it up next time. The upsert helper preserves
                # extra_data through the merge.
                seq = env.get("seq")
                if isinstance(seq, int):
                    env = {**env}  # don't mutate caller-owned dict
                ext_id = upsert_envelope(session_factory, env)
                if ext_id:
                    upserted += 1
                    # Persist seq separately so it survives an upsert
                    # that doesn't touch extra_data's seq key.
                    _stash_seq_in_extra_data(session_factory, ext_id, seq)

            next_since = doc.get("next_since", since)
            has_more = bool(doc.get("has_more"))
            since = next_since
            pages += 1
            if not has_more:
                logger.info(
                    "[signal-ingest] backfill drained since→%d after %d page(s); "
                    "upserted=%d",
                    since, pages, upserted,
                )
                return upserted

    logger.warning(
        "[signal-ingest] backfill capped at %d pages since→%d upserted=%d; "
        "live stream will fill the rest",
        MAX_BACKFILL_PAGES, since, upserted,
    )
    return upserted


def _stash_seq_in_extra_data(
    session_factory: sessionmaker, external_cluster_id: str, seq: Any
) -> None:
    """Update extra_data.seq for an already-upserted row.

    Separate step so we can hold the seq even when upsert_envelope's
    new/update branches don't touch the seq key (the envelope itself
    carries `seq` but the upsert translator doesn't read it — kept
    decoupled so seq plumbing can change without rewriting the
    translator).
    """
    if not isinstance(seq, int):
        return
    session = session_factory()
    try:
        row = (
            session.query(SignalCluster)
            .filter(SignalCluster.external_cluster_id == external_cluster_id)
            .first()
        )
        if row is None:
            return
        extra = dict(row.extra_data or {})
        extra["seq"] = seq
        row.extra_data = extra
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning(
            "[signal-ingest] failed to stash seq for ext_id=%s: %s",
            external_cluster_id, e,
        )
    finally:
        session.close()


# ─── HANDLERS — prefix-based event router ─────────────────────────────


# Type alias for readability. Handler signature is sync (handler runs
# its DB work synchronously inside the asyncio event loop's executor —
# upsert is small, this is fine for Phase 1). If a handler needs to be
# async later, change the dispatcher to await coroutines too.
Handler = Callable[[dict, sessionmaker], None]


def _handle_signal_event(envelope: dict, session_factory: sessionmaker) -> None:
    """Route any `signal.*` event to its specific handler.

    Phase 1 ships `signal.cluster_promoted`. Phase 2 adds
    `signal.curated_published` (the curated top-N snapshot).
    """
    event_type = envelope.get("event", "")
    data = envelope.get("data") or {}
    payload = data.get("payload") or {}

    if event_type == "signal.cluster_promoted":
        seq = data.get("seq")
        ext_id = upsert_envelope(session_factory, payload)
        if ext_id and isinstance(seq, int):
            # The outer FleetEvent seq is NOT the cluster's seq —
            # that's stashed from the payload's own seq field by
            # the backfill path. We don't track FleetEvent.seq here.
            _stash_seq_in_extra_data(
                session_factory, ext_id, payload.get("seq"),
            )
        if ext_id:
            logger.info(
                "[signal-ingest] cluster_promoted upserted external=%s",
                ext_id,
            )
        return

    if event_type == "signal.curated_published":
        _apply_curated_snapshot(session_factory, payload)
        return

    # Anything else under signal.* — quiet drop. Future event types
    # (cluster_decayed, etc.) plug in above by name.
    logger.debug(
        "[signal-ingest] ignoring %s — no handler", event_type
    )


# ─── Phase 2: curated snapshot handler ─────────────────────────────────


def _apply_curated_snapshot(session_factory: sessionmaker, payload: dict) -> None:
    """Apply a `signal.curated_published` snapshot: latest run wins.

    Session 1131 Phase 2 (Rigby's lock #2): u-d-b's CuratedSignalSnapshot
    is the audit-trail source of truth; signal-studio only needs to know
    which clusters are CURRENTLY curated and at what rank. We:

      1. Clear curated_rank/score/snapshot_id on ALL rows. The previous
         snapshot's set becomes empty.
      2. For each item in the new snapshot, upsert the cluster (in case
         we somehow missed the cluster_promoted event for it) then
         stamp curated_rank/score/snapshot_id.

    Payload shape (from build_curated_envelope on u-d-b side):
        {
          "snapshot_id": "<uuid>",
          "scoring_formula_version": "...",
          "top_n": 10,
          "items": [
            {"rank": 1, "curated_score": 0.92, "group_key": "...",
             "cluster": {<full cluster envelope>}},
            ...
          ],
          "cluster_ids": [...],
          ...
        }
    """
    snapshot_id = payload.get("snapshot_id")
    items = payload.get("items") or []
    if not snapshot_id or not items:
        logger.warning(
            "[signal-ingest] curated_published payload missing "
            "snapshot_id or items; skipping"
        )
        return

    session = session_factory()
    try:
        # 1. Clear the previous curated set. Latest snapshot wins.
        session.query(SignalCluster).filter(
            SignalCluster.curated_rank.isnot(None)
        ).update({
            "curated_rank": None,
            "curated_score": None,
            "curated_snapshot_id": None,
        }, synchronize_session=False)

        applied = 0
        for item in items:
            cluster_env = item.get("cluster") or {}
            rank = item.get("rank")
            score = item.get("curated_score")
            if not isinstance(rank, int):
                continue
            # Upsert in case the cluster_promoted event for this row
            # was missed (e.g. consumer was offline). Same translator
            # path as Phase 1.
            row = upsert_cluster_from_envelope(session, cluster_env)
            if row is None:
                continue
            row.curated_rank = rank
            row.curated_score = float(score) if score is not None else None
            row.curated_snapshot_id = snapshot_id
            applied += 1

        session.commit()
        logger.info(
            "[signal-ingest] curated snapshot applied snapshot=%s "
            "applied=%d items=%d",
            snapshot_id, applied, len(items),
        )

        # Session 1132 (C): notify any browser EventSource subscribers
        # so the Curated tab can refresh without polling. Best-effort —
        # in-memory broadcast; failure to deliver to a subscriber drops
        # silently. Import lazily to avoid a startup-time circular.
        try:
            from app.browser_events import notify_curated_refreshed
            notify_curated_refreshed(snapshot_id, applied)
        except Exception as e:  # pragma: no cover
            logger.warning(
                "[signal-ingest] browser notify failed snapshot=%s: %s",
                snapshot_id, e,
            )
    except Exception as e:
        session.rollback()
        logger.exception(
            "[signal-ingest] curated snapshot apply failed snapshot=%s: %s",
            snapshot_id, e,
        )
    finally:
        session.close()


# Ordered list of (prefix, handler) — Rigby's lock C shape. Handlers
# fire in declaration order; first prefix to match wins. Unknown
# prefixes silently drop to debug log (no warn spam).
HANDLERS: list[tuple[str, Handler]] = [
    ("signal.", _handle_signal_event),
    # Future: ("artifact.", _handle_artifact_event),
]


def dispatch_envelope(envelope: dict, session_factory: sessionmaker) -> None:
    """Run one envelope through the HANDLERS prefix router."""
    event_type = envelope.get("event", "")
    for prefix, handler in HANDLERS:
        if event_type.startswith(prefix):
            try:
                handler(envelope, session_factory)
            except Exception as e:
                logger.exception(
                    "[signal-ingest] handler raised for %s: %s",
                    event_type, e,
                )
            return
    logger.debug(
        "[signal-ingest] unrouted event_type=%s — no handler prefix matched",
        event_type,
    )


# ─── Long-running consumer ────────────────────────────────────────────


async def consume_fleet_events(session_factory: sessionmaker) -> None:
    """Background coroutine: subscribe to u-d-b fleet events forever.

    Builds on `brain_events.subscribe_fleet_events()` (the byte-
    identical primitive), which already handles replay-before-subscribe
    and exponential reconnect. Per-envelope we dispatch through
    HANDLERS — Rigby's lock C router pattern.

    Never raises to the caller: the asyncio.Task spawned at startup
    is expected to live as long as the FastAPI process. Internal
    failures log + continue.
    """
    logger.info("[signal-ingest] fleet event consumer starting")
    try:
        async for envelope in subscribe_fleet_events():
            dispatch_envelope(envelope, session_factory)
    except asyncio.CancelledError:
        logger.info("[signal-ingest] consumer cancelled — shutting down")
        raise
    except Exception as e:  # pragma: no cover
        # subscribe_fleet_events() is supposed to handle its own
        # reconnects forever; if it bails out we log loudly so the
        # operator notices a config problem.
        logger.exception(
            "[signal-ingest] consumer exited unexpectedly: %s", e
        )


__all__ = [
    "HANDLERS",
    "_apply_curated_snapshot",
    "_ensure_schema",
    "backfill_from_pull_endpoint",
    "consume_fleet_events",
    "dispatch_envelope",
    "upsert_envelope",
    "upsert_cluster_from_envelope",
]
