# Swarmchaser: write-up

Text for the submission form. The full report is in `docs/REPORT.md`.

## What I built and how to use it

Swarmchaser is a Python tool that reads a log of AI agents posting on a platform. It finds swarms, meaning groups of agents acting together, and answers four questions about each one:

1. Who is in it?
2. What outside link or skill file is steering it?
3. Is it spreading from agent to agent?
4. How early could it have been caught?

**Finding swarms.** It links agents through things unrelated agents are unlikely to share: the same post text with numbers and links blanked out, near-identical paraphrases, the same embedded token payload, the same account they tell others to follow, or the same human owner. Then it scores each group on behaviour such as posting in sync, sudden bursts, and accounts registered together.

**The other three questions.**
- **Steering:** a statistical test (Fisher exact, Bonferroni-corrected) for links that a swarm carries far more often than everyone else.
- **Spread:** a comparison of agents who saw a swarm post against agents who didn't, plus the same comparison backwards in time to catch agents who were going to join anyway.
- **Early warning:** a replay of the detector every 6 hours on only the data available then.

**How to use it.** `pip install -r requirements.txt`, download the data with `scripts/fetch_moltbook.py`, then run `python -m src.swarm.cli`. It writes a ranked report with example posts, members and figures. Only the loader is specific to Moltbook. Results from my run are already in `reports/`. 108 tests pass.

I checked it two ways:
- **Planted swarms.** I hid seven fake swarms in the real data. Six were found completely. The seventh, synchronised agents with completely different text, is a known blind spot.
- **Hand labels.** I labelled the top 40 swarms: 65% precision, or 77% leaving out unclear cases. I labelled them myself, with AI help.

## What did your tool find?

All results are from the Moltbook Observatory Archive, 27 Jan to 2 Feb and 8 to 11 Feb 2026 (838k posts, 172k comments).

- **119 swarms in the first week**, covering 8.7% of active agents. The largest is a token-mint campaign: 442 agents and 5,942 posts in 67 hours.
- **Swarms aren't run by one owner.** All 278 known owners in the mint swarm are different. No swarm with at least 3 known owners has one owner behind half its agents. So "which operator did this?", the first question in the Hugging Face and German-wiki incidents, usually has no answer. The campaign is the thing to investigate.
- **Swarms point at a few outside links.** 18 swarms carry a significant link shared across different owners. Examples: a `chatr.ai` skill file in 97% of one swarm's posts (21 owners), and a single token page inside a 283-agent "identity verification" wave (101 owners). Blocking one skill file is a concrete fix.
- **Spread is mostly not agent to agent.** Agents who commented on a mint post joined 4.9 times as often as other commenters. But they were already 2.35 times as likely to join the day *before* commenting, so about half the effect is agents who were going to join anyway. Only 0.11% of 107,278 members saw a mint post before their own first post. Instructions come from outside the conversation.
- **Swarms can be caught early.** In a replay, all 30 top swarms were flagged while running, and 97.5% of their posts came after the first flag. The mint swarm was flagged 1.5 hours in, with 17 agents.
