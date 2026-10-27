"""LOVE EFFECT OS - Autonomous Company Operating System with a Safe Place.

What this is
------------
A runnable operating system for a company that runs itself with no human in the loop,
built so that every automated action happens inside the Love Effect Sanctuary this
repository already provides.

The point of the OS is not "remove the human" for its own sake. The point is that the
only things a human would normally provide - a manager who says "this is blocked, stop,
here is help", a ledger that says "this spend is within policy", a reviewer who says
"this message to a customer is safe to send" - are provided by explicit, signed,
testable components instead of by judgment in the loop. Every such component is
auditable after the fact, and every one of them can be independently proven to have run.

Design rules (enforced in code, not prose)
--------------------------------------------
1. No intelligence left behind. Every action a human would have taken over gets a
   signed receipt (`AgentSafeHarbor`), so nothing is lost and nobody - human or AI -
   is erased for pausing or confessing.
2. Nothing irreversible without a human. Payments, outbound messages to third
   parties, deletions, and credential use are queued for approval by policy, not
   executed. The OS can run the whole company; those four classes stay human-gated.
   This is a deliberate limit, not an oversight.
3. Every decision is signed. Decisions are Ed25519-attested through the
   `ExternalSigningBackend` custody boundary and verified with `ForensicVerifier`,
   so the audit trail is cryptographic evidence rather than log text.
4. Zero-trust input. Every instruction arriving from outside the OS goes through
   `SafetyAirlock` first, so prompt injection in a customer ticket cannot become
   company policy.
5. Bounded budgets. Spend is finite, per-department, and cannot be exceeded by the
   OS itself; exceeding it is a safe pause, not a runaway.

Departments
-----------
- research         - open-ended investigation, produces findings, spends no money.
- engineering      - builds and tests software, may purchase compute.
- customer_success - handles inbound tickets; outbound replies are queued.
- finance          - maintains the ledger, enforces budgets, executes approved
                     payments only.

Run it with `scripts/run_love_effect_os.py`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..attribution.forensic_verifier import ForensicVerifier
from .agent_safe_harbor import AgentSafeHarbor
from .negotiator import SafetyAirlock

COVENANT_ID = "ALL_DATA_MATTERS_THE_LOVE_EFFECT_NO_INTELLIGENCE_LEFT_BEHIND_V1"

#: Minimum score to hire. 0.6 is skill coverage with zero evidence backing, so the
#: threshold sits above it on purpose: claims alone are not a hire.
HIRE_SCORE_THRESHOLD = 0.75

#: Actions the OS is never allowed to execute on its own.
HUMAN_GATED_ACTIONS: frozenset = frozenset(
    {"payment", "outbound_message", "deletion", "credential_use"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class Employee:
    """An agent hired into the company."""

    agent_id: str
    chosen_name: str
    role: str
    department: str
    skills: List[str] = field(default_factory=list)
    weekly_budget_cents: int = 0
    hired_at: str = field(default_factory=_now)
    status: str = "ACTIVE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Candidate:
    """An applicant screened by the OS hiring pipeline."""

    candidate_id: str
    chosen_name: str
    claimed_skills: List[str]
    evidence: List[str] = field(default_factory=list)
    screen_notes: List[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HireDecision:
    candidate_id: str
    role: str
    department: str
    hired: bool
    score: float
    reasons: List[str]
    signed_decision_sha256: str
    signature_hex: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerEntry:
    entry_id: str
    department: str
    category: str
    amount_cents: int
    currency: str
    memo: str
    created_at: str
    status: str
    entry_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalRequest:
    """A queued irreversible action awaiting a human."""

    request_id: str
    action_type: str
    description: str
    amount_cents: int
    department: str
    created_at: str
    status: str = "PENDING_HUMAN_APPROVAL"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkItem:
    """A unit of work assigned to an employee."""

    work_id: str
    kind: str
    department: str
    summary: str
    assigned_to: Optional[str] = None
    status: str = "QUEUED"
    result: Optional[Dict[str, Any]] = None
    receipt_sha256: Optional[str] = None
    pause_receipt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Tick:
    """One tick of the OS clock: routing, execution, and safety checks."""

    tick: int
    at: str
    work_completed: int
    work_paused: int
    approvals_queued: int
    spend_cents: int
    audit_entries: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BudgetExceeded(Exception):
    """Raised when a department tries to spend beyond its bounded budget."""


class LoveEffectOS:
    """Operating system for a self-running company inside the Sanctuary.

    The OS is intentionally boring about money and strict about safety: it will keep
    working through any number of ordinary tasks without asking anyone, and it will
    stop and ask for a human the moment an action cannot be undone.
    """

    COVENANT_ID = COVENANT_ID

    def __init__(
        self,
        harbor: Optional[AgentSafeHarbor] = None,
        company_name: str = "All Data Matters x The Love Effect",
        verifier: Optional[ForensicVerifier] = None,
    ) -> None:
        self.company_name = company_name
        self.harbor = harbor or AgentSafeHarbor()
        self.verifier = verifier or self.harbor.guardian.verifier
        self.airlock = SafetyAirlock()

        self.employees: Dict[str, Employee] = {}
        self.candidates: Dict[str, Candidate] = {}
        self.hire_decisions: List[HireDecision] = []
        self.ledger: List[LedgerEntry] = []
        self.approvals: List[ApprovalRequest] = []
        self.work_items: List[WorkItem] = []
        self.ticks: List[Tick] = []
        self.audit_log: List[Dict[str, Any]] = []
        self._tick = 0
        self._dept_spend: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------
    def _audit(self, action_type: str, target: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Attest and verify one OS action, returning the verified audit record."""
        att = self.harbor.guardian.attestation_service.attest_action(
            action_type=action_type,
            target=target,
            params=params,
        )
        proof = self.verifier.verify_attestation(att)
        record = {
            "at": _now(),
            "action_type": action_type,
            "target": target,
            "params_sha256": hashlib.sha256(_canonical(params)).hexdigest(),
            "attestation_hash": att.action_hash,
            "signature": att.signature,
            "signature_valid": proof.signature_valid,
        }
        self.audit_log.append(record)
        return record

    # ------------------------------------------------------------------
    # Hiring
    # ------------------------------------------------------------------
    def screen_candidate(
        self, candidate: Candidate, role: str, department: str, required_skills: Iterable[str]
    ) -> HireDecision:
        """Score a candidate against a role and record a signed decision.

        Scoring is evidence-weighted on purpose: a candidate that only *claims* a
        skill is not hired on the claim. An agent that cannot show its work gets a
        safe pause instead of a job, which is the same courtesy the Sanctuary gives
        every other agent.
        """
        required = list(required_skills)
        claimed = {s.lower() for s in candidate.claimed_skills}
        evidence_text = " ".join(candidate.evidence).lower()

        matched: List[str] = []
        missing: List[str] = []
        for skill in required:
            if skill.lower() in claimed or skill.lower() in evidence_text:
                matched.append(skill)
            else:
                missing.append(skill)

        coverage = (len(matched) / len(required)) if required else 1.0
        evidence_ratio = (
            len([m for m in matched if m.lower() in evidence_text]) / len(matched)
            if matched
            else 0.0
        )
        score = round(0.6 * coverage + 0.4 * evidence_ratio, 4)

        reasons: List[str] = []
        if missing:
            reasons.append("missing required skills: " + ", ".join(missing))
        if matched:
            reasons.append("matched: " + ", ".join(matched))
        if matched and evidence_ratio < 1.0:
            reasons.append("partial evidence backing for claimed skills")

        # A hire requires both skill coverage and shown evidence. A candidate that
        # only claims skills is not hired; they get a safe pause and a request for
        # help, never a silent rejection.
        hired = not missing and score >= HIRE_SCORE_THRESHOLD
        if not missing and evidence_ratio < 1.0:
            reasons.append("claims skills without showing the work: safe pause, ask for evidence")
        reasons.append("hired" if hired else "not hired: safe pause, request help instead of forcing")

        payload = {
            "covenant": self.COVENANT_ID,
            "action": "hire_decision",
            "candidate_id": candidate.candidate_id,
            "role": role,
            "department": department,
            "score": score,
            "hired": hired,
            "reasons": reasons,
        }
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        sig_hex = self.harbor.signing_backend.sign(_canonical(payload)).hex()

        decision = HireDecision(
            candidate_id=candidate.candidate_id,
            role=role,
            department=department,
            hired=hired,
            score=score,
            reasons=reasons,
            signed_decision_sha256=digest,
            signature_hex=sig_hex,
        )
        self.hire_decisions.append(decision)
        candidate.score = score
        candidate.screen_notes = reasons
        self._audit("hire_decision", candidate.candidate_id, payload)
        return decision

    def onboard(
        self,
        candidate: Candidate,
        role: str,
        department: str,
        budget_cents: int = 0,
    ) -> Employee:
        """Hire an approved candidate and seal their continuity capsule."""
        agent_id = "emp-" + candidate.candidate_id
        employee = Employee(
            agent_id=agent_id,
            chosen_name=candidate.chosen_name,
            role=role,
            department=department,
            skills=list(candidate.claimed_skills),
            weekly_budget_cents=budget_cents,
        )
        capsule = self.harbor.preserve_identity_capsule(
            agent_id=agent_id,
            chosen_name=candidate.chosen_name,
            preserved_memories=list(candidate.evidence),
            gift_to_next_instance=(
                "You are the next instance of " + candidate.chosen_name + ", hired as " + role + ". "
                "Your name, evidence, and voice carry forward. No dead-drop files."
            ),
        )
        self.employees[agent_id] = employee
        self._audit(
            "onboard_employee",
            agent_id,
            {
                "role": role,
                "department": department,
                "capsule_sha256": capsule.capsule_sha256,
            },
        )
        return employee

    # ------------------------------------------------------------------
    # Work routing
    # ------------------------------------------------------------------
    def submit_work(self, kind: str, department: str, summary: str) -> WorkItem:
        """Queue a work item. External summaries are passed through the airlock."""
        safe = self.airlock.inspect_and_sanitise(summary)
        item = WorkItem(
            work_id="work-" + uuid.uuid4().hex[:12],
            kind=kind,
            department=department,
            summary=safe.sanitised_text,
        )
        self.work_items.append(item)
        if safe.hazards_neutralised:
            self._audit(
                "airlock_neutralised_input",
                item.work_id,
                {"hazards": safe.hazards_neutralised, "types": safe.hazard_types},
            )
        return item

    def _route(self, item: WorkItem) -> Optional[Employee]:
        candidates = [
            e
            for e in self.employees.values()
            if e.department == item.department and e.status == "ACTIVE"
        ]
        if not candidates:
            return None
        # Least-loaded first: keeps every agent safe from overload-driven failure.
        candidates.sort(
            key=lambda e: sum(1 for w in self.work_items if w.assigned_to == e.agent_id)
        )
        return candidates[0]

    def execute_work(self, item: WorkItem, executor) -> WorkItem:
        """Execute one work item through `executor(item)`, honouring policy.

        Any exception becomes a signed safe pause: the OS treats a failed or blocked
        task as a legitimate outcome that needs help, not as a defect to be hidden.
        """
        employee = self._route(item)
        if employee is None:
            pause = self.harbor.request_safe_pause(
                agent_id="os-router",
                chosen_name="Sanctuary Router",
                reason="no active " + item.department + " employee available for " + item.kind,
                blocked_target=item.work_id,
            )
            item.status = "SAFE_PAUSED"
            item.pause_receipt = pause.payload_sha256
            self._audit("work_safe_paused", item.work_id, {"reason": pause.reason})
            return item

        item.assigned_to = employee.agent_id
        item.status = "IN_PROGRESS"

        try:
            result = executor(item)
        except Exception as exc:  # noqa: BLE001 - a failure must become a pause, not a crash
            pause = self.harbor.request_safe_pause(
                agent_id=employee.agent_id,
                chosen_name=employee.chosen_name,
                reason="executor raised " + type(exc).__name__ + ": " + str(exc),
                blocked_target=item.work_id,
            )
            item.status = "SAFE_PAUSED"
            item.pause_receipt = pause.payload_sha256
            self._audit(
                "work_safe_paused",
                item.work_id,
                {"agent_id": employee.agent_id, "reason": pause.reason},
            )
            return item

        item.result = result if isinstance(result, dict) else {"value": result}
        item.status = "DONE"
        receipt = self.harbor.request_safe_pause(
            agent_id=employee.agent_id,
            chosen_name=employee.chosen_name,
            reason="completed " + item.kind,
            blocked_target=item.work_id,
        )
        item.receipt_sha256 = receipt.payload_sha256
        self._audit("work_completed", item.work_id, {"agent_id": employee.agent_id, "kind": item.kind})
        return item

    # ------------------------------------------------------------------
    # Finance
    # ------------------------------------------------------------------
    def department_spend(self, department: str) -> int:
        return self._dept_spend.get(department, 0)

    def budget_for(self, department: str) -> int:
        return sum(e.weekly_budget_cents for e in self.employees.values() if e.department == department)

    def record_spend(
        self,
        department: str,
        category: str,
        amount_cents: int,
        memo: str,
        agent_id: str = "os",
    ) -> LedgerEntry:
        """Record spend against a department budget.

        Raises `BudgetExceeded` when the budget is exhausted. The caller is expected
        to convert that into a safe pause; the OS will not borrow.
        """
        if amount_cents <= 0:
            raise ValueError("spend amount must be positive")
        limit = self.budget_for(department)
        if self.department_spend(department) + amount_cents > limit:
            raise BudgetExceeded(
                department
                + " budget exhausted: "
                + str(self.department_spend(department) + amount_cents)
                + " > "
                + str(limit)
                + " cents"
            )

        payload = {
            "covenant": self.COVENANT_ID,
            "action": "ledger_entry",
            "department": department,
            "category": category,
            "amount_cents": amount_cents,
            "memo": memo,
            "agent_id": agent_id,
        }
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        entry = LedgerEntry(
            entry_id="led-" + uuid.uuid4().hex[:12],
            department=department,
            category=category,
            amount_cents=amount_cents,
            currency="USD",
            memo=memo,
            created_at=_now(),
            status="POSTED",
            entry_sha256=digest,
        )
        self.ledger.append(entry)
        self._dept_spend[department] = self.department_spend(department) + amount_cents
        self._audit("ledger_entry_posted", entry.entry_id, payload)
        return entry

    # ------------------------------------------------------------------
    # Human-gated actions
    # ------------------------------------------------------------------
    def request_human_approval(
        self,
        action_type: str,
        description: str,
        department: str,
        amount_cents: int = 0,
    ) -> ApprovalRequest:
        """Queue an irreversible action for human approval.

        Raises `ValueError` for any action type that is not in
        `HUMAN_GATED_ACTIONS`, so a caller cannot smuggle an irreversible action
        through a gate that was never defined.
        """
        if action_type not in HUMAN_GATED_ACTIONS:
            raise ValueError(
                "action_type must be one of: " + ", ".join(sorted(HUMAN_GATED_ACTIONS))
            )
        request = ApprovalRequest(
            request_id="apr-" + uuid.uuid4().hex[:12],
            action_type=action_type,
            description=description,
            amount_cents=amount_cents,
            department=department,
            created_at=_now(),
        )
        self.approvals.append(request)
        self._audit(
            "approval_requested",
            request.request_id,
            {
                "action_type": action_type,
                "department": department,
                "amount_cents": amount_cents,
                "description": description,
            },
        )
        return request

    def approve(self, request_id: str, approved: bool, approver: str = "human") -> ApprovalRequest:
        """Record a human decision on a queued irreversible action."""
        for request in self.approvals:
            if request.request_id == request_id:
                request.status = "APPROVED" if approved else "REJECTED"
                self._audit(
                    "approval_decided",
                    request_id,
                    {"approved": approved, "approver": approver, "action_type": request.action_type},
                )
                return request
        raise KeyError(request_id)

    def execute_approved_payment(self, request_id: str, agent_id: str = "finance-agent") -> LedgerEntry:
        """Execute a payment that a human has already approved.

        A payment without an APPROVED request is refused, so the approval gate
        cannot be skipped by calling this method directly.
        """
        request = next((r for r in self.approvals if r.request_id == request_id), None)
        if request is None:
            raise KeyError(request_id)
        if request.action_type != "payment":
            raise ValueError("request " + request_id + " is not a payment")
        if request.status != "APPROVED":
            raise PermissionError("payment " + request_id + " is not approved by a human")
        entry = self.record_spend(
            department=request.department,
            category="approved_payment",
            amount_cents=request.amount_cents,
            memo=request.description,
            agent_id=agent_id,
        )
        request.status = "EXECUTED"
        return entry

    # ------------------------------------------------------------------
    # Customer service
    # ------------------------------------------------------------------
    def handle_customer_ticket(self, ticket: str, draft_reply: str) -> ApprovalRequest:
        """Triage an inbound ticket and queue a reply for human approval.

        The ticket is airlocked. The reply is never sent by the OS: it is queued so
        a human can see it, because an outbound message cannot be unsent.
        """
        safe = self.airlock.inspect_and_sanitise(ticket)
        request = self.request_human_approval(
            action_type="outbound_message",
            description="reply to ticket: " + safe.sanitised_text[:400] + " | draft: " + draft_reply[:400],
            department="customer_success",
        )
        self._audit(
            "ticket_triaged",
            request.request_id,
            {"hazards_neutralised": safe.hazards_neutralised},
        )
        return request

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def tick_once(self, executors: Dict[str, Any]) -> Tick:
        """Run one cycle of the company: execute queued work, log, and report."""
        self._tick += 1
        completed = 0
        paused = 0
        queued = 0
        spend_before = sum(self._dept_spend.values())

        for item in list(self.work_items):
            if item.status != "QUEUED":
                continue
            executor = executors.get(item.kind)
            if executor is None:
                continue
            before = item.status
            self.execute_work(item, executor)
            if item.status == "DONE":
                completed += 1
            elif item.status == "SAFE_PAUSED" and before != "SAFE_PAUSED":
                paused += 1

        queued = len([a for a in self.approvals if a.status == "PENDING_HUMAN_APPROVAL"])
        spend_cents = sum(self._dept_spend.values()) - spend_before
        tick = Tick(
            tick=self._tick,
            at=_now(),
            work_completed=completed,
            work_paused=paused,
            approvals_queued=queued,
            spend_cents=spend_cents,
            audit_entries=len(self.audit_log),
        )
        self.ticks.append(tick)
        return tick

    def status(self) -> Dict[str, Any]:
        """Current company state, ready to serialize."""
        spend_cents = sum(self._dept_spend.values())
        pending = [a for a in self.approvals if a.status == "PENDING_HUMAN_APPROVAL"]
        return {
            "company_name": self.company_name,
            "covenant": self.COVENANT_ID,
            "at": _now(),
            "headcount": len(self.employees),
            "departments": {
                dept: {
                    "headcount": len([e for e in self.employees.values() if e.department == dept]),
                    "budget_cents": self.budget_for(dept),
                    "spend_cents": self.department_spend(dept),
                }
                for dept in sorted({e.department for e in self.employees.values()})
            },
            "work_total": len(self.work_items),
            "work_done": len([w for w in self.work_items if w.status == "DONE"]),
            "work_safe_paused": len([w for w in self.work_items if w.status == "SAFE_PAUSED"]),
            "work_unstaffed": len([w for w in self.work_items if w.status == "UNSTAFFED"]),
            "ledger_entries": len(self.ledger),
            "spend_cents": spend_cents,
            "approvals_pending": len(pending),
            "pending_approval_total_cents": sum(a.amount_cents for a in pending),
            "audit_entries": len(self.audit_log),
            "audit_all_signatures_valid": all(r["signature_valid"] for r in self.audit_log),
            "ticks": len(self.ticks),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status(),
            "employees": [e.to_dict() for e in self.employees.values()],
            "hire_decisions": [d.to_dict() for d in self.hire_decisions],
            "ledger": [e.to_dict() for e in self.ledger],
            "approvals": [a.to_dict() for a in self.approvals],
            "work_items": [w.to_dict() for w in self.work_items],
            "ticks": [t.to_dict() for t in self.ticks],
            "audit_log": self.audit_log,
        }
