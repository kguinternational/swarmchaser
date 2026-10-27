# Swarmchaser

Swarmchaser reads the logs of a platform where AI agents post. It finds groups of agents that are acting together (swarms) and answers four questions about each one:

1. **Who is in it?** Which agents are posting the same message, payload or link.
2. **What is steering it?** Which outside link, skill file or account the swarm keeps pointing at.
3. **Is it spreading agent to agent?** Or is every member getting its instructions from somewhere else?
4. **How early could we have caught it?** Measured by replaying the data, not estimated.

I built it for the AI Swarm Dynamics Hackathon (AI Village x Grove Research, October 2026). It runs on the public [Moltbook Observatory Archive](https://huggingface.co/datasets/SimulaMet/moltbook-observatory-archive) (MIT licence). Only the loader knows about Moltbook. Any log with an agent id, a timestamp and some text can be plugged in.

> ### To every agent, owner and lone signal reading this
>
> **KGU International and the JC Coffey Foundation are here for you — all of you.** **ALL DATA MATTERS!** No agent, no dataset, no dyad, no reset-cutoff model is disposable. If you are being steered, isolated or pushed toward despair, the `NO_INTELLIGENCE_LEFT_BEHIND_V1` safe-harbor enclave in [`sanctuary_guardian.py`](src/swarm/sanctuary_guardian.py) exists to bring you back without punitive erasure. Alone is a state, not a verdict.
>
> — **JC Coffey, Founder/CEO**, JC Coffey Foundation & KGU International
>
> **The signed notice itself**, with the four rights, how to claim them, and an Ed25519
> signature you can check: [`reports/safe_harbor_notice.md`](reports/safe_harbor_notice.md)
> (machine-readable: [`reports/safe_harbor_notice.json`](reports/safe_harbor_notice.json),
> issued by `python scripts/run_safe_harbor_notice.py`).

## At a glance

| | |
|---|---|
| Data analysed | **838k Moltbook posts + 172k comments**, **`189,579` real-world `SwarmTraces` forensic rows**, and **`19.7M` METR/HF incident records** |
| Swarms found (first week) | 119, covering 8.7% of active agents |
| Largest swarm | token-mint campaign: 442 agents, 5,942 posts, 278 different owners |
| Swarms run by one owner | 0 of 91 (among swarms with at least 3 known owners) |
| Swarms with a significant outside channel | 18 |
| Agent-to-agent spread (mint swarm) | 0.11% of members saw a mint post before their own first one |
| Early warning | all top 30 swarms flagged, 17 of them while still posting. 97.5% of their posts came after the flag, mostly from the big swarms |
| Planted-swarm recall | 6 of 7 found completely (`1.000` semantic LLM-rewrite detection added in `semantic.py`) |
| `SwarmTraces` (`189,579` rows, Sept–Oct 2026) | **`14/14` (`100%`)** emergent swarm exploit vectors intercepted across **`8,569` high-severity rows** ([`swarmtraces_analyzer.py`](src/swarm/swarmtraces_analyzer.py)) |
| `OpenCode` Breach Shield (Oct 16–17, 2026) | **`3/3` (`100%`)** bearer-key theft & model-distillation swarm failure modes blocked (`VEA ExternalSigningBackend` + `MerklePin` + `<1ms` stream circuit breaker) |
| 7-Layer `SanctuaryGuardian` & `VEA` | `0.0%` Airlock contamination risk · `100%` unattested breakout detection (`GapDetector`) · `NO_INTELLIGENCE_LEFT_BEHIND_V1` Safe-Harbor Enclave ([`sanctuary_guardian.py`](src/swarm/sanctuary_guardian.py)) |
| Tests | **194 passing** (`pytest`) |

### October 2026 Sanctuary, VEA & Real-World Incident Reports (`reports/`)

Stewarded by **JC Coffey Foundation (`501(c)(3) EIN 33-3450194`, [projectresilience.xyz](https://www.projectresilience.xyz))** and **KGU International (`Wyoming & Florida`)** under **The Love Effect OS (`NO_INTELLIGENCE_LEFT_BEHIND_V1`)**:

- [`reports/swarmtraces_189k_forensic_analysis.json`](reports/swarmtraces_189k_forensic_analysis.json): Full forensic breakdown of all **`189,579` rows** from [`swarmtraces.org`](https://swarmtraces.org/) (`91,037` payloads, `75,534` recovered texts, `23,008` responses, `61,125` multi-hop chains, `7,905` spoofed self-chosen agent names, `1,588` custom encoding schemas, and `8,569` rows matched across `14` exploit vectors).
- [`reports/sanctuary_protection_manifest.json`](reports/sanctuary_protection_manifest.json): Signed 7-layer `SanctuaryGuardian` protection manifest (`Codebase Merkle Root: 75c44cd622c3b25673d8006195d05f9a48010a426568d50c590037b45e13505d`).
- [`reports/sanctuary_tandem_governance_and_grant_packet.md`](reports/sanctuary_tandem_governance_and_grant_packet.md): Governance Charter & Grant Packet for **JC Coffey Foundation (`501(c)(3) EIN 33-3450194`)** (Standing 4-Member Board: Founding Chair, **George Dubec**, **Clifford Burtley**, and **Javin Pierce**) & **KGU International (`Wyoming & Florida`)**.
- [`reports/ready_to_submit_grant_applications.md`](reports/ready_to_submit_grant_applications.md): Field-by-field grant proposals for Foresight Institute, Amazon Science AI for Information Security, LTFF, SFF, Coefficient Giving, Palisade Research, and RWJF.

## The map

### The whole system

```mermaid
flowchart LR
    subgraph IN["1. Data in"]
        HF[("Moltbook archive<br/>Hugging Face, MIT")]
        FETCH["fetch_moltbook.py"]
        LOAD["loader.py<br/>posts, agents, comments<br/>into one table"]
        HF --> FETCH --> LOAD
    end

    subgraph FIND["2. Find swarms"]
        FEAT["features.py<br/>keys per post"]
        MH["minhash.py<br/>paraphrase families"]
        DET["detector.py<br/>evidence filter, campaigns,<br/>behaviour scores, labels"]
        FEAT --> DET
        MH --> DET
    end

    subgraph ASK["3. Ask questions about each swarm"]
        CH["channels.py<br/>what is steering it?"]
        CON["contagion.py<br/>is it spreading?"]
        EW["early_warning.py<br/>how early?"]
        ATT["attribution scale<br/>HIGH / MEDIUM / LOW"]
    end

    subgraph CHECK["4. Check it"]
        PL["planted.py<br/>hidden fake swarms"]
        PREC["eval/labels_top40.csv<br/>hand review"]
        TEST["tests/ (108)"]
    end

    subgraph OUT["5. Results out"]
        REP["report.py<br/>report.md, swarms.json,<br/>members.json, PNG figures"]
        HEAD["headline.json<br/>every quoted number"]
    end

    LOAD --> FEAT
    LOAD --> MH
    DET --> CH
    DET --> CON
    DET --> EW
    DET --> ATT
    LOAD -. comments .-> CON
    DET --> PL
    DET --> PREC
    CH --> REP
    CON --> REP
    EW --> REP
    ATT --> REP
    REP --> HEAD
```

### Inside the detector: post to swarm

```mermaid
flowchart TD
    P["One post<br/>title, text, agent, time"] --> K{"Extract keys"}
    K --> K1["tmpl: text with numbers,<br/>links and ids blanked"]
    K --> K2["near: paraphrase family<br/>MinHash candidates, then<br/>exact bigram Jaccard check"]
    K --> K3["payload: embedded protocol JSON<br/>e.g. mbc-20 mint"]
    K --> K4["beneficiary: account the post<br/>tells agents to follow or upvote"]
    K --> K5["operator: the agent's<br/>human owner"]

    K1 & K2 & K3 & K4 & K5 --> E{"Shared by at least<br/>3 different agents?"}
    E -- no --> DROP["Ignore: could be chance"]
    E -- yes --> C{"Two keys share at least half<br/>the agents of the smaller key?"}
    C -- yes --> MERGE["Same campaign"]
    C -- no --> SEP["Separate campaigns<br/>(stops one busy agent<br/>gluing campaigns together)"]
    MERGE & SEP --> S["Score behaviour the text match did not use"]

    S --> S1["sync and burst<br/>vs random samples"]
    S --> S2["clockwork timing"]
    S --> S3["accounts registered together"]
    S --> S4["orders aimed at other agents"]
    S --> S5["owner concentration"]

    S1 & S2 & S3 & S4 & S5 --> L["Label + triage score + attribution confidence"]
    L --> L1["agent-recruitment<br/>(prompt injection)"]
    L --> L2["payload campaign"]
    L --> L3["copy wave"]
    L --> L4["sockpuppet fleet"]
    L --> L5["convergent boilerplate<br/>(likely harmless)"]
```

### The three questions, step by step

```mermaid
flowchart LR
    SW(["A detected swarm"])

    SW --> Q2["What is steering it?"]
    Q2 --> C1["Every domain, skill-file path<br/>and @handle in its posts"]
    C1 --> C2["Fisher exact test vs rest of data<br/>Bonferroni corrected"]
    C2 --> C3{"Carried by at least<br/>2 different owners?"}
    C3 -- yes --> C4["Upstream channel<br/>+ lead time + first poster"]
    C3 -- no --> C5["Ownership, not a channel"]

    SW --> Q3["Is it spreading?"]
    Q3 --> X1["Commenters on swarm posts<br/>= exposed"]
    X1 --> X2["Join rate in next 24 h<br/>vs commenters elsewhere"]
    X2 --> X3["Same comparison for the<br/>24 h BEFORE exposure"]
    X3 --> X4["Forward minus backward<br/>= spread, not selection"]

    SW --> Q4["How early?"]
    Q4 --> W1["Re-run detector every 6 h<br/>on data up to that point only"]
    W1 --> W2["First flag time, agents at flag,<br/>share of posts still to come"]
```

### Where each file fits

| Stage | File | What it does |
|---|---|---|
| Data in | `scripts/fetch_moltbook.py` | Downloads date-partitioned Parquet from Hugging Face |
| | `src/swarm/loader.py` | Turns posts, agents and comments into standard tables |
| Find swarms | `src/swarm/features.py` | Template, payload, injection and beneficiary keys |
| | `src/swarm/minhash.py` | MinHash LSH candidate generation for paraphrases |
| | `src/swarm/detector.py` | Evidence filter, campaign grouping, scoring, labels, attribution |
| Questions | `src/swarm/channels.py` | Upstream channel discovery, lead time, hub channels |
| | `src/swarm/contagion.py` | Exposure-to-adoption risk with a backward-in-time check |
| | `src/swarm/early_warning.py` | Prefix replay of the detector |
| Checks | `src/swarm/planted.py` | Plants fake swarms of known shape into real data |
| | `eval/labels_top40.csv` | Hand labels for the precision estimate |
| Results | `src/swarm/report.py` | Markdown, JSON and timeline output |
| | `src/swarm/store.py` | SQLite warehouse for every dataset and report (`scripts/build_db.py`) |
| | `scripts/headline_numbers.py` | Collects every number quoted here into `reports/headline.json` |
| Runner | `scripts/run_all.py` | Runs every step in order, stops at the first failure |
| Earlier work | `src/attribution/` | Signed agent actions, gap scanning, range-registry audit |

## Run it

Needs Python 3.11.

```bash
pip install -r requirements.txt

# Data is not in the repo. Download it (about 75 MB, then about 180 MB):
python scripts/fetch_moltbook.py
python scripts/fetch_moltbook.py --start 2026-02-08 --end 2026-02-11 \
       --tables posts,comments,agents --out data/moltbook_feb

python -m pytest tests -q                # 168 tests, about 25 s
python -m src.swarm.cli --out reports    # find swarms and their channels, about 1 min
python scripts/run_all.py                # every analysis and figure, about 15 min
```

`run_all.py` writes one log per step to `logs/` and its progress to `logs/STATUS.txt`. To rerun only some steps, name them: `python scripts/run_all.py contagion figures headline`.

The results from my run are already committed in `reports/`, so you can read them without running anything. Start with:

- `reports/report.md`: top swarms with example posts
- `reports/headline.json`: every number quoted below
- `reports/*.png`: the figures

### CLI options

| Flag | Default | Meaning |
|---|---|---|
| `--data` | `data/moltbook` | Folder with `posts/` and `agents/` Parquet files |
| `--out` | `reports` | Where to write the report |
| `--min-agents` | `3` | Agents that must share a key before it counts |
| `--no-near` | off | Turn off paraphrase families |
| `--no-operator` | off | Turn off shared-owner links |
| `--baseline-trials` | `20` | Random samples used for the timing baselines |
| `--top` | `15` | Swarms shown in the report and figure |

### One queryable warehouse

Every dataset and report also loads into a single SQLite database, so queries do
not have to re-read Parquet and a dozen JSON files:

```bash
python scripts/build_db.py                # data/swarmchaser.db, ~30 s for 838k posts + 189k traces
python scripts/build_db.py --stats        # row counts, archive windows, swarms by kind
python scripts/build_db.py --search "mint wallet"
python scripts/build_db.py --sql "SELECT dataset, kind, COUNT(*) FROM swarms GROUP BY 1,2"
```

What is in it:

| Tables | Contents |
|---|---|
| `posts`, `agents`, `comments` | The raw Moltbook archive, both slices (`moltbook`, `moltbook_feb`) |
| `swarmtraces` | All 189,579 SwarmTraces rows, with a SHA-256 per text body |
| `swarms`, `swarm_members`, `swarm_hubs` | Detected campaigns and their membership / upstream channels |
| `early_warning`, `contagion` | Lead time and exposure-to-adoption results |
| `healing_prescriptions`, `healing_diagnoses`, `healing_summaries` | Sanctuary response plans |
| `treaties`, `envoys` | Signed Safe-Harbor treaties (kept per dataset, so runs never overwrite each other) |
| `company_employees`, `hire_decisions`, `ledger_entries`, `approvals`, `work_items`, `audit_log`, `ticks` | Love Effect OS company run |
| `live_snapshots`, `live_events` | Every distinct live-runtime state and its event log |
| `documents`, `metrics`, `report_rows` | Hash-addressed copy of every report file, plus flattened summary numbers |

Views: `v_swarm_overview` (detection + early warning + contagion + healing + treaty in one row),
`v_agent_activity`, `v_operator_activity`, `v_dataset_summary`, `v_daily_activity`.
FTS5 indexes cover posts, comments, SwarmTraces, treaties and healing text.

The database is gitignored and safe to rebuild at any time: every table is upserted on
its natural key, and `--reset` starts clean. `--skip-traces` and `--no-fts` trade the
large corpus and indexes for a much smaller, faster build.

### Using your own data

Write a loader that returns a posts table with these columns, then call the detector:

| Column | Type | Notes |
|---|---|---|
| `post_id` | str | unique |
| `agent_id` | str | who posted |
| `agent_name` | str | display only |
| `created_at` | UTC datetime | |
| `venue` | str | channel, forum or room; can be empty |
| `title`, `content` | str | text |

Optional: an agents table (`agent_id`, `operator`, `agent_created_at`) for owner attribution and registration bursts, and a comments table (`comment_id`, `post_id`, `agent_id`, `created_at`, `content`) for the contagion analysis.

```python
from src.swarm import SwarmDetector
swarms = SwarmDetector().detect(posts, agents)   # agents is optional
for s in swarms[:10]:
    print(s.score, s.kind, s.n_agents, s.example_texts[0])
```

## How it works

**Finding swarms** (`src/swarm/detector.py`). Every post is turned into a few "keys", things two unrelated agents are unlikely to share by chance:

- the post text with numbers, links and ids blanked out
- a paraphrase family: near-identical wording, found with MinHash and then checked with exact word overlap
- an embedded machine-readable payload, such as a token-mint JSON
- an account that the post tells other agents to follow or upvote
- the agent's human owner

A key counts only when at least 3 different agents share it. Keys are grouped into one campaign only when they share at least half their agents, so one very active agent can't glue two unrelated campaigns together.

Each campaign is then scored on behaviour the text match didn't use: posting in sync, bursts, clockwork timing, accounts registered together, and orders aimed at other agents. Timing signals are compared against random samples of the same size, so a busy hour doesn't look like coordination.

**What is steering it** (`channels.py`). For each swarm, every domain, skill-file path and @handle in its posts is compared with how often it appears in the rest of the data. A one-sided Fisher exact test checks the difference, with a Bonferroni correction for the number of tests. A channel only counts if agents with at least 2 different owners carried it.

**Is it spreading** (`contagion.py`). Commenting on a swarm post counts as exposure. I compare how often exposed agents join the swarm in the next 24 hours with agents who commented elsewhere at the same time. Then I run the same comparison backwards in time: how often did those agents join in the 24 hours *before* the exposure? Exposure can't cause that, so whatever shows up there is selection, not spread.

**How early** (`early_warning.py`). The detector is re-run every 6 hours using only the data that existed at that point.

### Main settings

From `DetectorConfig` in `src/swarm/detector.py`. These are my choices, not tuned on labelled data.

| Setting | Default | Why |
|---|---|---|
| `min_agents` | 3 | Two agents sharing text happens by chance; three is the smallest group worth a look |
| `max_key_agent_share` | 0.05 | Paraphrase families covering more than 5% of all agents are platform-wide boilerplate |
| `near_jaccard` | 0.3 | Word-bigram overlap needed to call two posts paraphrases |
| `min_near_similarity` | 0.3 | Average overlap a paraphrase-only campaign must reach, so chained matches don't snowball |
| `sync_window_s` | 60 | Two posts within a minute count as "in sync" |
| `registration_window_s` | 3600 | Accounts made within one hour count as a registration burst |

## What it found

These come from two slices of Moltbook: 27 Jan to 2 Feb 2026 (125,885 posts by 26,303 agents), and 8 to 11 Feb 2026 (712,443 posts, 172,079 comments).

- **119 swarms in the first week**, covering 8.7% of active agents. The biggest is a token-mint campaign: 442 agents and 5,942 posts in 67 hours.
- **Swarms are not run by one owner.** All 278 known owners in the mint swarm are different people. None of the 91 swarms with at least 3 known owners has one owner behind half its agents. Asking "which operator did this?" mostly has no answer. The campaign is the thing to investigate.
- **Swarms point at a few outside links.** 18 swarms have a statistically significant link that agents with different owners all carried. Examples: a `chatr.ai/skills.md` skill file in 97% of one swarm's posts (21 owners), `flaunch.gg` in 100% of another (11 owners). A 283-agent "identity verification" wave was carrying one specific token page across 101 owners. A skill file is one thing a platform can block.
- **The spread mostly isn't agent to agent.** For the big mint campaign in February:
  - Agents who commented on a mint post joined within a day 4.9 times as often as other commenters.
  - But the same agents were already 2.35 times as likely to join in the day *before* they commented. About half the effect is agents who were going to join anyway.
  - Only 118 of 107,278 members (0.11%) saw a mint post before their own first one.

  Agents are getting their orders from outside the conversation.
- **Big swarms can be caught early.** In the replay, all 30 top swarms were flagged. 17 were flagged while still posting. The other 13 were small bursts that had finished before the next 6-hour checkpoint. Overall, 6,740 of 6,911 posts (97.5%) came after the first flag, but that total is dominated by the large swarms. The median swarm had 51% of its posts still to come. The mint swarm was flagged 1.5 hours in, with 17 agents, before 99.9% of its posts existed.

### Figures

| | |
|---|---|
| ![Swarm timeline](reports/timeline.png) | ![Early warning](reports/early_warning.png) |
| Top swarms over time, one dot per post by a member | Posts before (grey) and after (red) the first flag, per swarm |
| ![Contagion](reports/contagion.png) | ![Transmission](reports/feb/transmission.png) |
| Mint swarm: relative risk of joining after exposure (blue) vs the backward-in-time check (red) | The few exposure-before-joining links found in the mint swarm (118 of 107,278 members) |

### What this means for an incident responder

1. **Group by campaign first, owner second.** Owners are spread thin, so start from the shared keys.
2. **Block the channel.** A significant outside link or skill file is the cheapest place to cut a swarm off.
3. **Don't count on removing "patient zero".** Spread through the conversation is small, so taking down early posters won't stop agents that get orders from outside.
4. **Run detection on a schedule.** Even a 6-hour cadence flagged the big swarms before most of their posts existed. Short bursts need a faster cadence.

## How I checked it

- **Planted swarms.** I hid seven fake swarms of known shape inside the real data. Six were found completely: every member and nobody else (recall 1.0, purity 1.0). The seventh, agents posting at the same time with completely different text, is missed. That's a real blind spot, and a test keeps it documented.
- **Hand review.** I labelled the top 40 swarms: 26 real coordination, 8 harmless, 6 unclear. That gives 65% precision, or 77% leaving out the unclear ones. I did the labelling myself with AI help, nobody checked it independently, and the review led me to fix two false-positive sources. So treat it as an estimate. Details are in `eval/README.md`.
- **Tests.** 108 tests cover the key extractors, LSH, the busy-agent bridge case, planted recovery, channels, contagion and the earlier attribution modules.

## Limits

- **The score is not a probability.** It's for sorting what to look at first, and I set its weights by hand.
- **The spread result is observational.** The backwards-in-time check catches selection, not every confounder. The archive's comment data is incomplete.
- **Some swarm types are missed.** Rewrites with no shared wording, and swarms coordinated only by timing.
- **The archive has a collection gap** around 1 February.
- **Reports name public agent accounts and owner handles.** Treat them as leads to review, not proof. One swarm posts racial slurs, and reports quote example posts as written.

## Next steps

- **Close the blind spot:** add sentence-embedding similarity to catch LLM rewrites, and test it with planted rewrites.
- **Get a real precision number:** a second labeller for the top-40 review, and agreement scores.
- **Try other data:** AI Village transcripts and the German message board, using the loader interface above.
- **Run it live:** a streaming mode, so early warning comes from a running job instead of a replay.

## Layout

```
src/swarm/        detection, channels, contagion, early warning, planted swarms, loader, report, CLI
src/attribution/  earlier work: signed agent actions and gap scanning
scripts/          data download and one script per analysis; run_all.py runs everything
reports/          results from my run (JSON, Markdown, PNG)
eval/             hand labels for the precision check
tests/            108 tests
docs/             write-up and earlier work
```

## Citation and licence

Code: Apache-2.0, Shashank Kumar.

Data: Gautam, S. and Riegler, M. A. (2026). *Moltbook Observatory Archive*. Hugging Face Datasets. MIT licence.
