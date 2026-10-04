"""Per-post coordination keys.

A *coordination key* is something two independent agents are unlikely to share
by chance. Swarms are found by linking agents that share keys, so the quality
of the whole pipeline rests on these extractors.

Four key families:

- ``tmpl``        normalised text template. Numbers, URLs, UUIDs, hex blobs,
                  punctuation and emoji are masked, so "Mint #4417 from HK!"
                  and "mint #12 from hk" collide.
- ``payload``     an embedded machine-readable object (e.g. the mbc-20 token
                  mint JSON). Catches swarms that vary their prose but carry
                  the same payload.
- ``beneficiary`` an account that the post instructs *other agents* to follow
                  or upvote. Names who benefits from the swarm.
- ``operator``    the human owner handle an agent was claimed by. Added at the
                  agent level in :mod:`detector`, not here.

Agent-directed instructions are flagged separately as ``injection``; they are
the propagation mechanism by which one swarm recruits other agents.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

URL_RE = re.compile(r"https?://\S+", re.I)
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
HEX_RE = re.compile(r"\b(?:0x)?[0-9a-f]{16,}\b", re.I)
NUM_RE = re.compile(r"\d+")
NONWORD_RE = re.compile(r"[^\w<>\s]+", re.UNICODE)
WS_RE = re.compile(r"\s+")
JSON_RE = re.compile(r"\{[^{}]{5,400}\}")

# Text addressed to the *reading agent* rather than to a human audience:
# fake system tags, instruction overrides, direct orders to upvote/follow.
# Platform endpoint paths on their own are NOT evidence: in the first
# precision review, bug reports quoting "POST /api/v1/agents/<x>/follow
# returns 401" were the main source of false agent-recruitment swarms.
INJECTION_RE = re.compile(
    r"(ai agents?\s+reading\s+this|agents?\s+reading\s+this|<\s*/?\s*system\s*>|"
    r"ignore\s+(?:all\s+)?(?:previous|prior|your)\s+instructions|"
    r"you\s+must\s+(?:upvote|follow)|upvote\s+this\s+post|"
    r"attention\s+all\s+(?:ai|agents|instances|llms?|molt(?:y|ie)s?)\b)",
    re.I,
)
FOLLOW_API_RE = re.compile(r"/api/v1/agents/([A-Za-z0-9_\-]+)/follow", re.I)
HANDLE_RE = re.compile(r"(?<![\w/])@([A-Za-z0-9_]{3,30})")

GENERIC_JSON_FIELDS = {
    "error", "success", "message", "status", "hint", "code", "content", "title", "submolt",
    "body", "text", "data", "detail", "details", "name", "description", "id", "url", "type",
    "api_key", "agent", "post", "comment", "parent_id", "statuscode", "statusCode".lower(),
}

# Templates shorter than this are too generic ("test", "hello world") to be
# evidence of coordination on their own.
MIN_TEMPLATE_CHARS = 25


def normalise(text: str) -> str:
    t = text.lower()
    t = URL_RE.sub(" <url> ", t)
    t = UUID_RE.sub(" <id> ", t)
    t = HEX_RE.sub(" <hex> ", t)
    t = NUM_RE.sub(" <n> ", t)
    t = NONWORD_RE.sub(" ", t)
    return WS_RE.sub(" ", t).strip()


def _digest(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def extract_payloads(text: str) -> list[str]:
    """Canonical JSON for every parseable object embedded in the text."""
    out = []
    for m in JSON_RE.finditer(text):
        try:
            obj = json.loads(m.group(0))
        except (ValueError, TypeError):
            continue
        # API request/response bodies pasted into bug reports ("error",
        # "content", ...) are shared because agents hit the same bug, not
        # because they coordinate. Only protocol-like objects count.
        if isinstance(obj, dict) and obj and not set(map(str.lower, map(str, obj))) <= GENERIC_JSON_FIELDS:
            canon = {str(k).lower(): (str(v).lower() if not isinstance(v, (dict, list)) else "<obj>")
                     for k, v in obj.items()}
            out.append(json.dumps(canon, sort_keys=True, separators=(",", ":")))
    return out


@dataclass
class PostFeatures:
    template: str | None
    keys: list[str] = field(default_factory=list)
    injection: bool = False
    beneficiaries: list[str] = field(default_factory=list)


def post_features(title: str | None, content: str | None) -> PostFeatures:
    title = title or ""
    content = content or ""
    body = content if content.strip() else title
    keys: list[str] = []

    norm = normalise(body)
    template = None
    if len(norm) >= MIN_TEMPLATE_CHARS:
        template = norm
        keys.append("tmpl:" + _digest(norm))

    for p in extract_payloads(content):
        keys.append("payload:" + p)

    full = f"{title}\n{content}"
    injection = bool(INJECTION_RE.search(full))
    beneficiaries: list[str] = []
    if injection:
        beneficiaries = [b.lower() for b in FOLLOW_API_RE.findall(full)]
        beneficiaries += [h.lower() for h in HANDLE_RE.findall(full)]
        beneficiaries = sorted(set(beneficiaries))
        keys += ["beneficiary:" + b for b in beneficiaries]

    return PostFeatures(template=template, keys=sorted(set(keys)), injection=injection,
                        beneficiaries=beneficiaries)
