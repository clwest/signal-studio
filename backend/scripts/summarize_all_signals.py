#!/usr/bin/env python3
"""One-shot CLI: run the LLM summarizer over all raw signal clusters.

Designed for local + Docker use. Invoke from the project root:

    # Dry run — shows what would happen, no LLM calls, no spend:
    docker exec signal_studio_api python scripts/summarize_all_signals.py --dry-run

    # Real run — gpt-4o-mini, costs ~$0.013 for 131 clusters:
    docker exec signal_studio_api python scripts/summarize_all_signals.py

    # Bound the spend explicitly:
    docker exec signal_studio_api python scripts/summarize_all_signals.py --limit 10

The script is idempotent: re-running on already-summarized clusters
with unchanged evidence skips them (matched via SHA-256 of inputs).
Cost-bounded: prints estimate as it goes.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Allow running from project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import sessionmaker  # noqa: E402
from app.models import get_engine  # noqa: E402
from app.signal_summarizer import (  # noqa: E402
    DEFAULT_MODEL,
    QUALITY_RAW,
    QUALITY_SUMMARIZED,
    QUALITY_REJECTED,
    _check_api_key,
    summarize_pending,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap number of clusters processed (default: all pending).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without spending tokens.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model name (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log every cluster decision, not just summary stats.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.dry_run:
        key_err = _check_api_key()
        if key_err:
            print(f"FAIL: {key_err}", file=sys.stderr)
            print(
                "Set OPENAI_API_KEY in signal-studio/.env or as a docker env var, "
                "then `docker compose restart signal_studio_api`.",
                file=sys.stderr,
            )
            return 2

    # Use the same DATABASE_URL the API uses.
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./signalstudio.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    engine = get_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Before-snapshot.
    from app.models import SignalCluster
    counts_before = {
        QUALITY_RAW: session.query(SignalCluster)
            .filter(SignalCluster.summary_quality == QUALITY_RAW).count(),
        QUALITY_SUMMARIZED: session.query(SignalCluster)
            .filter(SignalCluster.summary_quality == QUALITY_SUMMARIZED).count(),
        QUALITY_REJECTED: session.query(SignalCluster)
            .filter(SignalCluster.summary_quality == QUALITY_REJECTED).count(),
    }
    print(f"Before: raw={counts_before[QUALITY_RAW]} "
          f"summarized={counts_before[QUALITY_SUMMARIZED]} "
          f"rejected={counts_before[QUALITY_REJECTED]}")

    result = summarize_pending(
        session,
        limit=args.limit,
        model=args.model,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"\nDry-run done. {result.candidates} candidates would be processed.")
        return 0

    counts_after = {
        QUALITY_RAW: session.query(SignalCluster)
            .filter(SignalCluster.summary_quality == QUALITY_RAW).count(),
        QUALITY_SUMMARIZED: session.query(SignalCluster)
            .filter(SignalCluster.summary_quality == QUALITY_SUMMARIZED).count(),
        QUALITY_REJECTED: session.query(SignalCluster)
            .filter(SignalCluster.summary_quality == QUALITY_REJECTED).count(),
    }
    print(f"\nAfter:  raw={counts_after[QUALITY_RAW]} "
          f"summarized={counts_after[QUALITY_SUMMARIZED]} "
          f"rejected={counts_after[QUALITY_REJECTED]}")

    print(f"\nBatch stats:")
    print(f"  candidates:        {result.candidates}")
    print(f"  skipped (idem):    {result.skipped_idempotent}")
    print(f"  summarized OK:     {result.summarized}")
    print(f"  rejected:          {result.rejected}")
    print(f"  errors:            {result.errors}")
    print(f"  input tokens:      {result.input_tokens_total:,}")
    print(f"  output tokens:     {result.output_tokens_total:,}")
    print(f"  est. cost:         ${result.estimated_cost_usd:.4f}")
    return 0 if result.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
