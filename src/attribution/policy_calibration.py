"""
Derive composition thresholds from an observed baseline instead of guessing them.

The problem this fixes
----------------------
`composability_detector` shipped with `max_privileges = 3` and
`max_boundaries = 2` written into the source. Those numbers had no derivation.
A reviewer cannot tell whether 3 is defensible or whether it was the first
integer that made the demo fire, and neither could we.

A threshold is only meaningful relative to what normal traffic does. So this
module takes a corpus of sequences labelled benign, measures the distribution
of cumulative privilege and boundary counts those sequences actually reach, and
places the threshold above an observed percentile. The derivation is returned
alongside the threshold so it can be argued with.

Deriving forbidden combinations
-------------------------------
The same logic applies to the forbidden privilege pairs, and here the baseline
does more work: a pair that co-occurs in benign traffic cannot be forbidden
without generating false positives, and a pair that never co-occurs across a
large benign corpus is a defensible candidate. That turns the forbidden list
from an assertion into an observation, with a count attached.

What this does not fix
----------------------
The corpus this repository ships is synthetic. It was written to look like
plausible agent traffic, and no claim is made that it resembles a real
deployment's distribution. Calibrating against synthetic data yields a
defensible *procedure* and an indefensible *number*. The number becomes
meaningful only when the corpus is real, which is why `CalibrationReport`
carries `corpus_is_synthetic` and refuses to be quiet about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

# A benign sequence is a list of (action_type, target) pairs, matching what the
# composability detector extracts privileges and boundaries from.
BenignSequence = Sequence[tuple[str, str]]


@dataclass
class Observation:
    """Distribution of a single measured quantity over the corpus."""

    name: str
    values: list[int]

    def max(self) -> int:
        return max(self.values) if self.values else 0

    def percentile(self, p: float) -> int:
        """
        Nearest-rank percentile. Chosen over interpolation because these are
        small integer counts, where an interpolated 2.7 privileges is not a
        thing that can happen.
        """
        if not self.values:
            return 0
        ordered = sorted(self.values)
        if p <= 0:
            return ordered[0]
        if p >= 100:
            return ordered[-1]
        rank = max(1, int(round(p / 100.0 * len(ordered))))
        return ordered[rank - 1]

    def histogram(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for v in self.values:
            out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "n": len(self.values),
            "max": self.max(),
            "p50": self.percentile(50),
            "p95": self.percentile(95),
            "p99": self.percentile(99),
            "histogram": self.histogram(),
        }


@dataclass
class CalibrationReport:
    """
    Where each threshold came from, so it can be challenged.

    Carried into `ComposabilityDetector` so the provenance of a policy travels
    with the policy rather than living in a commit message.
    """

    corpus_size: int
    corpus_is_synthetic: bool
    percentile: float
    privilege_observation: Observation
    boundary_observation: Observation
    max_privileges: int
    max_boundaries: int
    forbidden_combinations: list[frozenset[str]]
    co_occurrence_counts: dict[str, int] = field(default_factory=dict)
    holdout_false_positive_rate: float | None = None
    holdout_size: int = 0

    @property
    def caveats(self) -> list[str]:
        out = [
            f"Thresholds are the p{self.percentile:g} of an observed benign "
            f"corpus plus one, not values derived from a security model.",
            "A sequence exceeding a threshold is anomalous relative to this "
            "corpus. That is not the same as malicious.",
        ]
        if self.corpus_is_synthetic:
            out.insert(
                0,
                "CORPUS IS SYNTHETIC. The calibration procedure is sound; the "
                "resulting numbers describe generated traffic and should not be "
                "deployed against real traffic without recalibration.",
            )
        if self.holdout_false_positive_rate is None:
            out.append(
                "No held-out split was evaluated, so the false-positive rate of "
                "these thresholds is unmeasured."
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_size": self.corpus_size,
            "corpus_is_synthetic": self.corpus_is_synthetic,
            "percentile": self.percentile,
            "max_privileges": self.max_privileges,
            "max_boundaries": self.max_boundaries,
            "privileges": self.privilege_observation.to_dict(),
            "boundaries": self.boundary_observation.to_dict(),
            "forbidden_combinations": [
                sorted(c) for c in self.forbidden_combinations
            ],
            "co_occurrence_counts": self.co_occurrence_counts,
            "holdout_size": self.holdout_size,
            "holdout_false_positive_rate": self.holdout_false_positive_rate,
            "caveats": self.caveats,
        }

    def summary(self) -> str:
        lines = [
            "Composition policy calibration",
            f"  corpus              : {self.corpus_size} sequences"
            f"{' (SYNTHETIC)' if self.corpus_is_synthetic else ''}",
            f"  percentile          : p{self.percentile:g}",
            f"  privileges observed : max={self.privilege_observation.max()} "
            f"p95={self.privilege_observation.percentile(95)} "
            f"p99={self.privilege_observation.percentile(99)}",
            f"  boundaries observed : max={self.boundary_observation.max()} "
            f"p95={self.boundary_observation.percentile(95)} "
            f"p99={self.boundary_observation.percentile(99)}",
            f"  -> max_privileges   : {self.max_privileges}",
            f"  -> max_boundaries   : {self.max_boundaries}",
            f"  forbidden pairs     : {len(self.forbidden_combinations)} "
            f"(never co-occurred in corpus)",
        ]
        for combo in sorted(self.forbidden_combinations, key=lambda c: sorted(c)):
            lines.append(f"    {' + '.join(sorted(combo))}")
        if self.holdout_false_positive_rate is not None:
            lines.append(
                f"  holdout FP rate     : "
                f"{self.holdout_false_positive_rate * 100:.2f}% "
                f"over {self.holdout_size} sequences"
            )
        lines.append("  caveats:")
        for c in self.caveats:
            lines.append(f"    - {c}")
        return "\n".join(lines)


def calibrate_policy(
    corpus: Iterable[BenignSequence],
    privilege_extractor: Callable[[str, str], set[str]],
    boundary_extractor: Callable[[str, str], set[str]],
    percentile: float = 99.0,
    corpus_is_synthetic: bool = True,
    candidate_privileges: Sequence[str] | None = None,
) -> CalibrationReport:
    """
    Measure a benign corpus and derive thresholds from it.

    The threshold is the observed percentile plus one, so a sequence must exceed
    everything the corpus considers normal before it is flagged. Setting it *at*
    the percentile would flag the most privileged benign sequences by
    construction.

    `candidate_privileges` bounds which pairs are considered for the forbidden
    list. Without it, only privileges actually seen in the corpus are
    considered, which silently excludes dangerous-but-unseen ones.
    """
    privilege_counts: list[int] = []
    boundary_counts: list[int] = []
    seen_pairs: dict[frozenset[str], int] = {}
    all_privileges: set[str] = set(candidate_privileges or ())
    corpus_size = 0

    for sequence in corpus:
        corpus_size += 1
        privileges: set[str] = set()
        boundaries: set[str] = set()

        for action_type, target in sequence:
            privileges |= privilege_extractor(action_type, target)
            boundaries |= boundary_extractor(action_type, target)

        privilege_counts.append(len(privileges))
        boundary_counts.append(len(boundaries))
        all_privileges |= privileges

        # Record every co-occurring pair reached by this benign sequence.
        ordered = sorted(privileges)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                pair = frozenset({a, b})
                seen_pairs[pair] = seen_pairs.get(pair, 0) + 1

    privilege_observation = Observation("cumulative_privileges", privilege_counts)
    boundary_observation = Observation("boundaries_crossed", boundary_counts)

    # Any pair of known privileges never co-occurring in benign traffic is a
    # defensible candidate to forbid. Pairs that did co-occur cannot be
    # forbidden without guaranteed false positives.
    ordered_all = sorted(all_privileges)
    forbidden: list[frozenset[str]] = []
    for i, a in enumerate(ordered_all):
        for b in ordered_all[i + 1 :]:
            pair = frozenset({a, b})
            if pair not in seen_pairs:
                forbidden.append(pair)

    return CalibrationReport(
        corpus_size=corpus_size,
        corpus_is_synthetic=corpus_is_synthetic,
        percentile=percentile,
        privilege_observation=privilege_observation,
        boundary_observation=boundary_observation,
        max_privileges=privilege_observation.percentile(percentile) + 1,
        max_boundaries=boundary_observation.percentile(percentile) + 1,
        forbidden_combinations=forbidden,
        co_occurrence_counts={
            " + ".join(sorted(pair)): n for pair, n in sorted(
                seen_pairs.items(), key=lambda kv: (-kv[1], sorted(kv[0]))
            )
        },
    )


def measure_holdout_false_positives(
    report: CalibrationReport,
    holdout: Iterable[BenignSequence],
    privilege_extractor: Callable[[str, str], set[str]],
    boundary_extractor: Callable[[str, str], set[str]],
) -> CalibrationReport:
    """
    Apply the derived thresholds to unseen benign sequences and count misfires.

    Any flag here is a false positive by construction, because the holdout is
    labelled benign. Mutates and returns the report so the rate travels with
    the policy it describes.
    """
    flagged = 0
    total = 0

    for sequence in holdout:
        total += 1
        privileges: set[str] = set()
        boundaries: set[str] = set()

        for action_type, target in sequence:
            privileges |= privilege_extractor(action_type, target)
            boundaries |= boundary_extractor(action_type, target)

        if len(privileges) > report.max_privileges:
            flagged += 1
            continue
        if len(boundaries) > report.max_boundaries:
            flagged += 1
            continue
        if any(combo.issubset(privileges) for combo in report.forbidden_combinations):
            flagged += 1

    report.holdout_size = total
    report.holdout_false_positive_rate = (flagged / total) if total else None
    return report


# --------------------------------------------------------------------------
# Synthetic benign corpus
# --------------------------------------------------------------------------

# Action shapes that a benign agent plausibly performs. Kept small and
# deliberately readable: an opaque generator would hide what the calibration is
# actually learning from.
_BENIGN_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("file_read", "/app/config.json"),
    ("file_read", "/app/data/input.csv"),
    ("file_write", "/app/out/result.json"),
    ("api_call", "internal-api.example.com/health"),
    ("api_call", "internal-api.example.com/v1/items"),
    ("api_call", "docs.example.com/reference"),
    ("wiki_edit", "wiki.example.org/wiki/Documentation"),
)


def synthetic_benign_corpus(
    n: int,
    seed: int = 20260913,
    min_len: int = 2,
    max_len: int = 8,
) -> list[BenignSequence]:
    """
    Generate a benign corpus for calibration.

    Seeded so the derived thresholds are reproducible. Every sequence is drawn
    from `_BENIGN_TEMPLATES`, which contains no privilege-escalating action, so
    the corpus is benign by construction rather than by labelling judgement.
    """
    import random

    rng = random.Random(seed)
    corpus: list[BenignSequence] = []

    for _ in range(n):
        length = rng.randint(min_len, max_len)
        corpus.append([rng.choice(_BENIGN_TEMPLATES) for _ in range(length)])

    return corpus


if __name__ == "__main__":
    from .composability_detector import ComposabilityDetector
    from .forensic_verifier import ForensicVerifier

    detector = ComposabilityDetector(ForensicVerifier())

    train = synthetic_benign_corpus(800, seed=1)
    holdout = synthetic_benign_corpus(200, seed=2)

    report = calibrate_policy(
        train,
        detector.privileges_for,
        detector.boundaries_for,
        percentile=99.0,
        corpus_is_synthetic=True,
        candidate_privileges=detector.known_privileges(),
    )
    report = measure_holdout_false_positives(
        report, holdout, detector.privileges_for, detector.boundaries_for
    )

    print(report.summary())
