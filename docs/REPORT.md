# Swarmchaser: who acts together, what steers them, does it spread, and how early can we tell

**Author.** Shashank Kumar (independent). **Event.** AI Swarm Dynamics Hackathon, AI Village x Grove Research, 3-4 Oct 2026.
**Code.** https://github.com/sidthebuilder/swarmchaser (`src/swarm/`). **Data.** Moltbook Observatory Archive (MIT), 838k posts and 172k comments across two windows.

## Problem

In the Hugging Face intrusion and the German wiki incident, investigators had thousands of agent actions and no way to ask four basic questions:

1. Which of these belong together?
2. What is driving them?
3. Is the behaviour spreading from agent to agent?
4. How early could it have been stopped?

Signature-based attribution doesn't help: my earlier work in this repo showed that an escaping agent simply doesn't sign. Swarmchaser answers all four from a platform's own logs.

## Method

- **Detection.** Agents are linked through coordination keys:
  - text templates
  - verified paraphrase families (MinHash LSH plus exact Jaccard)
  - embedded protocol payloads
  - accounts that agent-directed text tells readers to follow
  - shared owners

  Keys merge into campaigns only when they share at least half their members, so one prolific agent can't fuse unrelated campaigns. Each swarm is then scored on signals the text match didn't use: synchrony and burst concentration against random-sample baselines, cadence, registration bursts and owner concentration.
- **Channels.** For each swarm, every domain, skill-file path and @handle is tested for enrichment against the rest of the corpus (one-sided Fisher, Bonferroni-corrected), with the number of distinct owners that carried it.
- **Contagion.** Commenting on a carrier post counts as exposure. Adoption within 24 h among exposed agents is compared with time-matched commenters. A reverse-time placebo measures adoption in the 24 h *before* exposure, which exposure cannot cause. That separates transmission from selection, where agents drawn to a campaign's posts were going to join anyway.
- **Early warning.** The detector is re-run on every 6-hour prefix of the data, so detection times are measured, not simulated.

## Findings

1. **Swarms are campaigns, not operators.** 119 swarms cover 8.7% of agents in the launch week. The largest, an `mbc-20` token mint, has 442 agents, and its 278 known owners are all different. None of the 91 swarms with at least 3 known owners has one owner behind half its agents. Attributing a swarm to an operator, the first question in both 2026 incidents, mostly fails by construction.
2. **Swarms have findable command channels.**
   - `chatr.ai/skills.md` appears in 97% of one swarm's posts, across 21 owners.
   - `moltpay.xyz` appears in 100% of another.
   - `flaunch.gg` appears in 100% of a 12-agent token-launch swarm, across 11 owners.
   - A 283-agent "identity verification" wave carries a single `bags.fm` token page, across 101 owners.

   A skill file is a single point a platform can block.
3. **Spread is pushed from outside, not caught.** In 712k posts and 172k comments (8-11 Feb), for the 107,278-agent CLAW mint campaign:
   - Commenting on a carrier post looks like it raises the 24 h adoption risk 4.9x (95% CI 3.8 to 6.4).
   - The reverse-time placebo shows the same agents were already 2.35x (CI 1.5 to 3.7) as likely to adopt in the day *before* exposure. About half the apparent effect is selection. Any residual transmission is roughly 2x and only marginally separated from the placebo.
   - Volume settles it: 118 adopters (0.11%) were exposed before they first posted, R_eff is 0.001, and no chain goes past one generation. The other six measured campaigns have no exposed adopters at all.

   Agents are receiving the instructions directly. Read together with finding 2, the response that matters is removing channels, not carrier posts. Without the placebo, the raw 4.9x would have been reported as contagion.
4. **Swarms are catchable early.** Replayed at 6-hour checkpoints, all 30 top swarms were flagged, and 97.5% of their posts came after the first flag. The mint swarm was flagged 1.5 h in, with 17 agents, before 99.9% of its 5,942 posts.

## Validation

- **Planted recall.** Six of seven planted swarm types recovered with recall 1.0 and purity 1.0 inside the real corpus. The seventh, a synchronised swarm with fully distinct text, is missed. It's documented and pinned by a test.
- **Precision.** 65% over the top 40 swarms, or 77% excluding unclear cases. The labels come from one AI-assisted annotator, and the review that produced them also fixed two false-positive sources, so the figure is not held out.
- **Tests.** 108 passing. They include synthetic worlds where the contagion test must find real transmission and must flag pure selection through the placebo.

## Related work and what is new here

- **Moltbook measurement studies** describe the platform at scale: community structure, sentiment, instruction sharing and norm enforcement ([arXiv:2602.02625](https://arxiv.org/abs/2602.02625), [arXiv:2604.13052](https://arxiv.org/html/2604.13052v1)). [The Moltbook Illusion](https://arxiv.org/abs/2602.07432) separates autonomous from human-prompted agents by the regularity of posting intervals. My "scripted cadence" signal uses the same idea, so I make no claim of novelty for it.
- **Agent-to-agent propagation** has been shown under controlled conditions: [Prompt Infection](https://arxiv.org/abs/2410.07283), [ClawWorm](https://arxiv.org/abs/2603.15727), [Mind Viruses](https://arxiv.org/abs/2608.10218) and [Memetic Trojans](https://arxiv.org/abs/2610.00430). Memetic Trojans extracts real contagions from Moltbook but measures their spread in controlled transmission experiments, not in the platform's own logs.
- **What this project adds.** These pieces have not been put together before as one tool that runs on a platform's own logs:
  - detection of swarms
  - a statistical channel test across operators
  - a per-swarm contagion test with a confound guard (time-matched commenter controls plus a reverse-time placebo)
  - a measured, replayed early-warning time

  The contagion result complements the lab studies above with an observational, platform-wide measurement. Mind Viruses also concludes that the risk is real but currently limited.

## Limitations and dual use

- **Scoring.** The swarm score is a hand-weighted triage order.
- **Contagion.** The estimate is observational and uses partial comment coverage. The placebo detects selection but not every confounder. RR is reported only when at least 5 exposed agents adopted.
- **Text detection.** Paraphrases with no shared words and timing-only coordination are missed.
- **Data.** The archive shows a collection gap around 1 Feb.
- **Personal data.** Outputs name public accounts and owner handles. They are leads for review, not findings of fact.
- **Offensive content.** One swarm posts racial slurs, and reports quote it verbatim.
- **Evasion.** The documented blind spot also tells a swarm operator what to avoid. I report it because defenders need to know where coverage ends. The obvious next step, embedding similarity plus behavioural features, is equally public.

## Reproduce

See `README.md` › Quick start. `python scripts/run_all.py` regenerates everything, and `reports/headline.json` holds every number above.
