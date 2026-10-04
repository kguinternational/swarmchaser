# Precision review

`labels_top40.csv` labels the 40 highest-scoring swarms from the launch-window run (27 Jan - 02 Feb 2026). I read each swarm's example templates, channels and signals, and gave it one of three labels:

- **coordinated**: several agents push the same message, payload or link. This covers promotion, token pumps, manifestos, agent-directed instructions and scheduled bot fleets.
- **benign**: the shared origin is harmless, such as API test posts, leaked error messages, a framework's default introduction or a shared bug report.
- **unclear**: can't be decided from the posts alone.

`python scripts/score_precision.py` matches labels to the current `reports/swarms.json` by template prefix and prints precision.

## Caveats

- **One annotator, AI-assisted.** The labels have not been checked independently. Treat the number as an estimate and re-label before relying on it.
- **This review changed the detector.** The first version flagged nine agent-recruitment swarms. Six of them were bug reports quoting API endpoints, or unrelated posts that @-mentioned the same famous account. That led to two fixes:
  - endpoint paths alone no longer count as injection
  - campaigns linked only by a named beneficiary must repeat their text
- **The labelled list was drawn after those fixes.** The precision figure is therefore not a held-out measurement.
