#!/usr/bin/env python3
"""Signal Studio doc-claim verifier.

Compares what authoritative docs claim about the platform against what
the runtime actually shows. Ported from u-d-b's
``core/services/doc_claim_verification.py`` (Session 1099, simplified
for FastAPI repos — no Django coupling, no DB-skip helper).

## Concepts

- ``ClaimResult`` — structured verdict for a single claim
- ``@register_claim`` — decorator that registers a verifier
- ``run_all`` / ``summarize`` — runner + reporter

## Adding a claim

```python
@register_claim(doc="docs/PROJECT_WHAT_IT_IS.md", claim_id="thing_count",
                description="Doc claims N things; verifier counts them.")
def _thing_count():
    actual = ...   # query the code/runtime
    expected = 7   # what the doc asserts
    return ClaimResult.build(
        expected=expected, actual=actual,
        severity='ok' if expected == actual else 'medium',
        fix_suggestion=f"Update docs/PROJECT_WHAT_IT_IS.md to '{actual} things'"
                       if expected != actual else None,
    )
```

## CLI

```
python scripts/verify_doc_claims.py                  # all claims
python scripts/verify_doc_claims.py --doc docs/PROJECT_WHAT_IT_IS.md
python scripts/verify_doc_claims.py --only-drift
python scripts/verify_doc_claims.py --format json
python scripts/verify_doc_claims.py --list
python scripts/verify_doc_claims.py --fail-on-drift  # for CI
```
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


# ============================================================================
# Framework
# ============================================================================

SEVERITIES = ('ok', 'low', 'medium', 'high', 'critical', 'error')


@dataclass
class ClaimResult:
    matched: bool
    expected: Any
    actual: Any
    severity: str = 'ok'
    note: Optional[str] = None
    fix_suggestion: Optional[str] = None
    doc: str = ''
    claim_id: str = ''
    description: str = ''
    runtime_ms: int = 0
    error: Optional[str] = None

    @classmethod
    def build(
        cls,
        expected: Any,
        actual: Any,
        severity: str = 'ok',
        note: Optional[str] = None,
        fix_suggestion: Optional[str] = None,
    ) -> 'ClaimResult':
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {severity!r}")
        return cls(
            matched=(severity == 'ok'),
            expected=expected,
            actual=actual,
            severity=severity,
            note=note,
            fix_suggestion=fix_suggestion,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, (list, tuple, set)):
                d[k] = [x if isinstance(x, (str, int, float, bool, type(None))) else str(x) for x in v]
            elif not isinstance(v, (str, int, float, bool, type(None), dict, list)):
                d[k] = str(v)
        return d


@dataclass
class _RegisteredClaim:
    doc: str
    claim_id: str
    description: str
    verifier: Callable[[], ClaimResult]


_REGISTRY: list[_RegisteredClaim] = []


def register_claim(doc: str, claim_id: str, description: str = ''):
    def _deco(fn: Callable[[], ClaimResult]) -> Callable[[], ClaimResult]:
        _REGISTRY.append(_RegisteredClaim(
            doc=doc,
            claim_id=claim_id,
            description=description or (fn.__doc__ or '').strip(),
            verifier=fn,
        ))
        return fn
    return _deco


def list_registered() -> list[dict]:
    return [
        {
            'doc': c.doc,
            'claim_id': c.claim_id,
            'description': (c.description or '').strip().splitlines()[0] if c.description else '',
        }
        for c in _REGISTRY
    ]


def run_one(claim: _RegisteredClaim) -> ClaimResult:
    t0 = time.monotonic()
    try:
        result = claim.verifier()
        if not isinstance(result, ClaimResult):
            raise TypeError(
                f"Claim {claim.doc}:{claim.claim_id} returned {type(result).__name__}, expected ClaimResult"
            )
    except Exception as e:  # noqa: BLE001
        result = ClaimResult(
            matched=False,
            expected=None,
            actual=None,
            severity='error',
            note=f"Verifier raised {type(e).__name__}: {e}",
            error=traceback.format_exc(limit=3),
        )
    result.doc = claim.doc
    result.claim_id = claim.claim_id
    result.description = claim.description
    result.runtime_ms = int((time.monotonic() - t0) * 1000)
    return result


def run_all(doc_filter: Optional[str] = None, only_drift: bool = False) -> list[ClaimResult]:
    results: list[ClaimResult] = []
    for claim in _REGISTRY:
        if doc_filter and claim.doc != doc_filter:
            continue
        r = run_one(claim)
        if only_drift and r.severity == 'ok':
            continue
        results.append(r)
    return results


def summarize(results: list[ClaimResult]) -> dict:
    by_severity: dict[str, int] = {s: 0 for s in SEVERITIES}
    by_doc: dict[str, dict] = {}
    for r in results:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        d = by_doc.setdefault(r.doc, {'total': 0, 'ok': 0, 'drift': 0, 'error': 0})
        d['total'] += 1
        if r.severity == 'ok':
            d['ok'] += 1
        elif r.severity == 'error':
            d['error'] += 1
        else:
            d['drift'] += 1
    return {'total': len(results), 'by_severity': by_severity, 'by_doc': by_doc}


# ============================================================================
# Claims — signal-studio seed (2)
# ============================================================================
#
# signal-studio's narrative is mostly categorical (3 source types, 3
# signal attributes) rather than numerical. v0 ships two pattern
# variants: a presence/absence assertion + a list-count baseline.


@register_claim(
    doc='docs/PROJECT_WHAT_IT_IS.md',
    claim_id='action_engine_llm_free',
    description="Narrative claims 'no LLM dependency' for MVP action engine; verifier asserts no `openai` import in backend/app/main.py.",
)
def _action_engine_llm_free() -> ClaimResult:
    main_path = REPO_ROOT / "backend" / "app" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    openai_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openai" or alias.name.startswith("openai."):
                    openai_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "openai" or module.startswith("openai."):
                openai_imports.append(module)
    expected = 0  # docs/PROJECT_WHAT_IT_IS.md: "no LLM dependency"
    actual = len(openai_imports)
    return ClaimResult.build(
        expected=expected,
        actual=actual,
        severity='ok' if expected == actual else 'high',
        note=f"openai imports found: {openai_imports}" if openai_imports else None,
        fix_suggestion=(
            f"Narrative claims 'no LLM dependency' but main.py imports {openai_imports}. "
            f"Either remove the imports or update PROJECT_WHAT_IT_IS to remove the 'no LLM' claim."
            if expected != actual else None
        ),
    )


@register_claim(
    doc='docs/PROJECT_WHAT_IT_IS.md',
    claim_id='demo_cluster_count',
    description="DEMO_CLUSTERS in seed.py — baseline regression check; bump expected= when seed changes intentionally.",
)
def _demo_cluster_count() -> ClaimResult:
    seed_path = REPO_ROOT / "backend" / "app" / "seed.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    actual = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "DEMO_CLUSTERS":
                if isinstance(node.value, ast.List):
                    actual = len(node.value.elts)
                break
    if actual is None:
        return ClaimResult.build(
            expected=5,
            actual=None,
            severity='error',
            note="Could not locate DEMO_CLUSTERS list in backend/app/seed.py",
        )
    expected = 5  # Baseline at verifier creation (Session 1120)
    return ClaimResult.build(
        expected=expected,
        actual=actual,
        severity='ok' if expected == actual else 'low',
        fix_suggestion=(
            f"DEMO_CLUSTERS count changed to {actual} (baseline was {expected}). "
            f"If intentional, bump expected= here; otherwise restore seed data."
            if expected != actual else None
        ),
    )


# ============================================================================
# Renderers
# ============================================================================

SEVERITY_ICONS = {
    'ok': '✓',
    'low': '·',
    'medium': '●',
    'high': '▲',
    'critical': '■',
    'error': '?',
}


def render_text(results: list[ClaimResult], summary: dict) -> None:
    if not results:
        print("No matching claims to run.")
        return
    by_doc: dict[str, list[ClaimResult]] = {}
    for r in results:
        by_doc.setdefault(r.doc, []).append(r)
    for doc, items in sorted(by_doc.items()):
        print()
        print(f"── {doc} ──")
        for r in items:
            icon = SEVERITY_ICONS.get(r.severity, '·')
            print(f"  {icon} [{r.severity:>8}] {r.claim_id}")
            if r.description:
                print(f"      claim: {r.description.strip().splitlines()[0][:100]}")
            if r.severity != 'ok':
                print(f"      expected: {r.expected}")
                print(f"      actual:   {r.actual}")
            if r.note:
                print(f"      note:     {r.note}")
            if r.fix_suggestion:
                print(f"      fix:      {r.fix_suggestion}")
            if r.error:
                print(f"      error:    {r.error.strip().splitlines()[-1][:200]}")
    print()
    print("── Summary ──")
    print(f"  total: {summary['total']}")
    for sev in ('ok', 'low', 'medium', 'high', 'critical', 'error'):
        n = summary['by_severity'].get(sev, 0)
        if n > 0:
            print(f"  {sev:>8}: {n}")
    print()
    print("  by doc:")
    for doc, d in sorted(summary['by_doc'].items()):
        print(f"    {doc:40} ok={d['ok']:>2}  drift={d['drift']:>2}  error={d['error']:>2}")


def render_list(entries: list[dict]) -> None:
    by_doc: dict[str, list[dict]] = {}
    for e in entries:
        by_doc.setdefault(e['doc'], []).append(e)
    print(f"Registered claims: {len(entries)} across {len(by_doc)} docs")
    for doc, items in sorted(by_doc.items()):
        print(f"\n  {doc}")
        for it in items:
            desc = (it.get('description') or '')
            print(f"    · {it['claim_id']:40} — {desc[:80]}")


# ============================================================================
# CLI
# ============================================================================


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify doc claims against runtime reality.",
    )
    parser.add_argument('--doc', help='Filter to a single doc path')
    parser.add_argument('--only-drift', action='store_true', help='Hide ok results')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    parser.add_argument('--list', action='store_true',
                        help='List registered claims without running them')
    parser.add_argument('--fail-on-drift', action='store_true',
                        help='Exit non-zero on any drift (use for CI)')
    args = parser.parse_args(argv)

    if args.list:
        entries = list_registered()
        if args.format == 'json':
            print(json.dumps(entries, indent=2))
        else:
            render_list(entries)
        return 0

    results = run_all(doc_filter=args.doc, only_drift=args.only_drift)
    summary = summarize(results)

    if args.format == 'json':
        payload = {'summary': summary, 'results': [r.to_dict() for r in results]}
        print(json.dumps(payload, indent=2, default=str))
    else:
        render_text(results, summary)

    if args.fail_on_drift:
        ok_count = summary['by_severity'].get('ok', 0)
        if summary['total'] > 0 and ok_count < summary['total']:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
