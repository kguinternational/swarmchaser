# LIVE Runtime — real-time Swarmchaser + LOVE EFFECT OS

Status: running. 150 tests pass (8 new live-runtime tests).

## What runs

| Mode | Command | What it does |
| --- | --- | --- |
| replay | `.venv/bin/python scripts/run_live_runtime.py --mode replay --data data/moltbook --chunk-size 2000` | Streams the 125,885-post Moltbook archive in timestamp order, chunk by chunk, as a live feed |
| watch | `.venv/bin/python scripts/run_live_runtime.py --mode watch --sources data/moltbook/posts --poll 5` | Polls event sources on disk and ingests new rows as they appear |
| demo | `.venv/bin/python scripts/run_live_runtime.py --mode demo` | Injects a synthetic live campaign (exact-template + LLM-paraphrased) to show detection and response end to end |
| serve | `.venv/bin/python scripts/serve_live_center.py --port 8787` | Serves the live command center at `http://127.0.0.1:8787`, polling `/api/state` every 3s |

## Measured result on the real archive

```
125,885 posts processed
111 swarms intercepted at the 3rd agent
111 Ed25519 Safe-Harbor treaties signed (cryptographic_proof, external_process custody)
305 posts halted, 335 observed before the halt -> 47.7% preventable share
modalities: 92 semantic-llm-paraphrase, 18 exact-template, 1 json-payload
115 audit entries, every signature verified
```

The live count (111) matches the upstream interceptor run uncapped over the same
corpus (118), which is the check that matters: the live layer is finding the same
campaigns as the batch detector, not a different set.

## The pipeline, live

```
event arrives
  -> rolling window (60 min) re-scan
  -> 3rd distinct agent on a coordination key triggers interception
  -> SafetyAirlock strips injections from the campaign text
  -> SwarmNegotiator mints an Ed25519 Safe-Harbor Treaty
  -> ForensicVerifier proves the signature (CRYPTOGRAPHIC_PROOF)
  -> detection becomes a LoveEffectOS work item ("safe_harbor_response")
  -> an employee is routed to it, healing prescription is attached
  -> signed audit entry is written
  -> command center updates
```

Detection never executes anything directly. A detection only produces a work item,
which then runs under the normal company rules: budgets, approval gates, signed
audit. That is why the live layer inherits the LOVE EFFECT OS guarantees instead of
bypassing them.

## Two bugs found and fixed while building this

1. **Treaty id collision.** The upstream interceptor numbers treaties positionally
   per call (`treaty-stream-swarm-001`), so the same campaign got a different id on
   every window slide, and the live layer minted 1,699 treaties for 111 real
   campaigns. Fixed by deduplicating on the coordination key with a restart window
   matching the detection window, and minting a separate `live-treaty-NNNN` id.
2. **Double counting on re-ingest.** Deduplication was originally keyed on
   `interception_id`, which is positional. Now keyed on the campaign identity.

Both were caught by comparing the live count against the uncapped upstream count
rather than by assuming the numbers were right.

## Live command center

`scripts/serve_live_center.py` serves a page that polls `/api/state` every 3
seconds, so a separate runtime process feeds it and the browser stays current. It
shows events processed, swarms intercepted, treaties signed, posts halted,
preventable share, detection modality breakdown, active treaties, company status
(headcount, work done, safe pauses, ledger, spend, pending approvals), and the
recent event feed.

## Limits

- The window is 60 minutes and the memory held is one window of events, so the
  runtime is bounded. A campaign that pauses for longer than the window is treated
  as a new campaign, which is the intended reading.
- Data sources are parquet or jsonl on disk. There is no network collector, so
  "live" means live against the filesystem, not live against Moltbook.
- The demo mode injects synthetic campaigns. It is labelled as such in the output.
