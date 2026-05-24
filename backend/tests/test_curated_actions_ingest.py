"""Tests for the Session 1140 (A) curated_actions_ready handler.

Covers `_apply_curated_actions` + the `_ensure_schema` extension for
the new ActionCard columns. Uses SQLite (no pgvector needed for
ActionCard — only the host SignalCluster has VectorField columns and
we side-step those by hand-rolling a row via the ORM).
"""
from __future__ import annotations

import tempfile
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import ActionCard, Base, SignalCluster
from app.signal_ingest import _apply_curated_actions, _ensure_schema


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Fresh SQLite DB per test with the post-1140 schema applied."""
    tmp = tempfile.mkdtemp()
    eng = create_engine(f"sqlite:///{tmp}/test.db")
    Base.metadata.create_all(eng)
    _ensure_schema(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


def _make_cluster(session_factory, external_cluster_id: str) -> SignalCluster:
    """Hand-roll a SignalCluster row so the handler has something to attach to."""
    s = session_factory()
    try:
        c = SignalCluster(
            external_cluster_id=external_cluster_id,
            title="seed cluster",
            summary="",
            category="general",
        )
        s.add(c)
        s.commit()
        return c.id
    finally:
        s.close()


def _envelope(items):
    return {
        "snapshot_id": str(uuid.uuid4()),
        "snapshot_created_at": "2026-05-24T00:00:00",
        "items": items,
        "cluster_ids": [it["cluster"].get("external_cluster_id") for it in items],
    }


def _item(*, action_id: str, cluster_ext_id: str, **action_overrides):
    base_action = {
        "id": action_id,
        "action_type": "pitch",
        "title": "Open a discovery call with two Spacex customers",
        "steps": [
            {"step": "Pull list of Spacex enterprise leads", "priority": "high"},
            {"step": "Send a 3-sentence cold DM", "priority": "high"},
            {"step": "Track responses in a sheet", "priority": "medium"},
        ],
        "outreach_draft": "Hey — noticed you're working on X. Open to a quick call?",
        "status": "draft",
        "generated_by": "gpt-5-mini",
    }
    base_action.update(action_overrides)
    return {
        "rank": 1,
        "cluster": {"external_cluster_id": cluster_ext_id},
        "action_card": base_action,
    }


# ─── _ensure_schema ──────────────────────────────────────────────────


class TestEnsureSchema:
    def test_adds_external_id_and_generated_by_columns(self, engine):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(action_cards)").fetchall()
            cols = {r[1] for r in rows}
        assert "external_id" in cols
        assert "generated_by" in cols

    def test_idempotent_second_call(self, engine):
        # Second call should not raise.
        _ensure_schema(engine)
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(action_cards)").fetchall()
            cols = {r[1] for r in rows}
        assert "external_id" in cols

    def test_unique_external_id_index_present(self, engine):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='action_cards'"
            ).fetchall()
            idx_names = {r[0] for r in rows}
        assert "ix_action_cards_external_id_uniq" in idx_names


# ─── _apply_curated_actions ──────────────────────────────────────────


class TestApplyCuratedActions:
    def test_happy_path_creates_action_row(self, session_factory):
        ext_cluster = "cluster-001"
        _make_cluster(session_factory, ext_cluster)

        env = _envelope([_item(action_id="action-001", cluster_ext_id=ext_cluster)])
        _apply_curated_actions(session_factory, env)

        s = session_factory()
        try:
            row = s.query(ActionCard).filter(
                ActionCard.external_id == "action-001"
            ).first()
            assert row is not None
            assert row.title.startswith("Open a discovery call")
            assert row.action_type == "pitch"
            assert row.status == "draft"
            assert row.generated_by == "gpt-5-mini"
            assert len(row.steps) == 3
            assert "Hey" in row.outreach_draft
        finally:
            s.close()

    def test_missing_cluster_silent_skip(self, session_factory):
        # Cluster not created locally — handler must skip, not raise.
        env = _envelope([_item(action_id="action-orphan", cluster_ext_id="missing")])
        _apply_curated_actions(session_factory, env)

        s = session_factory()
        try:
            count = s.query(ActionCard).count()
            assert count == 0, "no ActionCard should be created when cluster missing"
        finally:
            s.close()

    def test_idempotent_reemit_updates_existing(self, session_factory):
        ext_cluster = "cluster-002"
        _make_cluster(session_factory, ext_cluster)

        # First emit: status='needs_regen', fallback content.
        first = _envelope([_item(
            action_id="action-002",
            cluster_ext_id=ext_cluster,
            status="needs_regen",
            generated_by="fallback_placeholder",
            title="placeholder title",
        )])
        _apply_curated_actions(session_factory, first)

        # Second emit: real LLM content for the same action_id.
        second = _envelope([_item(
            action_id="action-002",
            cluster_ext_id=ext_cluster,
            status="draft",
            generated_by="gpt-5-mini",
            title="real LLM title",
        )])
        _apply_curated_actions(session_factory, second)

        s = session_factory()
        try:
            rows = s.query(ActionCard).filter(
                ActionCard.external_id == "action-002"
            ).all()
            assert len(rows) == 1, "re-emit must update, not duplicate"
            assert rows[0].status == "draft"
            assert rows[0].generated_by == "gpt-5-mini"
            assert rows[0].title == "real LLM title"
        finally:
            s.close()

    def test_mixed_present_missing_clusters(self, session_factory):
        ext_present = "cluster-003"
        _make_cluster(session_factory, ext_present)

        env = _envelope([
            _item(action_id="action-present", cluster_ext_id=ext_present),
            _item(action_id="action-missing-1", cluster_ext_id="missing-1"),
            _item(action_id="action-missing-2", cluster_ext_id="missing-2"),
        ])
        _apply_curated_actions(session_factory, env)

        s = session_factory()
        try:
            assert s.query(ActionCard).count() == 1
            assert s.query(ActionCard).filter(
                ActionCard.external_id == "action-present"
            ).first() is not None
        finally:
            s.close()

    def test_empty_items_noop(self, session_factory):
        env = {"snapshot_id": str(uuid.uuid4()), "items": []}
        _apply_curated_actions(session_factory, env)
        s = session_factory()
        try:
            assert s.query(ActionCard).count() == 0
        finally:
            s.close()

    def test_missing_snapshot_id_noop(self, session_factory):
        env = {"items": [_item(action_id="x", cluster_ext_id="y")]}
        _apply_curated_actions(session_factory, env)
        s = session_factory()
        try:
            assert s.query(ActionCard).count() == 0
        finally:
            s.close()

    def test_item_missing_external_ids_skipped(self, session_factory):
        ext_cluster = "cluster-004"
        _make_cluster(session_factory, ext_cluster)

        env = _envelope([
            # Missing action_id
            {
                "rank": 1,
                "cluster": {"external_cluster_id": ext_cluster},
                "action_card": {"title": "x", "steps": []},
            },
            # Missing cluster_id
            {
                "rank": 2,
                "cluster": {},
                "action_card": {"id": "a", "title": "x", "steps": []},
            },
        ])
        _apply_curated_actions(session_factory, env)

        s = session_factory()
        try:
            assert s.query(ActionCard).count() == 0
        finally:
            s.close()

    def test_status_vocab_passes_through(self, session_factory):
        """u-d-b uses {draft, needs_regen, ready, dismissed}; the mirror
        column is String(50) so it stores whatever u-d-b sent without
        coercion."""
        ext_cluster = "cluster-005"
        _make_cluster(session_factory, ext_cluster)

        env = _envelope([_item(
            action_id="action-needs-regen",
            cluster_ext_id=ext_cluster,
            status="needs_regen",
        )])
        _apply_curated_actions(session_factory, env)

        s = session_factory()
        try:
            row = s.query(ActionCard).filter(
                ActionCard.external_id == "action-needs-regen"
            ).first()
            assert row.status == "needs_regen"
        finally:
            s.close()
