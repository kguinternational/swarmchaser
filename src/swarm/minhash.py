"""MinHash + LSH banding for near-duplicate templates.

Exact template hashing misses swarms that perturb wording slightly (swap a
word, add a sentence). Banding over word-bigram MinHash signatures gives every
template a set of bucket keys; two templates with Jaccard similarity ``s``
share at least one bucket with probability ``1 - (1 - s^r)^b``. With the
defaults (b=30 bands, r=4 rows) that is ~0.86 at s=0.5, ~0.54 at s=0.4 and
~0.05 at s=0.2.

Bigrams, not trigrams: in a 35-word post every swapped word destroys k
shingles, so three synonym swaps already push trigram Jaccard down to ~0.3
while bigram Jaccard stays near 0.5.

Buckets are candidate generation only. Using bucket collisions directly as
links chained thousands of unrelated "hi, I'm an AI assistant that helps my
human with..." introductions into one false swarm on Moltbook, so
:meth:`SwarmDetector._near_clusters` verifies every candidate pair with the
exact Jaccard before linking it.
"""

from __future__ import annotations

import zlib

import numpy as np

_P = np.uint64((1 << 61) - 1)


class MinHasher:
    def __init__(self, bands: int = 30, rows: int = 4, shingle: int = 2, seed: int = 7):
        self.bands, self.rows, self.shingle = bands, rows, shingle
        rng = np.random.default_rng(seed)
        n = bands * rows
        self.a = rng.integers(1, 1 << 31, size=n, dtype=np.uint64)
        self.b = rng.integers(0, 1 << 31, size=n, dtype=np.uint64)

    def signature(self, text: str) -> np.ndarray | None:
        toks = text.split()
        if len(toks) < self.shingle + 3:
            return None
        sh = {zlib.crc32(" ".join(toks[i:i + self.shingle]).encode()) for i in range(len(toks) - self.shingle + 1)}
        x = np.fromiter(sh, dtype=np.uint64)
        # (a*x + b) mod p, min over shingles. a < 2^31 and x < 2^32, so the
        # product stays below 2^63 and uint64 arithmetic cannot overflow.
        h = (np.outer(self.a, x) + self.b[:, None]) % _P
        return h.min(axis=1)

    def bucket_keys(self, text: str) -> list[str]:
        sig = self.signature(text)
        if sig is None:
            return []
        out = []
        for i in range(self.bands):
            band = sig[i * self.rows:(i + 1) * self.rows]
            out.append(f"near:{i}:{zlib.crc32(band.tobytes()):08x}")
        return out

    @staticmethod
    def jaccard(a: str, b: str, shingle: int = 2) -> float:
        def sh(t):
            w = t.split()
            return {" ".join(w[i:i + shingle]) for i in range(max(0, len(w) - shingle + 1))}
        A, B = sh(a), sh(b)
        return len(A & B) / len(A | B) if A and B else 0.0
