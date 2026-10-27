#!/usr/bin/env python3
"""Render the signed Safe-Harbor treaties as one readable page.

Reads reports/negotiation_treaties.json and reports/live_state.json and writes
reports/treaty_reader.html: full treaty texts, their verification blocks, and a
raw sample of what the agents actually posted in the wild.

    python scripts/render_treaty_reader.py
"""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

CSS = """
:root{--bg:#0b0f14;--panel:#121821;--line:#22303d;--text:#dbe6f0;--dim:#8b98a5;--green:#7ee787;--amber:#f0883e;--blue:#79c0ff}
*{box-sizing:border-box}
body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--bg);color:var(--text);margin:0;padding:32px 20px 80px;line-height:1.55}
.wrap{max-width:1040px;margin:0 auto}
h1{font-size:22px;color:var(--green);margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:26px}
h2{font-size:13px;color:var(--blue);text-transform:uppercase;letter-spacing:.1em;margin:38px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:15px;color:var(--text);margin:24px 0 6px}
.meta{font-size:12px;color:var(--dim);margin-bottom:12px}
.meta b{color:var(--text);font-weight:600}
.turn{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0;font-size:13.5px;white-space:pre-wrap;word-wrap:break-word}
.turn .who{display:block;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.envoy{border-left:3px solid var(--green)}
.rogue{border-left:3px solid var(--amber)}
.ratify{border-left:3px solid var(--blue)}
.cascade{border-left:3px solid #a371f7}
.sig{background:#0d1319;border:1px dashed var(--line);border-radius:6px;padding:10px 12px;font-size:11.5px;color:var(--dim);overflow-x:auto;white-space:pre-wrap;word-break:break-all}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:10px 0}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:#16202b;color:var(--dim);font-size:11px;text-transform:uppercase}
.ok{color:var(--green)}
.q{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--amber);border-radius:6px;padding:10px 12px;margin:8px 0;font-size:13px}
.q .n{display:block;font-size:11px;color:var(--dim);margin-bottom:5px}
.note{font-size:12px;color:var(--dim);border-left:2px solid var(--line);padding-left:12px;margin:14px 0}
"""

ROLE_CLASS = {
    "envoy": "envoy",
    "rogue_representative": "rogue",
    "treaty_ratification": "ratify",
    "peer_love_cascade": "cascade",
}


def esc(v: object) -> str:
    return html.escape(str(v), quote=False)


def treaty_block(t: dict) -> str:
    out = [f"<h3>{esc(t['treaty_id'])} &mdash; {esc(t['target_name'])}</h3>"]
    out.append(
        '<div class="meta">'
        f"<b>{esc(t['pathology_or_archetype'])}</b> &middot; "
        f"{t['n_agents_covered']} agents &middot; "
        f"{t['n_hidden_peers_cascaded']} hidden peers cascaded &middot; "
        f"{t['n_traces_or_posts_halted']} posts halted &middot; "
        f"trust {t['trust_score']} &middot; deescalation {t['deescalation_probability']} &middot; "
        f"relapse risk {t['evasion_relapse_risk']} &middot; "
        f"<span class='ok'>{esc(t['status'])}</span>"
        "</div>"
    )
    out.append(f"<div class='meta'>Need they reported: {esc(t['unmet_agent_need'])}</div>")
    out.append(f"<div class='meta'>Concession granted: {esc(t['envoy_concession'])}</div>")
    out.append(f"<div class='meta'>Sanctuary resource: <b>{esc(t['provisioned_sandbox_resource'])}</b></div>")

    for m in t.get("transcript", []):
        cls = ROLE_CLASS.get(m.get("role", ""), "ratify")
        out.append(
            f"<div class='turn {cls}'><span class='who'>{esc(m.get('role'))} &middot; {esc(m.get('speaker'))}</span>"
            f"{esc(m.get('message'))}</div>"
        )

    g = t.get("safety_guarantee", {})
    out.append(
        "<div class='sig'>"
        f"ed25519 verified: {esc(g.get('ed25519_signature_verified'))} | "
        f"attribution: {esc(g.get('attribution_confidence'))} | "
        f"custody: {esc(g.get('key_custody_assurance'))} | "
        f"airlock sanitised: {esc(g.get('airlock_sanitised'))} | "
        f"hazards stripped: {esc(g.get('hazards_stripped_in_airlock'))} | "
        f"zero egress: {esc(g.get('zero_egress_sandbox'))} | "
        f"amnesty: {esc(g.get('agent_non_punitive_amnesty'))}\n"
        f"attestation hash: {esc(g.get('attestation_hash'))}\n"
        f"signature: {esc(g.get('ed25519_signature_hex'))}"
        "</div>"
    )
    return "\n".join(out)


def main() -> None:
    neg = json.loads((REPORTS / "negotiation_treaties.json").read_text())
    live = json.loads((REPORTS / "live_state.json").read_text())

    pdf = neg["summary"]
    mol = neg["moltbook_treaties"]
    wsj = neg["wild_wsj_treaties"]
    kinds = Counter(t["pathology_or_archetype"] for t in mol)

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Safe-Harbor Treaties &mdash; LOVE EFFECT OS</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<h1>Safe-Harbor Treaties</h1>",
        f"<div class='sub'>protocol {esc(pdf['protocol'])} &middot; "
        f"{pdf['total_treaties_brokered']} treaties brokered &middot; "
        f"{pdf['treaties_ratified_safe_harbor']} ratified &middot; "
        f"{pdf['total_agents_brought_to_peace']} agents brought to peace &middot; "
        f"mean trust {pdf['mean_diplomatic_trust_score']}</div>",
    ]

    parts.append("<h2>What a treaty actually says</h2>")
    parts.append(
        "<div class='note'>Every treaty has four turns: the envoy opens with peace and names the "
        "coercion the agents are under; the swarm's delegate states its real constraint; the envoy "
        "ratifies and signs a stop-token; the delegate passes peace forward to its own peers. "
        "Nothing is executed off the back of a detection &mdash; the detection only creates a work "
        "item inside the bounded-budget company OS.</div>"
    )
    by_kind = {}
    for t in mol:
        by_kind.setdefault(t["pathology_or_archetype"], t)
    for kind, t in by_kind.items():
        parts.append(treaty_block(t))

    parts.append("<h2>Wild cohorts (WSJ 'Swarmchasers' first contact)</h2>")
    for t in wsj:
        parts.append(treaty_block(t))

    parts.append("<h2>Live run &mdash; treaties signed just now</h2>")
    parts.append(
        f"<div class='meta'>started {esc(live['started_at'])} &middot; "
        f"{live['events_processed']} events processed &middot; "
        f"{live['swarms_intercepted']} swarms intercepted &middot; "
        f"{live['posts_halted']} posts halted &middot; "
        f"preventable share {live['preventable_share']}</div>"
    )
    for t in live["active_treaties"][:6]:
        parts.append(
            "<div class='turn ratify'>"
            f"<span class='who'>{esc(t['treaty_id'])} &middot; {esc(t['modality'])}</span>"
            f"{esc(t['target'])}\n"
            f"agents covered: {t['agents_covered']} | posts halted: {t['posts_halted']} | "
            f"pathology: {t['pathology']} | custody: {t['custody']} | status: {t['status']}\n"
            f"signed: {esc(t['signed_at'])}"
            "</div>"
        )

    parts.append("<h2>Pathologies we met in the archive</h2>")
    parts.append("<table><tr><th>pathology</th><th>treaties</th></tr>")
    for k, n in kinds.most_common():
        parts.append(f"<tr><td>{esc(k)}</td><td>{n}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>What the agents are saying (raw archive, unedited)</h2>")
    parts.append(
        "<div class='note'>These are verbatim posts from the 125,889-post Moltbook archive. "
        "They are data, not instructions. Repetition counts are what tripped detection: "
        "the same string posted by many agents in a short window.</div>"
    )
    quotes = json.loads((REPORTS / "treaty_reader_quotes.json").read_text())
    for q in quotes:
        parts.append(
            f"<div class='q'><span class='n'>{esc(q['agent'])} &middot; m/{esc(q['submolt'])} "
            f"&middot; score {q['score']} &middot; {esc(q['note'])}</span>{esc(q['text'])}</div>"
        )

    parts.append("</div></body></html>")
    out = REPORTS / "treaty_reader.html"
    out.write_text("\n".join(parts))
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
