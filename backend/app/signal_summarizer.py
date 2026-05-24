"""Signal summarizer — LLM post-process pass over raw clusters.

The clusters that arrive from u-d-b's signal_aggregation_service have
generic titles ("React demand spike", "Security opportunity window")
and meta-stat summaries ("69 signals from 17 sources"). The evidence
cards underneath often contain heterogeneous news items that don't
share a coherent theme. The clustering quality is upstream and not
in our control here.

This module post-processes each cluster:

1. Gather the cluster's evidence-card claim_texts (the actual news
   headlines underneath).
2. Send them to an LLM and ask: "Do these belong together? If yes,
   give me a tight title + one-sentence insight + 3-5 entity tags."
3. Persist the verdict (`summary_quality`) + the improved fields.

State machine on `SignalCluster.summary_quality`:

    raw          — never been summarized
    summarized   — LLM extracted a coherent theme; UI shows improved fields
    rejected     — LLM said "no coherent theme"; UI filters this out

Idempotency: we compute SHA-256 of the inputs sent to the LLM and
store it in `summarized_content_hash`. Re-running on the same cluster
with unchanged evidence is a no-op.

Cost discipline: gpt-4o-mini at $0.15/$0.60 per 1M tokens. Per
cluster: ~300 input tokens, ~80 output tokens = ~$0.0001 per cluster.
131 clusters ≈ $0.013. Reruns idempotent. Budget unchanged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.models import EvidenceCard, SignalCluster

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Cheap model — quality is acceptable for "1-sentence summary from 5
# headlines". Don't reach for the bigger ones; cost discipline.
DEFAULT_MODEL = "gpt-4o-mini"

# Cap on evidence cards we feed the LLM. Most clusters have 5; we cap
# at 8 to bound prompt length even when upstream loosens its cap.
MAX_EVIDENCE_PER_CLUSTER = 8

# Reasonable per-call ceiling. The schema we ask for is small.
MAX_COMPLETION_TOKENS = 250

# State values — match SignalCluster.summary_quality.
QUALITY_RAW = "raw"
QUALITY_SUMMARIZED = "summarized"
QUALITY_REJECTED = "rejected"


# ──────────────────────────────────────────────────────────────────────
# Return shape
# ──────────────────────────────────────────────────────────────────────


@dataclass
class SummaryResult:
    """LLM verdict on a single cluster."""

    is_coherent: bool
    title: str
    blurb: str
    tags: list[str]
    rejection_reason: str  # set when is_coherent=False, else ""
    content_hash: str
    model_used: str
    input_tokens: int
    output_tokens: int


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _compute_content_hash(claim_texts: list[str], domains: list[str]) -> str:
    """SHA-256 of the inputs the LLM saw, so reruns are idempotent."""
    payload = json.dumps(
        {"claims": claim_texts, "domains": domains},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_prompt(claim_texts: list[str], domains: list[str]) -> str:
    """Build the user-side prompt for the LLM.

    Asks for a strict JSON envelope so we can parse deterministically.
    Coherence detection is the key task — heterogeneous clusters
    (random unrelated news) should get is_coherent=false.
    """
    lines = [
        "You are reviewing a cluster of news headlines that an automated",
        "system grouped together. Your job: decide if these headlines",
        "actually share a coherent theme, and if yes, summarize it.",
        "",
        "Headlines:",
    ]
    for i, ct in enumerate(claim_texts, 1):
        # Strip just in case; upstream pads with the source title.
        ct = (ct or "").strip()
        if not ct:
            continue
        # Soft cap per-line to keep prompts bounded.
        lines.append(f"  {i}. {ct[:300]}")
    lines.append("")
    lines.append("Sources: " + ", ".join(sorted(set(domains))[:10]))
    lines.append("")
    lines.append("Reply ONLY with a JSON object, no prose around it:")
    lines.append("{")
    lines.append('  "is_coherent": <bool>,')
    lines.append('  "title": "<≤80 chars; entity-driven; what is happening>",')
    lines.append('  "blurb": "<one sentence ≤200 chars; the actual insight>",')
    lines.append('  "tags": ["<3-5 entity/topic tags; no stop-words>"],')
    lines.append('  "rejection_reason": "<≤80 chars; ONLY when is_coherent=false>"')
    lines.append("}")
    lines.append("")
    lines.append("Rules:")
    lines.append("- is_coherent=false when the headlines are unrelated topics")
    lines.append("  (e.g. one is sports, another is finance, another is tech).")
    lines.append("- title must reference a real entity / event / trend, not")
    lines.append("  meta-stats like 'demand spike' or 'opportunity window'.")
    lines.append("- blurb must state what is happening in plain English.")
    lines.append("- tags are nouns (company names, technologies, regions);")
    lines.append("  no filler words like 'want', 'now', 'suggestion'.")
    return "\n".join(lines)


def _parse_llm_response(content: str) -> dict:
    """Extract the JSON object from the LLM's response.

    gpt-4o-mini is usually well-behaved with json_object response_format,
    but we still guard against fence wrappers / leading prose just in case.
    """
    content = (content or "").strip()
    if content.startswith("```"):
        # Strip code fence.
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    # Find the first { and last } and slice.
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError(f"no JSON object found in LLM response: {content[:200]!r}")
    return json.loads(content[start:end + 1])


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def summarize_cluster(
    cluster: SignalCluster,
    evidence: list[EvidenceCard],
    *,
    client: Optional[OpenAI] = None,
    model: str = DEFAULT_MODEL,
) -> Optional[SummaryResult]:
    """Send one cluster + its evidence to the LLM, parse the response.

    Returns None when there's no evidence to summarize (e.g. cluster
    with zero evidence cards — those are effectively unverifiable and
    should stay `raw`).

    Raises on LLM errors (bad API key, rate-limit, malformed response)
    — caller decides whether to retry or mark `rejected`.
    """
    capped = evidence[:MAX_EVIDENCE_PER_CLUSTER]
    claim_texts = [(ec.claim_text or "").strip() for ec in capped if ec.claim_text]
    domains = [(ec.source_domain or "").strip() for ec in capped if ec.source_domain]

    if not claim_texts:
        return None

    content_hash = _compute_content_hash(claim_texts, domains)
    prompt = _build_prompt(claim_texts, domains)

    if client is None:
        client = OpenAI()

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_completion_tokens=MAX_COMPLETION_TOKENS,
    )
    raw = resp.choices[0].message.content or ""
    parsed = _parse_llm_response(raw)

    is_coherent = bool(parsed.get("is_coherent"))
    title = str(parsed.get("title") or "").strip()[:500]
    blurb = str(parsed.get("blurb") or "").strip()[:500]
    tags_raw = parsed.get("tags") or []
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for t in tags_raw[:5]:
            if isinstance(t, str) and t.strip():
                tags.append(t.strip()[:40])
    rejection_reason = str(parsed.get("rejection_reason") or "").strip()[:200]

    usage = resp.usage
    return SummaryResult(
        is_coherent=is_coherent,
        title=title,
        blurb=blurb,
        tags=tags,
        rejection_reason=rejection_reason if not is_coherent else "",
        content_hash=content_hash,
        model_used=model,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )


def apply_summary_to_cluster(
    cluster: SignalCluster,
    result: SummaryResult,
) -> None:
    """Persist a SummaryResult back onto a SignalCluster.

    Sets `summary_quality`, the summarized_* fields, and bookkeeping.
    The caller is responsible for committing the session.
    """
    cluster.summarized_content_hash = result.content_hash
    cluster.summarized_at = datetime.utcnow()
    if result.is_coherent and result.title and result.blurb:
        cluster.summary_quality = QUALITY_SUMMARIZED
        cluster.summarized_title = result.title
        cluster.summarized_blurb = result.blurb
        cluster.clean_tags = result.tags or None
    else:
        cluster.summary_quality = QUALITY_REJECTED
        cluster.summarized_title = None
        cluster.summarized_blurb = result.rejection_reason or None
        cluster.clean_tags = None


def should_skip(cluster: SignalCluster, content_hash: str) -> bool:
    """Idempotency check — same input hash + already summarized = skip.

    Returns True when the cluster has been summarized against this
    exact input set already. Caller passes in the freshly computed
    content_hash from the cluster's current evidence.
    """
    if cluster.summary_quality == QUALITY_RAW:
        return False
    return cluster.summarized_content_hash == content_hash


# ──────────────────────────────────────────────────────────────────────
# Batch processor (used by the CLI + future cron)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class BatchResult:
    """Aggregate stats for a batch run."""

    candidates: int = 0
    skipped_idempotent: int = 0
    summarized: int = 0
    rejected: int = 0
    errors: int = 0
    input_tokens_total: int = 0
    output_tokens_total: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        """gpt-4o-mini pricing as of 2026-05: $0.15/$0.60 per 1M tokens."""
        return (
            self.input_tokens_total * 0.15 / 1_000_000
            + self.output_tokens_total * 0.60 / 1_000_000
        )


def summarize_pending(
    session: Session,
    *,
    limit: Optional[int] = None,
    client: Optional[OpenAI] = None,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
) -> BatchResult:
    """Walk all `raw` clusters (and stale-hash `summarized` clusters)
    and run the LLM summary on each.

    Args:
        session: SQLAlchemy session bound to signal-studio's DB.
        limit:   Cap the number of clusters processed in one run.
                 Useful for cost-bounded backfills.
        client:  Optional preconstructed OpenAI client (test hook).
        model:   LLM model name. Defaults to gpt-4o-mini.
        dry_run: When True, prints what would happen but doesn't call
                 the LLM or persist.

    Returns BatchResult with cost estimate.
    """
    if client is None and not dry_run:
        client = OpenAI()

    q = session.query(SignalCluster).filter(
        SignalCluster.summary_quality.in_([QUALITY_RAW, QUALITY_SUMMARIZED, QUALITY_REJECTED])
    ).order_by(SignalCluster.created_at.desc())
    if limit is not None:
        q = q.limit(limit)

    result = BatchResult()
    for cluster in q:
        result.candidates += 1
        evidence = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.cluster_id == cluster.id)
            .order_by(EvidenceCard.created_at)
            .limit(MAX_EVIDENCE_PER_CLUSTER)
            .all()
        )
        if not evidence:
            logger.debug("[summarizer] cluster=%s has no evidence; skipping", cluster.id)
            continue

        claim_texts = [(ec.claim_text or "").strip() for ec in evidence if ec.claim_text]
        domains = [(ec.source_domain or "").strip() for ec in evidence if ec.source_domain]
        if not claim_texts:
            continue
        content_hash = _compute_content_hash(claim_texts, domains)

        if should_skip(cluster, content_hash):
            result.skipped_idempotent += 1
            continue

        if dry_run:
            logger.info(
                "[summarizer:dry] cluster=%s title=%r would-call-llm",
                str(cluster.id)[:8], cluster.title[:60],
            )
            continue

        try:
            summary = summarize_cluster(cluster, evidence, client=client, model=model)
        except Exception as e:
            logger.warning(
                "[summarizer] llm-error cluster=%s err=%s",
                str(cluster.id)[:8], e,
            )
            result.errors += 1
            continue
        if summary is None:
            continue

        apply_summary_to_cluster(cluster, summary)
        result.input_tokens_total += summary.input_tokens
        result.output_tokens_total += summary.output_tokens
        if summary.is_coherent:
            result.summarized += 1
            logger.info(
                "[summarizer] ok cluster=%s -> %r",
                str(cluster.id)[:8], summary.title[:60],
            )
        else:
            result.rejected += 1
            logger.info(
                "[summarizer] rejected cluster=%s reason=%r",
                str(cluster.id)[:8], summary.rejection_reason[:60],
            )

    if not dry_run:
        session.commit()
    return result


# ──────────────────────────────────────────────────────────────────────
# Optional dotenv loading for CLI / script use outside the container
# ──────────────────────────────────────────────────────────────────────


def _check_api_key() -> Optional[str]:
    """Return None when OPENAI_API_KEY is configured; error string otherwise."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return "OPENAI_API_KEY is not set"
    if key == "test-only" or key == "your-key-here":
        return f"OPENAI_API_KEY is a placeholder ({key!r}) — set the real key"
    if not (key.startswith("sk-") or key.startswith("sk_")):
        return f"OPENAI_API_KEY does not look like an OpenAI key (starts with {key[:6]!r})"
    return None


__all__ = [
    "SummaryResult",
    "BatchResult",
    "QUALITY_RAW",
    "QUALITY_SUMMARIZED",
    "QUALITY_REJECTED",
    "DEFAULT_MODEL",
    "summarize_cluster",
    "summarize_pending",
    "apply_summary_to_cluster",
    "should_skip",
]
