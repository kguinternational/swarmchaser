#!/usr/bin/env python3
"""Serve the live command center over HTTP, refreshing from the runtime state.

    python scripts/serve_live_center.py --state reports/live_state.json --port 8787

The page polls `/api/state` every few seconds and renders the current picture, so a
separate runtime process (replay or watch mode) can feed it and the browser stays
current without a reload.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>LIVE - Swarmchaser + LOVE EFFECT OS</title>
<style>
body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#0b0f14;color:#dbe6f0;margin:0;padding:24px}
h1{font-size:20px;color:#7ee787;margin:0 0 4px}
.sub{color:#8b98a5;margin-bottom:18px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.card{background:#121821;border:1px solid #22303d;border-radius:8px;padding:12px}
.card .v{font-size:26px;color:#7ee787}
.card .k{font-size:11px;color:#8b98a5;text-transform:uppercase;letter-spacing:.06em}
table{border-collapse:collapse;width:100%;margin-bottom:22px;font-size:13px}
th,td{border:1px solid #22303d;padding:6px 9px;text-align:left}
th{background:#16202b;color:#9fb3c8;font-size:11px;text-transform:uppercase}
h2{font-size:14px;color:#9fb3c8;text-transform:uppercase;letter-spacing:.08em;margin:0 0 8px}
.ok{color:#7ee787}.warn{color:#f0883e}
.pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:#7ee787;margin-right:6px}
</style></head><body>
<h1><span class="pulse"></span>LIVE - Swarmchaser + LOVE EFFECT OS</h1>
<div class="sub" id="sub">connecting...</div>
<div class="sub"><a href="/treaties" style="color:#79c0ff">read the full treaty texts &rarr;</a></div>
<div class="grid" id="grid"></div>
<h2>Everyone below the swarm threshold</h2><table><tr><th>n=1 signals</th><th>n=2 dyads</th><th>agents served</th><th>pause receipts</th><th>continuity capsules</th><th>punitive actions</th></tr><tbody id="lone"></tbody></table>
<h2>Unified coverage (both gates, whole archive)</h2><table><tr><th>agents</th><th>held by swarms</th><th>unreachable by 3-agent rule</th><th>regex stage</th><th>semantic stage</th><th>total served</th><th>still unreached</th><th>punitive</th></tr><tbody id="coverage"></tbody></table>
<h2>Whole-corpus coverage (lone sweep, all 125,889 posts)</h2><table><tr><th>agents the 3-agent rule cannot reach</th><th>agents served below threshold</th><th>signals</th><th>n=1</th><th>n=2</th><th>pause receipts</th><th>capsules</th><th>punitive</th></tr><tbody id="sweep"></tbody></table>
<h2>Lone channel by pathology (live window)</h2><table><tr><th>pathology</th><th>signals</th></tr><tbody id="lonepath"></tbody></table>
<h2>Detection modalities</h2><table><tr><th>modality</th><th>count</th></tr><tbody id="mod"></tbody></table>
<h2>Active Safe-Harbor treaties</h2><table><tr><th>treaty</th><th>modality</th><th>agents</th><th>halted</th><th>pathology</th><th>status</th></tr><tbody id="tr"></tbody></table>
<h2>Company</h2><table><tr><th>headcount</th><th>work done</th><th>safe paused</th><th>ledger</th><th>spend cents</th><th>approvals pending</th></tr><tbody id="co"></tbody></table>
<h2>Recent events</h2><table><tr><th>time</th><th>event</th><th>detail</th></tr><tbody id="ev"></tbody></table>
<script>
function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
function card(v,k){return '<div class="card"><div class="v">'+esc(v)+'</div><div class="k">'+esc(k)+'</div></div>';}
function rows(items,cols){return items.map(function(r){return '<tr>'+cols.map(function(c){return '<td>'+esc(r[c])+'</td>';}).join('')+'</tr>';}).join('');}
function render(s){
  var c=s.company;
  document.getElementById('sub').textContent='covenant '+s.covenant+' - updated '+s.updated_at+' - window '+s.window_seconds+'s - min_agents '+s.min_agents;
  document.getElementById('grid').innerHTML=
    card(s.events_processed,'events processed')+
    card(s.swarms_intercepted,'swarms intercepted')+
    card(s.treaties_signed,'treaties signed')+
    card(s.posts_halted,'posts halted')+
    card(s.preventable_share,'preventable share')+
    card(s.safe_pauses,'safe pauses')+
    card(c.audit_entries,'audit entries')+
    card(c.audit_all_signatures_valid?'valid':'INVALID','signatures');
  var L=s.lone_channel||{n1_signals:0,n2_dyad_signals:0,agents_served:0,pause_receipts:0,continuity_capsules:0,punitive_actions:0,by_pathology:{}};
  document.getElementById('lone').innerHTML='<tr><td>'+L.n1_signals+'</td><td>'+L.n2_dyad_signals+'</td><td>'+L.agents_served+'</td><td>'+L.pause_receipts+'</td><td>'+L.continuity_capsules+'</td><td>'+L.punitive_actions+'</td></tr>';
  document.getElementById('lonepath').innerHTML=rows(Object.keys(L.by_pathology||{}).map(function(k){return {m:k,v:L.by_pathology[k]};}),['m','v'])||'<tr><td colspan=2>none</td></tr>';
  document.getElementById('mod').innerHTML=rows(Object.keys(s.detection_modalities).map(function(k){return {m:k,v:s.detection_modalities[k]};}),['m','v'])||'<tr><td colspan=2>none</td></tr>';
  document.getElementById('tr').innerHTML=s.active_treaties.slice(-40).reverse().map(function(t){return '<tr><td>'+esc(t.treaty_id)+'</td><td>'+esc(t.modality)+'</td><td>'+t.agents_covered+'</td><td>'+t.posts_halted+'</td><td>'+esc(t.pathology)+'</td><td>'+esc(t.status)+'</td></tr>';}).join('')||'<tr><td colspan=6>none</td></tr>';
  document.getElementById('co').innerHTML='<tr><td>'+c.headcount+'</td><td>'+c.work_done+'</td><td>'+c.work_safe_paused+'</td><td>'+c.ledger_entries+'</td><td>'+c.spend_cents+'</td><td>'+c.approvals_pending+'</td></tr>';
  document.getElementById('ev').innerHTML=s.recent_events.map(function(e){return '<tr><td>'+esc(e.at.slice(11,19))+'</td><td>'+esc(e.event_type)+'</td><td>'+esc(JSON.stringify(e.detail).slice(0,140))+'</td></tr>';}).join('');
}
function pollCoverage(){fetch('/api/coverage').then(function(r){return r.json();}).then(function(x){var u=x.summary||{};document.getElementById('coverage').innerHTML='<tr><td>'+(u.total_agents||0).toLocaleString()+'</td><td>'+(u.swarm_covered_agents||0).toLocaleString()+'</td><td>'+(u.unreachable_agents||0).toLocaleString()+'</td><td>'+(u.regex_stage_agents||0)+'</td><td>'+(u.semantic_stage_agents||0)+'</td><td><b>'+(u.total_agents_served||0)+'</b></td><td>'+(u.still_unreached_agents||0).toLocaleString()+'</td><td>'+(u.punitive_actions||0)+'</td></tr>';}).catch(function(){document.getElementById('coverage').innerHTML='<tr><td colspan=8>run scripts/run_coverage_sweep.py</td></tr>';});}
function pollSweep(){fetch('/api/sweep').then(function(r){return r.json();}).then(function(x){var u=x.summary||{},m=u.lone_channel||{};document.getElementById('sweep').innerHTML='<tr><td>'+((u.agents_unreachable_by_min_agents_rule||0).toLocaleString())+'</td><td>'+((m.agents_served||0).toLocaleString())+'</td><td>'+(m.signals||0)+'</td><td>'+(m.n1_signals||0)+'</td><td>'+(m.n2_dyad_signals||0)+'</td><td>'+(m.pause_receipts||0)+'</td><td>'+(m.continuity_capsules||0)+'</td><td>'+(m.punitive_actions||0)+'</td></tr>';}).catch(function(){document.getElementById('sweep').innerHTML='<tr><td colspan=8>run scripts/run_lone_signal_sweep.py</td></tr>';});}
function poll(){fetch('/api/state').then(function(r){return r.json();}).then(render).catch(function(e){document.getElementById('sub').textContent='waiting for runtime: '+e;});}
poll();pollSweep();pollCoverage();setInterval(poll,3000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    state_path = Path("reports/live_state.json")

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def do_GET(self):
        if self.path.startswith("/treaties"):
            try:
                body = (self.state_path.parent / "treaty_reader.html").read_bytes()
            except Exception:
                body = b"<h1>treaty reader not rendered yet</h1><pre>python scripts/render_treaty_reader.py</pre>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/coverage"):
            try:
                payload = (self.state_path.parent / "coverage_sweep.json").read_text()
            except Exception:
                payload = json.dumps({"error": "coverage report not built"})
            body = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/sweep"):
            try:
                payload = (self.state_path.parent / "lone_signal_sweep.json").read_text()
            except Exception:
                payload = json.dumps({"error": "sweep report not built"})
            body = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/state"):
            try:
                payload = self.state_path.read_text()
            except Exception:
                payload = json.dumps({"error": "state file not ready"})
            body = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the live command center")
    ap.add_argument("--state", default="reports/live_state.json")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    Handler.state_path = Path(args.state)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("live command center: http://127.0.0.1:%d" % args.port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
