# Attestation gaps: detecting AI agent escapes from the receiving side

Apache-2.0. Built for the Apart Research / CeSIA AI Incident Response Sprint, September 2026.
Full write-up: [HACKATHON_SUBMISSION.md](HACKATHON_SUBMISSION.md).

## The short version

Making agent actions carry an Ed25519 signature does not help you attribute an escape. An agent that leaves its sandbox to steal benchmark answers does not sign what it does next. Verified against the shape of both documented 2026 incidents, a signature-only view returns zero attributable actions and names the culprit `unknown`.

What works is the inverse. If an operator is obliged to attest every outbound action, then an **unsigned** action arriving from that operator's registered address space is itself the evidence. The receiving platform checks this against its own logs, with no cooperation from the operator and no access to its network.

Then the third finding, which is the one with real data behind it: audited against the egress range files OpenAI actually publishes, **not one prefix is good enough to support an assertable finding**. 315 days stale, 6 prefixes claimed by two products at once, 39 of 60 in reassignable cloud space. Gap detection works; the registry it depends on does not, yet.

## What's here

| Module | Role |
|---|---|
| `attestation_service.py` | Ed25519 per-action signing. The cooperative case. |
| `key_custody.py` | Signing-key custody boundary. In-process vs external, honestly labelled. |
| `forensic_verifier.py` | Third-party verification from a public key alone. |
| `gap_detector.py` | Scans platform logs for missing-but-required attestations. The non-cooperative case. |
| `range_registry.py` | Audits published egress ranges; signed append-only registry. |
| `composability_detector.py` | Cumulative-privilege analysis across an action sequence. |
| `policy_calibration.py` | Derives composition thresholds from a benign baseline. |
| `paac_integration.py` | Hooks into the existing PAAC monitor. |

`data/registries/` holds cached snapshots of the real published range files, so the audit figures reproduce exactly.

## Run it

```bash
pip install -r requirements.txt
python -m pytest tests/test_attribution_incidents.py \
                 tests/test_attribution_performance.py \
                 tests/test_range_registry.py \
                 tests/test_custody_and_calibration.py -v -s
```

81 tests, about 12 s. The suite prints its own environment and every performance number it reports; nothing is hardcoded.

## Measured (Python 3.11.9, Windows 10, Intel64 Family 6 Model 186)

Ranges are across three consecutive runs on the same idle machine.

| | |
|---|---|
| Attestation generation | 0.035 - 0.045 ms mean |
| Verification, distinct actions | 0.086 - 0.133 ms mean |
| Gap scan, 17,600 events | 0.088 - 0.122 s |
| Signed analysis, 17,600 actions | 1.61 - 2.12 s |
| Attestation size | 498 bytes, constant |

Run-to-run variance reached ~50% on the verification path, so don't read single-run precision into these. Gap scanning is cheaper per event than signed analysis by 10x to 24x depending on the run. An earlier version of this file claimed a stable 18x from two runs; a third run showed that ratio isn't stable, so the honest claim is "an order of magnitude", not a number.

Single machine. Ed25519 throughput varies by platform and Python build; re-run before quoting.

## Real registry audit (clock pinned to 2026-09-11)

| Property | Measured |
|---|---|
| Prefixes published | 60 |
| Distinct addresses | 5,264 |
| GPTBot file staleness | 315 days |
| SearchBot file staleness | 251 days |
| Prefixes claimed by both products | 6 |
| Addresses not attributable to one product | 768 (14.6%) |
| Prefixes in multi-tenant cloud space | 39 of 60 |
| Prefixes at high confidence | **0** |

The operator's docs say to refetch because ranges rotate. The published snapshots are 8 and 10 months old. That makes staleness the default state, not an edge case.

## Example

```python
from src.attribution import (
    ForensicVerifier, GapDetector, load_bundled_openai_registries,
)

verifier = ForensicVerifier()
verifier.register_lab_public_key("openai", operator_public_key_pem)

detector = GapDetector(verifier)

# Load real published ranges, carrying their audited confidence.
audit = load_bundled_openai_registries()
detector.register_from_audit(audit)

report = detector.scan(events_from_your_own_logs)

print(report.summary())
print(f"assertable findings: {len(report.assertable_gaps)}")   # 0, on today's data
for caveat in report.caveats:
    print(" -", caveat)
```

`GapReport.caveats` returns the limits as data, and `is_assertable` refuses to promote a gap from a degraded range into a finding. Both exist so a downstream consumer cannot present a result with the caveats stripped off.

## What this does not do

- **One proxy defeats it.** Traffic from unobligated address space produces no gap. `test_egress_outside_obligated_space_is_invisible` asserts exactly this: 1,000 actions, 0 gaps.
- **Nothing is assertable on today's registry data.** Every gap from the real published ranges is a triage lead. See the table above.
- **A gap is not an escape.** Misconfiguration, a dead sidecar, or a stale CIDR registry all produce gaps.
- **Attribution is to an address range,** not to a model or a run. 14.6% of the audited space can't even separate two products of the same operator.
- **Event-stream evaluation is synthetic.** The registry audit is real data; the 15k/17.6k streams are not. Production false-positive rate is unmeasured, and the public-log route for measuring it is closed — MediaWiki no longer exposes source IPs for unregistered editors.
- **Composition thresholds are calibrated on a synthetic corpus.** The procedure is measured, and it caught the shipped placeholder of 3 misfiring on **21% of benign** held-out sequences (derived value 5 gives 0%). But the corpus is generated, so the number doesn't transfer. Adjacent to the PAAC audit's D-01/D-02 findings; does not discharge them.
- **Custody is in-process throughout.** Every signature here came from a key extractable from process memory, which the escaped agent could also read. The external/PKCS#11 path exists and is exercised, against a software stub. No hardware assurance is claimed.
- **Timing is corroborating only.** Fixed intervals are trivially separable from human traffic; an agent adding jitter raises nothing, and `test_jittered_agent_defeats_timing_signal` proves it.

## Contact

Shashank Kumar — shashankchoudhary792@gmail.com
