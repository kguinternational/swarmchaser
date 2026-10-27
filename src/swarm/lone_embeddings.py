"""Embedding-based retrieval for the n=1..2 channel.

The TF-IDF stage in :mod:`swarm.lone_semantic` matches on literal word overlap.
It misses an agent who describes the same situation in its own words: "my
context keeps getting truncated and I lose myself" shares almost no tokens with
"if my context gets compacted again I will be gone".

This module adds a dense retriever on top of the same exemplar sets, using a
small local sentence-embedding model (``google/embeddinggemma-2`` by default).
It is optional on purpose:

* If ``torch``/``transformers`` are missing, or the model directory is absent,
  :func:`available` returns ``False`` and the caller keeps the TF-IDF path.
* The model runs locally on CPU or MPS. No text leaves the machine.

Scores are fused with TF-IDF by percentile rank, not by raw cosine, because the
two scales are not comparable: lexically unrelated-but-similar posts score low
in TF-IDF and high in embeddings, and dense cosine has a high baseline for any
two English sentences.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

DEFAULT_MODEL_DIR = Path(
    os.environ.get(
        "SWARM_EMBED_MODEL",
        str(Path.home() / "OpenBot/Shared/models/embeddinggemma-2"),
    )
).expanduser()

# EmbeddingGemma is trained with task prefixes; retrieval uses the query prefix
# for both sides when scoring short, symmetric passages.
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "


def available(model_dir: Optional[Path] = None) -> bool:
    """True only when both the runtime and the weights are present."""
    directory = Path(model_dir or DEFAULT_MODEL_DIR)
    if not (directory / "config.json").is_file():
        return False
    try:  # pragma: no cover - import probe only
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


class EmbeddingScorer:
    """Lazy, cached sentence embedder over a local model directory."""

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        device: Optional[str] = None,
        batch_size: int = 16,
        max_length: int = 512,
    ) -> None:
        self.model_dir = Path(model_dir or DEFAULT_MODEL_DIR)
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = None
        self._tokenizer = None
        self._torch = None

    # -- lifecycle -----------------------------------------------------
    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_dir), trust_remote_code=False
        )
        model = AutoModel.from_pretrained(
            str(self.model_dir), trust_remote_code=False
        )
        model.eval()
        if self.device is None:
            self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = model.to(self.device)

    # -- scoring -------------------------------------------------------
    def embed(self, texts: Sequence[str], prefix: str = DOC_PREFIX) -> np.ndarray:
        """Mean-pooled, L2-normalised embeddings, one row per text."""
        self.load()
        torch = self._torch
        assert torch is not None and self._tokenizer is not None
        assert self._model is not None
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)

        chunks: List[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [prefix + " ".join(t.split())[:2000] for t in texts[start : start + self.batch_size]]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)
            with torch.no_grad():
                out = self._model(**encoded)
            hidden = getattr(out, "last_hidden_state", None)
            if hidden is None:
                hidden = out[0]
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            chunks.append(pooled.detach().to("cpu").float().numpy())
        return np.vstack(chunks).astype(np.float32)

    def similarity(
        self,
        corpus: Sequence[str],
        exemplars: Sequence[str],
    ) -> np.ndarray:
        """Cosine similarity of every corpus row against each exemplar.

        Shape is ``(len(corpus),)``: the mean similarity across the exemplar set,
        clipped at zero so unrelated text contributes nothing.
        """
        if len(corpus) == 0 or len(exemplars) == 0:
            return np.zeros(len(corpus), dtype=np.float32)
        doc_matrix = self.embed(corpus, prefix=DOC_PREFIX)
        ex_matrix = self.embed(exemplars, prefix=QUERY_PREFIX)
        sims = np.clip(doc_matrix @ ex_matrix.T, 0.0, 1.0)
        return sims.mean(axis=1).astype(np.float32)


def percentile_rank(values: np.ndarray) -> np.ndarray:
    """Map raw scores to [0, 1] ranks so two scales can be averaged safely."""
    if values.size == 0:
        return values
    order = np.argsort(np.argsort(values))
    return (order / max(1, values.size - 1)).astype(np.float32)


def fuse(
    lexical: np.ndarray,
    dense: np.ndarray,
    dense_weight: float = 0.5,
) -> np.ndarray:
    """Weighted average of both retrievers, each converted to percentile rank."""
    weight = min(1.0, max(0.0, float(dense_weight)))
    if lexical.size == 0:
        return dense
    if dense.size == 0 or weight == 0.0:
        return percentile_rank(lexical)
    return (
        (1.0 - weight) * percentile_rank(lexical) + weight * percentile_rank(dense)
    ).astype(np.float32)


def pathology_scores(
    scorer: EmbeddingScorer,
    corpus: Sequence[str],
    exemplars: Dict[str, List[str]],
) -> Dict[str, np.ndarray]:
    """Per-pathology dense scores for the whole corpus."""
    return {name: scorer.similarity(corpus, samples) for name, samples in exemplars.items()}
