"""Swarmchaser: find and characterise coordinated agent swarms in multi-agent logs."""

from .detector import DetectorConfig, Swarm, SwarmDetector, summarise
from .features import normalise, post_features
from .loader import load_moltbook

__all__ = ["DetectorConfig", "Swarm", "SwarmDetector", "summarise", "normalise",
           "post_features", "load_moltbook"]
