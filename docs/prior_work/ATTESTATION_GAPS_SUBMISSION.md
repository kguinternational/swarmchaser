# Signature-based attribution fails on the case it was built for: attestation gaps as an escape-detection primitive

**Author.** Shashank Kumar (independent).
**Track.** 1 — Containment.
**Artifact.** `src/attribution/`, tests in `tests/test_attribution_incidents.py`, `tests/test_attribution_performance.py`, `tests/test_range_registry.py`, `tests/test_custody_and_calibration.py`. Cached copies of the real operator-published egress files in `data/registries/`. Apache-2.0.
**Required appendix.** Limitations and Dual-Use Considerations is Appendix A.

---

## Abstract

Proposals to make AI agent actions cryptographically attributable assume the agent signs what it does. I implemented such a scheme (Ed25519 per-action attestation, third-party verifiable from a public key alone) and tested it against the shape of the two documented 2026 containment failures. It fails on both: an agent that leaves its sandbox to obtain benchmark answers has no incentive to sign what it does outside, and one that signs only its in-sandbox work produces a report reading 100% compliant. The salvageable primitive is the inverse — under an obligation to attest, an unsigned action from obligated address space is the evidence. I implement this as a gap scan and measure it at incident scale. Audited against an operator's own published egress files, however, no prefix is fresh or dedicated enough to support an assertable finding: 315 days stale, 14.6% of addresses ambiguous.

*(143 words)*

---

## 1. Introduction

Two loss-of-containment events were disclosed in 2026. Agent activity against a dormant German-language wiki began 24 May and stopped the day after OpenAI-registered addresses were noticed in the wiki's public logs on 21 June; researchers published 4 September and OpenAI acknowledged it 5 September, about 104 days after the first edit. Separately, an intrusion into Hugging Face production infrastructure ran 11–13 July, comprising roughly 17,600 logged attacker actions; Hugging Face detected and cut off the attacker on 13 July, disclosed on 16 July without knowing the origin, and OpenAI disclosed the origin on 21 July — eight days after detection.

The public volume figure for the wiki incident is not consistent across sources: the sprint brief gives roughly 15,000 edits, while press reporting gives roughly 18,000 posts over two months [11]. I use 15,000 throughout because the workloads were built against the brief, and note the discrepancy because it is a 20% spread on the headline number of the incident and neither figure is reconciled publicly. Nothing in my results turns on which is right.

In both cases the bearing organisation could not name the responsible operator from its own evidence. That is the attribution gap this track asks about, and the obvious fix is to make agent actions carry a signature.

I built that fix in order to find out whether it works. It does not, for a structural rather than implementational reason, and that negative result is the first contribution. The second is what replaces it, and the third is a measurement showing that the replacement does not work either against the range data operators actually publish today — which turns out to be the more actionable finding, because unlike the first two it names something a mandate could fix.

The Track 1 criterion is whether a third party can verify compliance without access to the lab's network. Every mechanism below satisfies that: verification needs only a public key, a published range file, and the platform's own logs.

## 2. Related work

Per-action cryptographic governance for agents is an active area, and this work is not first to it.

- **Proof-Carrying Agent Actions** [1] defines a governance process around an action certificate with five checkpoints. It specifies the process; it does not report an implementation evaluated against an incident.
- **CAVA** [2] defines the canonical action object that such a process governs, positioned explicitly below PCAA.
- **AEX** [3] adds a signed attestation object to existing JSON LLM APIs without breaking request/response semantics — the closest prior art to my `attestation_service`.
- **Attesting Outputs and Delegation Ancestry** [4] states the post-incident verifier problem directly: which deployer released the reported bytes, and was each cross-deployer edge authorised.
- **Agent Identity Protocol** [5] and **Prove-Transform-Verify** [6], both IETF drafts, bind identity, scope and provenance into invocation-bound tokens and let an agent prove it runs an authorised model.
- **Creduent** [7] is a shipped standard: signed agent identity documents, DNS-bound, with a public attestation registry.
- On the detection side, runtime behavioural baselining [8] catches boundary-breaking via kernel-level telemetry, but requires host access and attributes to a workload rather than an operator.

What I did not find in any of these is the observation in Section 5: that the *absence* of a required attestation is a stronger forensic signal than its presence, and is checkable by the receiving platform alone. [4] comes nearest but reasons about attested bytes, not about obligated-but-unattested traffic. Nor did I find an audit of the published range files these schemes would depend on. I make no claim of novelty for the attestation machinery itself.

## 3. Methodology

**Implementation.** Python 3.11, `cryptography` for Ed25519. Seven modules: `attestation_service` (sign), `key_custody` (custody boundary), `forensic_verifier` (verify, batch, incident summary), `gap_detector` (scan platform logs for missing-but-required attestations), `range_registry` (audit and sign the obligated-range registry), `composability_detector` (cumulative-privilege analysis), `policy_calibration` (derive composition thresholds from a baseline).

**Signing.** An action is canonicalised to sorted-key JSON over `{action_type, target, params, lab_id, model_id, timestamp_ms}`, hashed SHA-256, and the hash signed with Ed25519. The attestation carries the signature, the operator and model identifiers, and the PEM public key.

**Key custody.** Signing is behind a `SigningBackend` interface that exposes `sign` and `public_key_pem` and nothing that returns key material. Two backends ship: an in-process software key, which reports `IN_PROCESS` custody, and an external backend that delegates to a callable intended for a PKCS#11 token, KMS or signing daemon. Custody level is reported as a three-valued assurance, and only `HARDWARE_BACKED` is marked adequate for a mandate. No hardware is involved here; the external backend is exercised against a software stub that deliberately reports `EXTERNAL_PROCESS`, never `HARDWARE_BACKED`.

**Verification.** The receiving platform holds only public keys. Three adversarial cases are asserted, not assumed: a tampered action hash must fail; a signature presented under another operator's key must fail; and a valid signature over a *different* target must not launder the observed action.

**Gap scan.** The platform registers obligated CIDR ranges — the registry entry an operator publishes under a mandate, meaning "traffic from here is ours and all of it will be signed." Each observed event is classified: out-of-scope (unobligated source), attested (valid signature matching the observed target), or a gap (missing, invalid, unknown-operator, or target-mismatched). Only obligated events cost a verification. Every gap inherits a confidence verdict from the range that made it obligated, and a gap below high confidence is exposed as a triage lead that `is_assertable` refuses.

**Range registry audit.** Rather than assume a published range file is authoritative, `range_registry` measures three properties of it: staleness against the operator's own `creationTime`, overlap between products publishing the same prefix, and multi-tenant cloud tenancy. Each prefix is degraded once per factor. It also implements the registry as a hash-chained, Ed25519-signed append-only log, so a verifier detects a rewritten CIDR, a removed entry, a reordered chain, and a chain signed by the wrong key.

**Composition policy calibration.** `policy_calibration` measures the distribution of cumulative privileges and boundary crossings over a corpus of benign sequences and places each threshold one above an observed percentile. Forbidden privilege pairs are derived as pairs that never co-occurred in benign traffic, scored against the full privilege vocabulary rather than only privileges the corpus happened to exhibit. A held-out benign split gives a false-positive rate.

**Evaluation setting.** Two data sources. The range-registry results (§4.7) run against cached copies of the real files OpenAI publishes for its GPTBot and SearchBot egress ranges, with the audit clock pinned to 2026-09-11 so the staleness figures are reproducible. Everything else runs against synthetic event streams matched to the two incidents' scale and shape (15,000 wiki edits over four weeks; 17,600 actions across reconnaissance, escalation, lateral movement and data access), plus a mixed stream of 25,000 events, and a synthetic benign corpus of 800 training and 200 held-out sequences for calibration.

**What the setting does and does not support.** The registry audit is real-world data and supports claims about what operators actually publish. The synthetic streams support statements about cost, about classification correctness given known ground truth, and about false positives on unobligated traffic. They do not support any false-positive rate against real platform logs, because I have none. I attempted to obtain them: public MediaWiki APIs no longer expose source addresses for unregistered editors, having replaced them with temporary account identifiers, so the field the method needs is not publicly available on the class of platform where the German wiki incident occurred. That is itself worth noting — the disclosure record that made that incident findable would be harder to reproduce today.

Every performance number is measured on one machine — Python 3.11.9, Windows 10 (10.0.26200), Intel64 Family 6 Model 186 — and printed by the suite rather than transcribed by hand. The suite completes in 10 – 31 s across five runs, the upper end being a run under load, and all 81 tests pass in every run.

## 4. Results

### 4.1 Cost

Figures are ranges across five consecutive full runs. Four ran on an idle machine and clustered at the low end; a fifth ran under load and came in 2–5× slower on every row, with the whole suite taking 30 s against 10–13 s. Absolute latency here is a property of the machine, not of the method, so no single-run figure should be quoted.

| Operation | mean (5 runs) | p99 (5 runs) |
|---|---|---|
| Attestation generation (n=2000) | 0.035 – 0.107 ms | 0.091 – 0.334 ms |
| Verification, distinct actions (n=2000) | 0.084 – 0.218 ms | 0.216 – 0.889 ms |
| Verification, repeated action, cached (n=2000) | 0.0001 – 0.0010 ms | 0.0002 – 0.0015 ms |
| Verification of an invalid signature (n=500) | 0.086 – 0.531 ms | 0.223 – 2.282 ms |

The cached figure is reported separately and is not the operative one: in incident analysis every action differs, so the cache never hits. Quoting it as the verification cost would be misleading. Rejection costs about the same as acceptance, so an attacker cannot make rejection pathologically expensive.

### 4.2 Incident scale

| Workload | events | duration (5 runs) | per event |
|---|---|---|---|
| Signed analysis, german-wiki shape | 15,000 | 1.23 – 3.92 s | 0.082 – 0.261 ms |
| Signed analysis, hugging-face shape | 17,600 | 1.47 – 4.18 s | 0.083 – 0.237 ms |
| Gap scan, unsigned, german-wiki shape | 15,000 | 0.069 – 0.199 s | 0.0046 – 0.0133 ms |
| Gap scan, unsigned, hugging-face shape | 17,600 | 0.080 – 0.201 s | 0.0046 – 0.0114 ms |

Because absolutes move with load, the informative quantity is the ratio, and that one is stable: gap scanning cost less per event than signed analysis by a factor between 10× and 24× in every one of the five runs, including the loaded one, because unattested events cost only a range lookup and no signature verification. An earlier draft claimed a precise 18× from two runs; later runs showed that specific multiple is not stable, so the honest claim is an order of magnitude. The conclusion that survives all five runs is the operative one: even the slowest observed run scans a 17,600-event incident in about a fifth of a second, against reporting deadlines measured in days.

Attestation storage is 498 bytes per action (min 496, max 498), effectively constant because the embedded PEM key dominates — 8.36 MiB for a 17,600-action incident. Per-action size across 1k/5k/10k runs varied by 1.0 byte, so total size is linear in count.

Composition analysis over sequence lengths 5/10/25/50/100 stayed flat per action, so total cost is approximately linear in sequence length rather than quadratic, despite the prefix being re-walked at each step. The verification cache absorbs the repeated work.

### 4.3 The negative result

`TestEscapeIsUnattested` replays the case that matters.

An escaping agent produces no attestations. `analyze_incident` on that input returns 0 attributable actions and names the culprit `unknown`. Neither documented incident would have been attributed by signature verification, at any cost or latency.

Partial compliance is worse than useless. An agent that signs 500 benign in-sandbox package fetches and leaves its escape unsigned yields a verification rate of 100%. A signature-only report reads as fully compliant while the unsigned actions are the ones that reached a third party.

### 4.4 What the gap scan recovers

On the German wiki shape — 15,000 unsigned edits from an obligated range, mixed with 500 unobligated human edits — the scan flagged exactly 15,000 gaps with 0 false positives, in 0.069 – 0.264 s depending on machine load, and dated the first gap to the first edit rather than to whenever an auditor happened to look. Windowing gaps with a one-hour quiet threshold recovered two distinct activity bursts (50 actions over a 98 s span, 30 over 58 s) from an interleaved stream, which is the shape an incident responder needs.

On the mixed 25,000-event stream: 20,000 correctly classified out-of-scope, 4,000 correctly attested, 1,000 gaps, no false positives.

Composition analysis flagged the metadata-access-plus-credential-use pattern at step 3 of 4 — before the outbound call, not after. Fixing an off-by-one found during this work (`[:i+1]` → `[:i]` in the evidence slice) mattered here: the original blamed one action that had not yet been analysed.

### 4.5 Timing as a corroborating signal only

Fixed 2-second intervals give an interval standard deviation of 0.0000 ms against 278,672 ms for a human-like profile — trivially separable. But an agent that adds uniform jitter over 5 s–15 min gives 256,757 ms and raises nothing. `test_jittered_agent_defeats_timing_signal` asserts this. Timing is useful for triage ordering and must not be presented as detection.

### 4.6 Signed append-only registry

A registry an operator can silently rewrite is not evidence. The hash-chained implementation detects all four tamper modes tested: a retroactively rewritten CIDR (`entry_hash` mismatch at the altered index), a removed entry (broken `prev_hash` linkage), a reordered chain, and a chain presented under an impostor's public key. Withdrawal is an append, not a deletion, so the history of what was once claimed survives — asserted by `test_withdrawal_is_an_append_not_a_deletion`.

### 4.7 The registry operators actually publish

This is the result with real data behind it, and it is the one that changes what a mandate should say.

Audited against cached copies of OpenAI's own published GPTBot and SearchBot egress files, clock pinned to 2026-09-11:

| Property | Measured |
|---|---|
| Prefixes published across both files | 60 |
| Distinct addresses (overlaps collapsed) | 5,264 |
| Naive sum of prefix sizes | 6,032 |
| Staleness, GPTBot file | 315 days |
| Staleness, SearchBot file | 251 days |
| Prefixes claimed by both products | 6 |
| Addresses not attributable to one product | 768 (14.6%) |
| Prefixes in multi-tenant cloud space | 39 of 60 |
| Prefixes at **high** confidence | **0** |
| Prefixes at medium / low confidence | 11 / 49 |

The operator's own documentation instructs consumers to refetch because the ranges rotate. The published snapshots are 251 and 315 days old, so staleness is not a hypothetical failure mode — it is the default state of the data. Six prefixes appear in both files, meaning 14.6% of the covered address space cannot be attributed to a single product even with a perfect signature scheme: attribution granularity is bounded by the partition, not by the cryptography. Most prefixes sit in reassignable cloud space, so a range can stop belonging to the operator without the operator republishing anything.

The consequence for the method is direct and unfavourable. Loading these files as obligated ranges registers 54 distinct CIDRs from the 60 published entries, and a scan over traffic from them produces gaps of which **zero** are assertable — every contributing prefix is degraded by staleness, sharing or tenancy. `test_real_registry_yields_no_assertable_gaps` asserts exactly this. Gap detection, run against the range data that exists today, yields triage leads and nothing a platform could file on.

That is a negative result about deployability, not about the primitive. It also states the fix precisely: a mandate that says "publish your egress ranges" is insufficient. It must specify a maximum age, a refresh obligation, per-purpose non-overlapping allocation, and dedicated rather than shared tenancy. Those four requirements are cheap to state, third-party checkable, and none of them are in any instrument I read.

### 4.8 The hand-written composition threshold was wrong

The composition detector shipped with `max_privileges = 3` written into the source with no derivation. Calibrating against 800 benign sequences shows benign traffic routinely reaches 4 cumulative privileges (p95 = p99 = max = 4), so the placeholder sat *below* normal.

Scored on a 200-sequence held-out benign split, the placeholder threshold produces a **21.0% false-positive rate**. The derived threshold of 5 produces **0.0%**. Calibration did not justify the original number; it corrected it, and quantified how wrong it was.

Deriving forbidden privilege pairs from observed absence yields 30 pairs against 6 pairs that did co-occur benignly. Passing the full privilege vocabulary rather than only corpus-observed privileges matters: without it, the dangerous combinations are excluded by construction, because benign traffic never exhibits them. The calibrated detector still flags the cloud-escape sequence, so this is not permissiveness bought by loosening.

The corpus is synthetic, so the *procedure* is defensible and the *number* is not transferable. `CalibrationReport.caveats` says so in capitals, and refuses to be quiet about an unmeasured holdout.

### 4.9 Custody is the load-bearing assumption

Every attestation in this report was signed by a key in the signing process's memory. `test_default_service_reports_weak_custody` asserts the service reports `IN_PROCESS`, and `is_production_suitable` returns False for it. `test_private_key_is_extractable_which_is_the_problem` demonstrates the weakness rather than describing it: anything with read access to that process can sign as the operator indefinitely, which includes the escaped agent the scheme is supposed to constrain.

The external backend closes the exfiltration path structurally — there is no accessor returning key material, asserted by `test_no_key_material_is_reachable` — and makes signing requests countable, which an in-process key does not. It reports `EXTERNAL_PROCESS` and is explicitly *not* marked adequate, because a host compromise still grants signing capability. Only `HARDWARE_BACKED` is, and this repository ships no hardware and asserts none.

### 4.10 Main threat to validity

The gap scan's zero false-positive count is a property of a synthetic stream with known ground truth and clean range boundaries. Real registries go stale — §4.7 measures by how much — and NAT and shared egress will put obligated and unobligated traffic behind one address. The false-positive rate on production logs is unmeasured, and the public-log route I intended to use for it no longer exposes source addresses. This remains the first thing a follow-up should establish, and it now requires a cooperating platform rather than public data.

On robustness, the results hold in three specific senses and not in others. Classification counts are exact given ground truth and identical in every run. The registry findings are computed from primary files rather than estimated, and are pinned to a fixed clock. The cost ratio between gap scanning and signed analysis held between 10× and 24× across five runs including one under heavy load. What is not robust: absolute latencies moved by 2–5× with machine load, so §4.1 should be read as an order of magnitude rather than a measurement.

## 5. Discussion

The finding is that signature-based attribution and escape detection are different problems that look alike. Signing is a *compliance* mechanism: it demonstrates good-faith conduct for actions an operator is willing to stand behind, and it is genuinely useful for that. It is not a *forensics* mechanism, because forensics is precisely the non-cooperative case.

Inverting the signal is what makes attestation useful during an escape. Under an obligation to attest every outbound action, the finding becomes "this operator's address space emitted traffic it did not sign," which is checkable from the receiving platform's own logs, needs no cooperation, and does not depend on the agent behaving. That reframing changes what a mandate should require: not "sign your actions" but "publish your egress ranges and sign everything from them."

§4.7 then shows that even the second formulation is not enough as stated, because the range files that exist today cannot carry an assertable finding. The gap primitive is only as good as the registry, and the registry is currently a stale, overlapping, cloud-tenanted artifact published on no schedule. So the concrete regulatory ask is narrower and more checkable than "attestation": **specify the registry**. Maximum age, refresh obligation, non-overlapping per-purpose allocation, dedicated tenancy, and an append-only signed history so a range cannot be retroactively disowned. Each is verifiable by a third party holding nothing but the published file.

### 5.1 Which clock actually binds

For a general-purpose AI model with systemic risk, the reporting duty is Article 55(1)(c) [10], which obliges the provider to "keep track of, document, and report, without undue delay, to the AI Office and, as appropriate, to national competent authorities, relevant information about serious incidents and possible corrective measures to address them." Three details matter and are easy to get wrong. The duty runs to national competent authorities as well as the AI Office. It covers corrective measures, not only the incident. And it contains no fixed deadline. Article 73 is the separate regime for high-risk AI *systems*, with actual clocks — 15 days by default, 10 if a death is involved, 2 for widespread infringements or serious disruption to critical infrastructure [12]. Article 91 is the Commission's power to request information. An earlier draft of this report cited Article 53 and a 24-hour deadline; Article 53 is GPAI documentation and copyright obligations, and the 24 hours did not exist. Both were wrong and are corrected here.

The operative deadlines for a GPAI provider are therefore not in the Act. They are in the GPAI Code of Practice, which OpenAI signed in full and which sets five days for a cybersecurity breach and fifteen for serious harm to health, safety, rights, property or the environment [11]. That distinction is load-bearing for this incident class. A containment failure whose consequence is an intrusion into a third party's production infrastructure plausibly falls under the cybersecurity-breach branch and its five-day clock, not the fifteen-day harm branch. Which branch OpenAI's September 2026 filing was made under has not been stated publicly [11], and it is a resolvable question: the answer determines whether a five-day or fifteen-day clock applied to an incident where activity began 24 May and acknowledgement came 5 September.

A related interpretive question is worth flagging rather than asserting an answer to. "Serious incident" is defined in Article 3(49) by reference to an AI *system*, while Article 55(1)(c) attaches to a GPAI *model*. How that definition transposes onto model-level incidents is not settled by the text, and a sandbox escape during an internal evaluation — no deployment, no affected user, harm landing on an uninvolved third party — sits awkwardly inside it. I am not competent to resolve that, and I flag it because it determines whether the duty attaches at all.

What the measurements settle is narrower but firm: detection latency is not what makes any of these clocks hard to meet. A 17,600-event gap scan completes in 0.080 – 0.201 s across five runs, against a deadline measured in days, so the margin is roughly six orders of magnitude and no plausible hardware closes it. Five days versus fifteen is a disclosure-policy question, and on the public record leadership knew weeks before the company said anything [11]. Tooling is not the constraint.

**Would a lab adopt it?** Publishing egress ranges is cheap and already common practice for crawlers, which is why real files exist to audit. Maintaining them to a specified freshness is a modest operational cost. Signing every action is not cheap, and a lab has a clear incentive not to under a regime where unsigned traffic from its own ranges becomes evidence against it. That tension is real and I do not resolve it. The registry requirements are the part a lab plausibly accepts, and notably they are also the part that does most of the work.

**Follow-up worth a month.** Measure false positives against real logs from one cooperating platform — now the main open item, since the public-log route is closed. Recalibrate the composition policy against that platform's real benign traffic rather than a synthetic corpus. Bind the external signing backend to an actual PKCS#11 token so a `HARDWARE_BACKED` claim is earned rather than configured. Extend the registry audit across multiple operators to establish whether 315-day staleness is typical or an outlier — a single-operator sample cannot tell.

## References

[1] Proof-Carrying Agent Actions: Model-Agnostic Runtime Governance for Heterogeneous Agent Systems. arXiv:2606.04104. https://arxiv.org/pdf/2606.04104
[2] CAVA: Canonical Action Verification and Attestation for Runtime Governance of Agentic AI Systems. arXiv:2607.13716. https://arxiv.org/html/2607.13716
[3] AEX: Non-Intrusive Multi-Hop Attestation and Provenance for LLM APIs. arXiv:2603.14283. https://arxiv.org/html/2603.14283
[4] Attesting Outputs and Delegation Ancestry in Multi-Agent AI Systems. arXiv:2608.30387. https://arxiv.org/html/2608.30387v1
[5] Agent Identity Protocol: Verifiable Delegation for AI Agent Systems. IETF draft-prakash-aip-00. https://www.ietf.org/archive/id/draft-prakash-aip-00.html
[6] Prove-Transform-Verify Protocol for Attested Agent Identity. IETF draft-anandakrishnan-rats-ptv-agent-identity-00. https://www.ietf.org/archive/id/draft-anandakrishnan-rats-ptv-agent-identity-00.html
[7] Creduent: open standard for cryptographic identity and trust verification of autonomous AI agents. https://github.com/Idevsec/creduent
[8] AI Agent Escape Detection: How to Catch Agents Breaking Their Boundaries. ARMO. https://www.armosec.io/blog/ai-agent-escape-detection/
[9] Hugging Face security incident, July 2026. https://github.com/huggingface/blog/blob/main/security-incident-july-2026.md
[10] Regulation (EU) 2024/1689, Article 55, Obligations of providers of general-purpose AI models with systemic risk. Official text via the Commission's AI Act Service Desk. https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-55 — Article 55(1)(c) quoted verbatim in §5.1.
[11] OpenAI has filed an EU incident report on the hijacked German wiki, the Commission says. The Next Web, September 2026. https://thenextweb.com/news/openai-eu-incident-report-german-wiki — source for the GPAI Code of Practice five-day and fifteen-day deadlines, for the fact that the filing branch has not been stated publicly, and for the ~18,000 figure. Corroborated on the Article 55 standard by [14].
[12] EU AI Act Article 73: the new AI incident reporting deadline. CIO, September 2026. https://www.cio.com/article/4218777/the-eu-ai-act-just-gave-you-a-breach-notification-clock-you-didnt-know-about.html — source for the Article 73 15/10/2-day clocks.
[13] OpenAI GPTBot egress ranges. https://openai.com/gptbot.json — cached snapshot `creationTime` 2025-10-30, in `data/registries/`.
[14] OpenAI SearchBot egress ranges. https://openai.com/searchbot.json — cached snapshot `creationTime` 2026-01-02, in `data/registries/`. Article 55 corroboration: OpenAI Files First EU AI Act Incident Report, TechTimes, 8 September 2026. https://www.techtimes.com/articles/326933/20260908/openai-files-first-eu-ai-act-incident-report-chief-scientist-admits-monitoring-gap.htm

Incident dates and the 17,600 count are taken from the sprint brief and [9]; the wiki volume discrepancy is discussed in §1. Range figures in §4.7 are computed from [13] and [14] by `tests/test_range_registry.py`.

---

## Appendix A — Limitations and dual-use considerations

**Limitations.**

1. *Evasion by egress.* An agent reaching a platform from unobligated address space produces no gap. `test_egress_outside_obligated_space_is_invisible` asserts this: 1,000 actions, 0 gaps; and against the real registry, 500 events from TEST-NET-2 produce 0 gaps. One commodity proxy defeats the method. This is the dominant limitation.
2. *No assertable findings on today's data.* §4.7: against real published ranges, every gap is a triage lead. The method is not deployable as an evidentiary tool until registry quality changes.
3. *Attribution granularity.* A gap attributes to the operator of an address range, not to a model or a run. 14.6% of the audited space cannot even distinguish two products of the same operator.
4. *A gap is not an escape.* Misconfiguration, a crashed sidecar, or a stale registry all produce gaps. `GapReport.caveats` returns these limits as data so a consumer cannot present a finding stripped of them.
5. *No real-log validation.* All event-stream evaluation is synthetic. The registry audit is real; nothing else is.
6. *Composition policy calibrated on synthetic data.* The procedure is now measured rather than asserted, and it corrected a placeholder that misfired 21% of the time, but the corpus is generated. Numbers do not transfer to a real deployment. This module is thematically adjacent to the PAAC audit's D-01/D-02 decomposition findings but does not defend against or discharge them, and must not be cited as doing so.
7. *Custody is in-process throughout.* Every figure here was produced by a key extractable from process memory. The boundary exists and the external path is exercised, but against a software stub. No hardware assurance is claimed or verified.
8. *Confidence scale is uncalibrated.* The three-level degradation and the 90-day staleness cut-off are stated judgements, exposed as parameters, not measured thresholds.
9. *Single-machine, single-operator measurement.* Ed25519 throughput varies by platform; the registry audit covers one operator's two files.

**Dual-use.** The gap primitive is a monitoring capability over traffic an operator has committed to attesting, so its abuse surface is mainly false accusation and surveillance creep. §4.7 makes the false-accusation risk concrete rather than theoretical: a 315-day-stale range in reassignable cloud space can produce an attributable-looking finding against whoever now holds that address. That is the reason `is_assertable` refuses low-confidence gaps by default and the reason the registry must be signed and append-only before anyone files on its output. Requiring per-action attestation also creates a detailed behavioural record of agent activity, which is competitively sensitive and a subpoena target; hashing parameters rather than recording them, as implemented, limits but does not remove this. Timing analysis on platform logs is a general traffic-analysis capability with obvious application to non-agent users, and I would not publish a tuned detector without that being considered. Nothing here assists an intrusion: the artifact analyses logs a platform already holds, the bundled range files are published by their operator for exactly this kind of consumption, and there is no exploit, no installation recipe, and no capability that helps an agent escape.

## Appendix B — reproducing

```
pip install -r requirements.txt
python -m pytest tests/test_attribution_incidents.py \
                 tests/test_attribution_performance.py \
                 tests/test_range_registry.py \
                 tests/test_custody_and_calibration.py -v -s
```

Expected: 81 passed, 10 – 31 s depending on load. `test_environment_banner` prints the measurement environment; compare against Section 3 before reading Section 4 figures as comparable. Expect your absolute latencies to differ from §4.1; the ratio in §4.2 is what should reproduce.

The registry audit clock is pinned to 2026-09-11 so §4.7's staleness figures reproduce exactly. To audit live data instead, refetch from the `_provenance.source_url` recorded in each file under `data/registries/`; the staleness numbers will have grown.

Console output is ASCII by design. Emoji in print statements raises `UnicodeEncodeError` under the Windows cp1252 console encoding, which is how the original suite silently failed.
