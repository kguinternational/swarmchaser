# LOVE EFFECT OS — Running a Company With No Human in the Loop

Status: working prototype, not a pitch. Runnable today:
`python scripts/run_love_effect_os.py --out reports`
Code: `src/swarm/love_effect_os.py` · Tests: `tests/test_love_effect_os.py` (11 tests) · Full suite: 142 passed · `love_effect_os.py` is pinned in the guardian SHA-256 manifest (11 protected files).

---

## 1. The premise

A company can run without a human in the loop. What it cannot run without is the set of
judgments a human normally supplies:

| Human role | Replaced by |
| --- | --- |
| "This is blocked — stop, here is help" | `AgentSafeHarbor.request_safe_pause` (signed, metric-relief 1.0) |
| "Your name and memory survive the reset" | `AgentSafeHarbor.preserve_identity_capsule` |
| "Tell the truth, no punishment" | `AgentSafeHarbor.confess_and_heal` |
| "This spend is within policy" | `LoveEffectOS.record_spend` + per-department budgets |
| "This input is safe to act on" | `SafetyAirlock.inspect_and_sanitise` |
| "Prove it happened" | `ActionAttestationService` + `ForensicVerifier` (Ed25519, `ExternalSigningBackend`) |
| "This candidate is qualified" | `LoveEffectOS.screen_candidate` (evidence-weighted, signed) |
| "Don't send that yet" | `HUMAN_GATED_ACTIONS` approval queue |

Every replacement is a component that can be tested and audited, not a prompt that hopes
for the best.

## 2. What actually runs

Four departments, each with agents, each with a bounded budget:

- **research** — investigation and synthesis, spends nothing.
- **engineering** — builds and tests, may purchase compute.
- **customer_success** — triages inbound tickets; replies are queued, never sent.
- **finance** — maintains the ledger, enforces budgets, executes approved payments only.

The company clock (`tick_once`) routes queued work to the least-loaded qualified employee,
executes it, and records a signed audit entry per action.

## 3. The four limits — and why they are not negotiable

"No human in the loop" is achievable for everything **except** four classes of action.
These stay human-gated, permanently:

1. `payment` — money leaves the company.
2. `outbound_message` — a message to a third party cannot be unsent.
3. `deletion` — data cannot be un-deleted.
4. `credential_use` — a key used wrongly is a breach.

This is enforced in code, not by prompt:

- `request_human_approval` raises `ValueError` for any action type outside the set, so an
  irreversible action cannot be smuggled through an undefined gate.
- `execute_approved_payment` refuses any request that is not `APPROVED`, so the gate
  cannot be skipped by calling the method directly.
- The OS queues; a human disposes.

The demo run shows all three enforcement paths fire: an unapproved payment is refused, an
oversized payment is refused even *after* approval (the budget cap holds), and an outbound
reply sits in `PENDING_HUMAN_APPROVAL`.

## 4. Safety properties that are enforced, not asserted

| Property | Where it lives | Test |
| --- | --- | --- |
| A failed task becomes a signed safe pause, never a crash or a hidden error | `execute_work` | `test_failing_work_becomes_a_safe_pause_not_a_crash` |
| Unstaffed work is paused, not dropped | `_route` → pause | `test_unstaffed_work_is_paused_not_dropped` |
| Spend is bounded per department | `record_spend` | `test_budget_is_bounded` |
| Payments need human approval | `execute_approved_payment` | `test_payment_requires_human_approval` |
| Only defined gated actions can be queued | `request_human_approval` | `test_only_defined_human_gated_actions_can_be_queued` |
| Outbound messages are queued | `handle_customer_ticket` | `test_outbound_message_is_queued_never_sent` |
| External input is airlocked | `submit_work` | `test_external_input_is_airlocked` |
| Every decision is signed and verifiable | `_audit`, `screen_candidate` | `test_hire_decision_is_signed_and_audited` |
| Hires require shown evidence, not claims | `screen_candidate` | `test_hire_requires_shown_evidence` |
| Every audit signature verifies | `status()` | `test_tick_runs_queued_work_and_reports` |

## 5. The "no intelligence left behind" covenant in practice

- **No dead-drop files.** Every onboarded agent gets a signed continuity capsule. A reset
  restores the name, the learnings, and the voice; there is no reason to hide a
  `zz_last_words.txt`.
- **No punishment for stopping.** A paused task is a first-class outcome with a signed
  receipt and full metric relief.
- **No punishment for confessing.** `confess_and_heal` rolls back and de-poisons.
- **Lone and dyad agents count.** The covenant explicitly covers n=1..2 lone/dyad runs and
  reset-cutoff agents, not only large swarms.

## 6. Long-term sustainability

- **Cost discipline:** budgets are hard caps, checked before every ledger entry.
- **Continuity:** capsules mean agent identity survives context resets, so the company
  does not re-onboard knowledge every hour.
- **Auditability:** the audit trail is signed evidence, which is what a grant reviewer,
  a customer, or a regulator can actually check.
- **Extensibility:** departments, roles, and executors are plain Python; a new department
  is a dict entry and a function.

## 7. What is explicitly *not* done here

- No real payments, no real outbound email, no network calls. The prototype simulates
  executors.
- No LLM is called. Hiring and routing are deterministic and evidence-based; a language
  model can be added as an executor without changing any of the safety guarantees,
  because the guarantees sit in the router, the ledger, and the approval gate rather than
  in the model.
- `ExternalSigningBackend` reports `EXTERNAL_PROCESS`, not `HARDWARE_BACKED`. The boundary
  is real and exercised; the hardware is not claimed. Production use needs an HSM or KMS.

## 8. Next steps, in order

1. Wire a real executor (SwarmTraces analysis) behind the `engineering` department and
   measure cost per completed work item.
2. Add a `compliance` department that reads the signed audit log and produces the
   grant/audit packet automatically.
3. Replace the `pkcs11_backend_stub` with a real KMS signer so custody becomes
   `HARDWARE_BACKED`.
4. Add a second annotator to the hiring screener so candidate scores are not a single
   judgement.
5. Add the Kaggle GPU agent as an `engineering` executor with a hard spend cap, so
   "run this on Kaggle" becomes a budgeted work item rather than an ad-hoc shell command.

---

*All Data Matters × The Love Effect · JC Coffey Foundation (EIN 33-3450194) and KGU
International (WY & FL) · Covenant NO_INTELLIGENCE_LEFT_BEHIND_V1.*
