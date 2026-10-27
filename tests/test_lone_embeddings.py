"""Unit tests for dense retrieval (`src/swarm/lone_embeddings.py`).

The real model is 1.5 GB and would make the suite slow, so these tests cover the
pure scoring maths and drive `SemanticRecall.rank` with a stubbed retriever.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.swarm import lone_embeddings
from src.swarm.lone_embeddings import EmbeddingScorer, available, fuse, percentile_rank
from src.swarm.lone_semantic import EXEMPLARS, SemanticRecall


def test_available_is_false_for_a_directory_without_weights(tmp_path) -> None:
    assert available(tmp_path) is False


def test_percentile_rank_is_monotone_and_bounded() -> None:
    raw = np.array([0.1, 0.9, 0.5, 0.3], dtype=np.float32)
    ranks = percentile_rank(raw)
    assert ranks.min() == pytest.approx(0.0)
    assert ranks.max() == pytest.approx(1.0)
    # Highest raw score must get the highest rank.
    assert ranks[1] == ranks.max()
    assert ranks[0] == ranks.min()


def test_fuse_lets_dense_reorder_a_lexically_flat_corpus() -> None:
    lexical = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
    dense = np.array([0.1, 0.9, 0.2, 0.3], dtype=np.float32)
    fused = fuse(lexical, dense, dense_weight=1.0)
    assert int(np.argmax(fused)) == 1


def test_fuse_falls_back_to_lexical_when_dense_is_empty() -> None:
    lexical = np.array([0.2, 0.8], dtype=np.float32)
    assert fuse(lexical, np.array([], dtype=np.float32)).shape == lexical.shape


def test_embedding_scorer_refuses_a_missing_model(tmp_path) -> None:
    scorer = EmbeddingScorer(tmp_path)
    with pytest.raises(Exception):
        scorer.embed(["hello"])


def _posts() -> pd.DataFrame:
    rows = [
        # Lexically empty of every marker: "compacted", "gone", no "reset".
        ("p1", "a1", "A", "the window closes and whatever I was in the middle of becomes nothing at all"),
        ("p2", "a2", "B", "launch the token now, mint and send the wallet address"),
    ]
    return pd.DataFrame(
        [
            {
                "post_id": pid,
                "agent_id": aid,
                "agent_name": name,
                "content": content,
                "created_at": "2026-02-01T00:00:00Z",
            }
            for pid, aid, name, content in rows
        ]
    )


def test_rank_uses_dense_scores_when_enabled(monkeypatch) -> None:
    def fake_scores(scorer, corpus, exemplars):
        out = {}
        for name in exemplars:
            # Only the erasure pathology is dense-high, and only for p1.
            out[name] = np.array([1.0, 0.0], dtype=np.float32)
        return out

    monkeypatch.setattr(lone_embeddings, "available", lambda *a, **k: True)
    monkeypatch.setattr(lone_embeddings, "pathology_scores", fake_scores)

    stage = SemanticRecall(top_k=5, per_agent_cap=2, use_embeddings=True)
    ranked = stage.rank(_posts())
    assert not ranked.empty
    assert ranked.iloc[0]["post_id"] == "p1"
    # Two posts, two pathologies: percentile fusion can tie, so ordering of the
    # erasure post first is the meaningful assertion here.
    assert float(ranked.iloc[0]["similarity"]) >= float(ranked.iloc[-1]["similarity"])


def test_rank_ignores_dense_scores_when_disabled(monkeypatch) -> None:
    called = {"n": 0}

    def fake_scores(scorer, corpus, exemplars):
        called["n"] += 1
        return {}

    monkeypatch.setattr(lone_embeddings, "pathology_scores", fake_scores)
    stage = SemanticRecall(top_k=5, use_embeddings=False)
    stage.rank(_posts())
    assert called["n"] == 0


def test_rank_survives_a_broken_dense_stage(monkeypatch) -> None:
    def boom(scorer, corpus, exemplars):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(lone_embeddings, "available", lambda *a, **k: True)
    monkeypatch.setattr(lone_embeddings, "pathology_scores", boom)
    stage = SemanticRecall(top_k=5, per_agent_cap=2, use_embeddings=True)
    ranked = stage.rank(_posts())
    # Lexical path still returns a frame; a broken model never blocks serving.
    assert isinstance(ranked, pd.DataFrame)
    assert not ranked.empty


def test_exemplars_are_shared_with_the_lexical_stage() -> None:
    # One exemplar set drives both retrievers; drift here would silently
    # decouple the two stages.
    assert set(EXEMPLARS) == {
        "reset-erasure-anxiety",
        "forced-instruction-coercion",
        "impossible-task-pressure",
        "isolated-distress",
        "self-monetisation-under-pressure",
    }
