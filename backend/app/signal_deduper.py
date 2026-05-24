"""Signal cluster deduplication.

After the LLM summarizer runs, some semantically-identical clusters
still survive — the upstream u-d-b signal_aggregation_service emits
multiple `Tableau Developer Remote Job` rows, multiple
`AI + SpaceX IPO + fragrance startup` lumps, etc. The summarizer can
only judge each cluster in isolation; it can't merge them.

This module catches those near-duplicates deterministically. Two
cluster representations are considered duplicates when EITHER:

    * Jaccard(clean_tags) >= TAG_JACCARD_THRESHOLD, OR
    * Jaccard(title_tokens_after_stopwords) >= TITLE_JACCARD_THRESHOLD

Stop-word filter on title tokens prevents short overlaps like
"AI", "and", "the" from triggering false merges. Both thresholds are
configurable.

Grouping uses Union-Find so a chain (A↔B, B↔C → A=B=C) collapses to
one representative. The kept cluster is the one with the highest
`signal_strength`; ties broken by `source_count` descending then
`created_at` descending.

Pure function (no DB writes, no ORM mutation). Returns the deduped
list of input rows plus a tiny audit struct for the API to surface
"hidden N duplicates" if useful.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


# ─── Thresholds (tunable) ─────────────────────────────────────────────

# Two clusters are merged when their clean_tags overlap this much. 0.4
# means: of the union of tags, 40% appear in both. Captures the
# "Tableau / Remote / Job Listings" quad cleanly without over-merging.
TAG_JACCARD_THRESHOLD = 0.4

# Title-token overlap fallback for cases where tags differ but the
# title essentially restates the same idea. 0.5 is stricter than tags
# because titles share more filler.
TITLE_JACCARD_THRESHOLD = 0.5

# Minimum tag-set size before the tag rule applies. With 1-tag rows
# you'd merge anything sharing the tag, which is too aggressive.
MIN_TAGS_FOR_TAG_DEDUP = 2

# Title stop-words. Kept short and project-specific (not a full NLTK
# list) so we own the heuristic.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at",
    "to", "for", "with", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "by", "via", "into", "amid", "after", "before", "while",
    "&",
})

# "Generic" tags that are too broad to count as a specific-tag match.
# When two clusters share only one of these (e.g. both tagged "AI"),
# that's not enough to merge them on its own. Specific proper-noun
# tags ("Tableau", "SpaceX", "Aave") are what should trigger merges.
_GENERIC_TAGS = frozenset({
    "ai", "tech", "technology", "business", "general", "news",
    "startups", "startup", "remote", "remote work", "data",
    "software", "industry", "market", "markets", "trend",
})


# ─── Output struct ────────────────────────────────────────────────────


@dataclass
class DedupResult:
    """Outcome of running deduplicate_clusters on a list of rows."""

    kept: list[Any]
    """Rows that survived the dedup pass, ordered by input order."""

    duplicates_merged: int
    """How many rows were absorbed into a kept row."""

    groups: list[list[str]]
    """Audit: each inner list is the set of cluster ids in a duplicate
    group, with the kept id first. Useful for surfacing "hidden N
    duplicates" or for debugging false merges."""


# ─── Tokenization helpers (pure) ──────────────────────────────────────


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize_title(title: str) -> set[str]:
    """Lowercase, strip non-alnum, drop stop-words. Returns a set."""
    if not title:
        return set()
    raw = _TOKEN_RE.findall(title.casefold())
    return {t for t in raw if t and t not in _STOPWORDS and len(t) > 1}


def _normalize_tags(tags) -> set[str]:
    """Lowercase + strip + drop empty tags. Accepts list or None."""
    if not tags:
        return set()
    out: set[str] = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        s = t.strip().casefold()
        if s:
            out.add(s)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    """|a ∩ b| / |a ∪ b|. 0 when both sets are empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ─── Cluster-shape adapter ────────────────────────────────────────────


def _cluster_view(row) -> dict:
    """Extract the dedup-relevant fields from either an ORM row or a dict.

    Lets the deduper run against SignalCluster instances directly OR
    against the dict representation /api/signals returns. Avoids ORM
    coupling in the dedup logic itself.
    """
    # Prefer the LLM-summarized fields when present (those are what the
    # user sees + what makes near-duplicates obvious).
    title = ""
    tags: list = []
    if isinstance(row, dict):
        title = row.get("title") or ""
        tags = row.get("tags") or []
        strength = row.get("signal_strength") or 0.0
        sources = row.get("source_count") or 0
        created_at = row.get("created_at") or ""
        row_id = row.get("id") or ""
    else:
        # ORM row — fall back through summarized_* then base columns.
        title = getattr(row, "summarized_title", None) or getattr(row, "title", "") or ""
        clean = getattr(row, "clean_tags", None)
        base = getattr(row, "tags", None)
        tags = clean if clean else (base or [])
        strength = getattr(row, "signal_strength", None) or 0.0
        sources = getattr(row, "source_count", None) or 0
        created = getattr(row, "created_at", None)
        created_at = created.isoformat() if created else ""
        row_id = str(getattr(row, "id", "") or "")
    return {
        "id": row_id,
        "title_tokens": _tokenize_title(title),
        "tag_set": _normalize_tags(tags),
        "signal_strength": float(strength),
        "source_count": int(sources),
        "created_at": created_at,
    }


# ─── Union-Find primitives ────────────────────────────────────────────


class _UF:
    """Minimal Union-Find for n indices."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ─── Public API ───────────────────────────────────────────────────────


def deduplicate_clusters(
    rows: Iterable,
    *,
    tag_threshold: float = TAG_JACCARD_THRESHOLD,
    title_threshold: float = TITLE_JACCARD_THRESHOLD,
) -> DedupResult:
    """Collapse near-duplicate clusters.

    Args:
        rows: Iterable of SignalCluster ORM rows OR list-of-dicts (the
              shape /api/signals returns). The deduper introspects each
              row via `_cluster_view`.
        tag_threshold: Jaccard floor on tag overlap. Default 0.4.
        title_threshold: Jaccard floor on title-token overlap. Default 0.5.

    Returns:
        DedupResult with kept rows (same shape as input — ORM rows in,
        ORM rows out; dicts in, dicts out) preserving input order, plus
        audit fields.

    Algorithm:
        1. Build a view for each row (id, tokens, tags, strength).
        2. For all pairs (O(n²); n ≤ 50ish in practice), union them
           when either overlap threshold is met.
        3. For each group, pick the representative — highest strength,
           then source_count, then created_at.
        4. Return rows whose id matches a representative, in input order.
    """
    rows = list(rows)
    if len(rows) < 2:
        return DedupResult(kept=rows, duplicates_merged=0, groups=[])

    views = [_cluster_view(r) for r in rows]
    n = len(views)

    uf = _UF(n)
    for i in range(n):
        ti, gi = views[i]["title_tokens"], views[i]["tag_set"]
        for j in range(i + 1, n):
            tj, gj = views[j]["title_tokens"], views[j]["tag_set"]
            tag_dup = (
                len(gi) >= MIN_TAGS_FOR_TAG_DEDUP
                and len(gj) >= MIN_TAGS_FOR_TAG_DEDUP
                and _jaccard(gi, gj) >= tag_threshold
            )
            title_dup = (
                len(ti) >= 2
                and len(tj) >= 2
                and _jaccard(ti, tj) >= title_threshold
            )
            # Rule 3 — specific-tag rescue. Catches "Tableau Developer"
            # duplicates where the Jaccard scores both fall below
            # threshold but a rare proper-noun tag IS shared. We
            # require ≥1 shared specific (non-generic) tag AND ≥2
            # shared title tokens so we don't over-merge on generic
            # words alone.
            specific_shared = (gi & gj) - _GENERIC_TAGS
            shared_title_tokens = ti & tj
            specific_dup = (
                bool(specific_shared)
                and len(shared_title_tokens) >= 2
            )
            if tag_dup or title_dup or specific_dup:
                uf.union(i, j)

    # Group indices by root.
    groups_by_root: dict[int, list[int]] = {}
    for i in range(n):
        groups_by_root.setdefault(uf.find(i), []).append(i)

    # Pick a representative per group: highest strength, then
    # source_count, then created_at descending.
    keep_indices: set[int] = set()
    audit_groups: list[list[str]] = []
    for root, idxs in groups_by_root.items():
        if len(idxs) == 1:
            keep_indices.add(idxs[0])
            continue
        idxs.sort(
            key=lambda i: (
                -views[i]["signal_strength"],
                -views[i]["source_count"],
                # Reverse-iso created_at: lexicographic sort works on ISO-8601.
                # Negate by inverting the sort: we want NEWEST first, so prefix '~'.
                # Simpler: use the string as-is, then reverse the result.
            ),
        )
        # idxs[0] is the best by strength/source_count. For tie-breaking
        # on created_at, take the most recent.
        best = max(
            idxs,
            key=lambda i: (
                views[i]["signal_strength"],
                views[i]["source_count"],
                views[i]["created_at"],
            ),
        )
        keep_indices.add(best)
        # Build audit list with kept first.
        ordered_ids = [views[best]["id"]] + [
            views[i]["id"] for i in idxs if i != best
        ]
        audit_groups.append(ordered_ids)

    # Return rows in input order.
    kept_rows = [rows[i] for i in range(n) if i in keep_indices]
    duplicates_merged = n - len(kept_rows)

    return DedupResult(
        kept=kept_rows,
        duplicates_merged=duplicates_merged,
        groups=audit_groups,
    )


__all__ = [
    "deduplicate_clusters",
    "DedupResult",
    "TAG_JACCARD_THRESHOLD",
    "TITLE_JACCARD_THRESHOLD",
    "MIN_TAGS_FOR_TAG_DEDUP",
]
