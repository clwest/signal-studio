"""Browser-facing SSE pub/sub for curated-set refresh notifications.

Session 1132 (Rigby's pick C, conversation pa-d19c1674b936): when
u-d-b emits `signal.curated_published` while a user is viewing the
Curated tab, the page should learn about it within seconds without
polling.

Architecture (2-hop fan-out — Phase 1 lock):

    u-d-b emit                                  (HTTPS SSE)
      └─→ signal-studio's brain_events consumer ──┐
                                                  │
            (signal_ingest._apply_curated_snapshot │
             commits DB rows, then calls           │ ↓
             notify_curated_refreshed)             │ ↓
                                                  ▼
                                          browser EventSource
                                          on /api/signals/events
                                          (this module)

Why in-memory (not Redis) pub/sub here:

- signal-studio runs a single uvicorn process per container today.
  An asyncio.Queue per subscriber is the simplest correct primitive
  for single-process broadcast.
- If signal-studio ever scales to multi-process / multi-container,
  swap `notify_curated_refreshed` for a Redis publish + change each
  subscriber's queue to a Redis subscribe iterator. The browser SSE
  contract stays the same; only the broadcast plumbing changes.

Memory rule: SSE generators must be `async def`. Daphne / uvicorn +
sync generator + blocking I/O = event-loop hang (Session 1130 fix).
This module uses async throughout.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

logger = logging.getLogger(__name__)


# Cap on per-subscriber queue depth so a slow/disconnected browser
# can't accumulate unbounded notifications in memory. We only push
# tiny `{snapshot_id, top_n}` payloads, so 32 is plenty even for
# bursty curator activity.
_QUEUE_MAX_SIZE = 32

# Keep-alive ping cadence — SSE comment line every N seconds so
# middle-boxes don't reap an idle connection. Matches the cadence
# used by u-d-b's fleet_events_stream view.
KEEPALIVE_INTERVAL_SEC = 15.0


# Module-level subscriber registry. Each browser EventSource gets
# its own asyncio.Queue; notifications are broadcast to all queues.
_subscribers: set[asyncio.Queue[dict]] = set()


def _register_subscriber(q: asyncio.Queue[dict]) -> None:
    _subscribers.add(q)
    logger.info(
        "[browser-events] subscriber connected total=%d", len(_subscribers),
    )


def _unregister_subscriber(q: asyncio.Queue[dict]) -> None:
    _subscribers.discard(q)
    logger.info(
        "[browser-events] subscriber disconnected total=%d", len(_subscribers),
    )


def notify_curated_refreshed(snapshot_id: str, top_n: int) -> None:
    """Broadcast a `curated:refreshed` event to every connected browser.

    Sync helper because the call site (`signal_ingest._apply_curated_snapshot`)
    runs inside an async context but does sync DB work. We push directly
    onto the queues; full-queue subscribers get their oldest message
    dropped (cap protects against memory growth from a stuck browser).

    Payload is intentionally tiny — the UI refetches `/api/signals/curated`
    on receipt. Means we don't need to keep the queue size in sync with
    the curated payload's growth.
    """
    if not _subscribers:
        return
    payload = {
        "event": "curated:refreshed",
        "snapshot_id": snapshot_id,
        "top_n": top_n,
        "ts": time.time(),
    }
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop oldest, then re-push. Best-effort delivery only; if
            # the browser is too slow to drain, it'll get the latest
            # snapshot's notification on its next read.
            try:
                _ = q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(payload)
            except Exception as e:  # pragma: no cover
                logger.warning(
                    "[browser-events] requeue after drop failed: %s", e,
                )
    logger.debug(
        "[browser-events] notify_curated_refreshed broadcast snapshot=%s "
        "subscribers=%d",
        snapshot_id, len(_subscribers),
    )


# ─── SSE generator + event loop ──────────────────────────────────────


def _format_sse(event_type: str, data: dict) -> bytes:
    """Format one SSE wire event. Mirrors the shape u-d-b's fleet_events
    uses so anyone reading both files sees the same primitive."""
    json_data = json.dumps(data, separators=(",", ":"))
    return f"event: {event_type}\ndata: {json_data}\n\n".encode("utf-8")


def _format_keepalive() -> bytes:
    return b": ping\n\n"


async def curated_event_stream() -> AsyncIterator[bytes]:
    """Async generator that yields SSE wire bytes for one browser client.

    Subscribes to the module-level broadcast set, yields a `stream.opened`
    hello on connect, then forwards every `curated:refreshed` event
    plus periodic keep-alive comments until the client disconnects.
    """
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
    _register_subscriber(q)
    try:
        # Hello event so the client knows the stream is up. The
        # `curated_snapshot_id` echo lets the client compare against
        # what it already has — if they differ the UI can choose to
        # refresh immediately rather than wait for the next event.
        yield _format_sse("stream.opened", {
            "event": "stream.opened",
            "ts": time.time(),
        })

        last_keepalive = time.monotonic()
        while True:
            try:
                payload = await asyncio.wait_for(
                    q.get(),
                    timeout=KEEPALIVE_INTERVAL_SEC,
                )
            except asyncio.TimeoutError:
                # Idle — send keep-alive comment so middle-boxes don't
                # reap the connection.
                yield _format_keepalive()
                last_keepalive = time.monotonic()
                continue
            event_type = payload.get("event", "message")
            yield _format_sse(event_type, payload)
            last_keepalive = time.monotonic()
    except asyncio.CancelledError:
        # Client disconnected or server shutting down — clean exit.
        raise
    except Exception as e:  # pragma: no cover
        logger.exception("[browser-events] stream error: %s", e)
    finally:
        _unregister_subscriber(q)


__all__ = [
    "curated_event_stream",
    "notify_curated_refreshed",
]
